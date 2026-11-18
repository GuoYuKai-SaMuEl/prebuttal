"""`prebuttal retry`: re-run only the reviewers that failed in an archived run.

A run where one reviewer hit an overloaded backend still paid for the others.
Retrying re-sends the *same* reviewer pack and figures (archived with the run)
to the failed reviewers only — same persona, backend, model, temperature and
seed — then re-runs the area chair over the merged reviews.  The result is
archived as a new run of the same project.  There is nothing to configure: a
different model is a different review, so it is a new run.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .config import ReviewerConfig, RunConfig
from .models import FigureImage, ReviewReport, figures_digest, sha256_text
from .orchestrator import Log, Slot, review_then_meta
from .providers import BaseProvider
from .report import report_from_dict
from .venues import Venue, VenueError, get_venue, venue_from_report


class RetryError(Exception):
    """The run cannot be retried (nothing failed, pack missing or changed...)."""


def failed_reviewers(report: ReviewReport) -> list[int]:
    return [i for i, r in enumerate(report.reviews) if not r.parse_ok]


def load_pack(run_dir: Path, sha256: str = "") -> str:
    """The exact text the original reviewers saw (archived since 0.4.0).

    ``sha256`` is the hash the report recorded: a pack.md edited or damaged
    since would mix reviews of two different texts in one report."""
    try:
        pack = (run_dir / "pack.md").read_text(encoding="utf-8")
    except FileNotFoundError:
        raise RetryError(
            "this run was archived before 0.4.0 without its reviewer text — start a new run instead"
        ) from None
    except (OSError, UnicodeDecodeError) as e:
        raise RetryError(
            f"the archived reviewer text (pack.md) is unreadable ({e}) — start a new run instead"
        ) from None
    if sha256 and sha256_text(pack) != sha256:
        raise RetryError(
            "the archived reviewer text (pack.md) changed since that run, so new reviews "
            "would not read what the others read — start a new run instead"
        )
    return pack


def load_figures(run_dir: Path, sha256: str = "") -> list[FigureImage]:
    """The figure images the original reviewers could see (none if not archived).

    All or nothing: with one image missing or replaced, the retried reviewers
    would see other figures than the reviews they are merged with.  ``sha256``
    is the hash the report recorded (since 0.7.0); without it, an index that
    names a missing image is still caught."""
    fig_dir = run_dir / "figures"
    index = fig_dir / "figures.json"
    images: list[FigureImage] = []
    if index.is_file():
        try:
            labels = json.loads(index.read_text(encoding="utf-8"))
            if not isinstance(labels, list):
                raise ValueError("not a list")
            images = [
                FigureImage(label=str(label), png=(fig_dir / f"{i:02d}.png").read_bytes())
                for i, label in enumerate(labels, 1)
            ]
        except (OSError, ValueError) as e:
            raise RetryError(
                f"the archived figure images of that run are incomplete ({e}) — start a new "
                "run instead"
            ) from None
    if sha256 and figures_digest(images) != sha256:
        raise RetryError(
            "the archived figure images changed since that run, so new reviews would not "
            "see what the others saw — start a new run instead"
        )
    return images


def venue_for_retry(data: dict, path: str = "") -> Venue:
    """The venue to *run* with: custom venues need their form text, which
    report.json does not store, so the venue file must still exist unchanged.
    ``path``: the venue file the run used (recorded since 0.7.0), tried first —
    a venue given as a path is not found by its name."""
    stored = venue_from_report(data)
    if not stored.custom:
        return stored
    from .venues.custom import load_venue_file

    try:
        live = load_venue_file(path) if path and Path(path).is_file() else get_venue(stored.key)
    except VenueError as e:
        raise RetryError(f"custom venue '{stored.key}' is needed to retry: {e}") from e
    if not live.custom:  # the name became built in after that run (cvpr in 0.5.3)
        raise RetryError(
            f"'{stored.key}' is now a built-in venue, so the custom '{stored.key}' venue of "
            "that run can't be retried — rename your venue file (e.g. "
            f"{stored.key}-lab.toml) and start a new run with it"
        )
    from .venues.custom import venue_to_spec

    if venue_to_spec(live) != venue_to_spec(stored):
        raise RetryError(f"custom venue '{stored.key}' changed since that run")
    v = data.get("venue")
    form_hash = v.get("form_sha256") if isinstance(v, dict) else None
    # recorded since 0.7.0: a form text edited since would review against other guidelines
    if form_hash and sha256_text(live.form_text()) != form_hash:
        raise RetryError(f"the review form of custom venue '{stored.key}' changed since that run")
    return live


def _version(v: str) -> tuple[int, ...]:
    nums = []
    for part in str(v).split(".")[:3]:
        digits = "".join(c for c in part if c.isdigit())
        nums.append(int(digits) if digits else 0)
    return tuple(nums)


def load_resolved(run_dir: Path, made_by: str = "") -> dict:
    """The run's ``resolved-config.json``: {} for a run archived before 0.7.0
    without what retry needs from it; for a run of 0.7.0 or later
    (``made_by``: the report's prebuttal version) a missing or unreadable
    file is a damaged archive, not an old one."""
    p = run_dir / "resolved-config.json"
    if not p.is_file():
        if made_by and _version(made_by) >= (0, 7, 0):
            raise RetryError("the archived resolved-config.json is missing")
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # UnicodeDecodeError is a ValueError
        raise RetryError(f"the archived resolved-config.json is unreadable ({e})") from None
    if not isinstance(data, dict):
        raise RetryError("the archived resolved-config.json is not a JSON object")
    if made_by and _version(made_by) >= (0, 7, 0):
        lost = [k for k in _RETRY_KEYS if k not in data]
        if lost:  # what retry runs with: none may be missing from a 0.7.0+ run
            raise RetryError(
                f"the archived resolved-config.json lacks {', '.join(lost)} — start a new run"
            )
    return data


# what a run of 0.7.0 or later records for `retry` in resolved-config.json
_RETRY_KEYS = ("max_tokens", "budget_chars", "agents", "venue_path")


def retry_config(cfg: RunConfig, resolved: dict, backends: set[str]) -> RunConfig:
    """``cfg`` with what the archived run recorded (``resolved-config.json``,
    since 0.7.0): the same output cap and review budget for the AC, whatever
    folder `retry` starts from.  A custom agent about to run (one of
    ``backends``) whose command changed since is refused: the same backend
    name would run another program; agents of reviews that are kept are not
    run, and not checked."""
    out = replace(cfg)
    # a field that is absent: an older archive, the current setting stands;
    # one that is there with a wrong type: a damaged archive
    for key in ("max_tokens", "budget_chars"):
        if key not in resolved:
            continue
        v = resolved[key]
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise RetryError(f"the archived resolved-config.json has an invalid {key}: {v!r}")
        setattr(out, key, v)
    agents = resolved.get("agents", {})
    if not isinstance(agents, dict) or not all(isinstance(s, dict) for s in agents.values()):
        raise RetryError("the archived resolved-config.json has an invalid 'agents' entry")
    venue_path = resolved.get("venue_path", "")
    if not isinstance(venue_path, str):
        raise RetryError("the archived resolved-config.json has an invalid 'venue_path'")
    if resolved.get("prebuttal_version") and _version(str(resolved["prebuttal_version"])) >= (
        0,
        7,
        0,
    ):
        # every custom agent about to run must have been recorded: else the
        # current [agents] entry would run unchecked
        custom = {b[6:] for b in backends if b.startswith("agent-") and b[6:] in cfg.agents}
        unrecorded = sorted(custom - set(agents))
        if unrecorded:
            raise RetryError(
                f"the archived resolved-config.json has no settings for custom agent(s) "
                f"{', '.join(unrecorded)} — start a new run"
            )
    endpoints = resolved.get("endpoints")
    if endpoints is not None and not isinstance(endpoints, dict):
        raise RetryError("the archived resolved-config.json has an invalid 'endpoints'")
    moved = endpoint_changes(endpoints, backends)
    if moved:
        raise RetryError(
            "the paper would go somewhere else than in that run: "
            + "; ".join(moved)
            + " — set it back (OPENAI_BASE_URL / OLLAMA_HOST) or start a new run"
        )
    for name, spec in agents.items():
        if f"agent-{name}" not in backends:
            continue
        now = cfg.agents.get(name)
        was = spec if isinstance(spec, dict) else {}
        if now is None or [now.command, now.stdin] != [was.get("command"), was.get("stdin")]:
            raise RetryError(
                f"custom agent '{name}' is not configured as it was for that run "
                "(command or stdin changed, or no [agents] entry here) — retry from the "
                "folder of that run's prebuttal.toml, or start a new run"
            )
    return out


def unrecorded_endpoints(resolved: dict, backends: set[str]) -> list[str]:
    """``backend → endpoint`` for each of ``backends`` whose destination the
    environment decides, in a run that did not record it (archived before
    endpoints were): where a retry would send the paper now, to confirm."""
    from .providers import backend_endpoint

    if resolved.get("endpoints") is not None:
        return []
    return [f"{b} → {u}" for b in sorted(backends) if (u := backend_endpoint(b))]


def endpoint_changes(recorded: dict | None, backends: set[str]) -> list[str]:
    """The backends of ``backends`` whose destination now differs from the one
    ``recorded`` (``resolved-config.json`` "endpoints"; None: not recorded,
    before 0.7.0)."""
    from .providers import backend_endpoint

    if recorded is None:
        return []
    out = []
    for b in sorted(backends):
        now = backend_endpoint(b)
        was = recorded.get(b, "")
        if now and now != was:
            out.append(f"{b} {was or '(not recorded)'} → {now}")
    return out


def retry_report(
    data: dict,
    pack: str,
    venue: Venue,
    cfg: RunConfig,
    providers: dict[str, BaseProvider],
    ac_provider: BaseProvider,
    log: Log,
    images: list[FigureImage] | None = None,
) -> ReviewReport:
    """Re-run the failed reviewers of ``data`` (a report.json) plus the AC.

    ``providers`` maps the ids of the reviewers to retry to their backends.
    Ctrl-C raises RunInterrupted with what finished, as for `prebuttal run`."""
    old = report_from_dict(data)
    targets = failed_reviewers(old)
    # each failed review again: same reviewer, round and (explicit) seed
    slots = [
        Slot(
            ReviewerConfig(
                id=r.reviewer_id,
                persona=r.persona,
                backend=providers[r.reviewer_id].backend,
                model=providers[r.reviewer_id].model,
                temperature=r.temperature,
            ),
            index=n,
            repeat=r.repeat,
            seed=r.seed,  # as recorded: already stepped for its round
        )
        for n, r in enumerate(old.reviews[i] for i in targets)
    ]
    sub = replace(cfg, seed=old.run.seed, reviewers=[s.reviewer for s in slots])
    sub.ac = replace(cfg.ac, temperature=old.meta.temperature)
    old.paper.figure_images = list(images or [])  # shown again, archived again
    old.paper.source_path, old.paper.source_type = old.run.source, old.run.source_type
    keep = [None if i in targets else r for i, r in enumerate(old.reviews)]
    return review_then_meta(old.paper, sub, venue, pack, providers, ac_provider, log, keep, slots)
