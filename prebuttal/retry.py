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
from .models import FigureImage, ReviewReport
from .orchestrator import Log, review_then_meta
from .providers import BaseProvider
from .report import report_from_dict
from .venues import Venue, VenueError, get_venue, venue_from_report


class RetryError(Exception):
    """The run cannot be retried (nothing failed, pack missing or changed...)."""


def failed_reviewers(report: ReviewReport) -> list[int]:
    return [i for i, r in enumerate(report.reviews) if not r.parse_ok]


def load_pack(run_dir: Path) -> str:
    """The exact text the original reviewers saw (archived since 0.4.0)."""
    try:
        return (run_dir / "pack.md").read_text(encoding="utf-8")
    except OSError:
        raise RetryError(
            "this run was archived before 0.4.0 without its reviewer text — start a new run instead"
        ) from None


def load_figures(run_dir: Path) -> list[FigureImage]:
    """The figure images the original reviewers could see (none if not archived)."""
    fig_dir = run_dir / "figures"
    try:
        labels = json.loads((fig_dir / "figures.json").read_text(encoding="utf-8"))
        return [
            FigureImage(label=str(label), png=(fig_dir / f"{i:02d}.png").read_bytes())
            for i, label in enumerate(labels, 1)
        ]
    except (OSError, ValueError, TypeError):
        return []


def venue_for_retry(data: dict) -> Venue:
    """The venue to *run* with: custom venues need their form text, which
    report.json does not store, so the venue file must still exist unchanged."""
    stored = venue_from_report(data)
    if not stored.custom:
        return stored
    try:
        live = get_venue(stored.key)
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
    return live


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
    sub = replace(
        cfg,
        seed=old.run.seed,
        reviewers=[
            ReviewerConfig(
                id=old.reviews[i].reviewer_id,
                persona=old.reviews[i].persona,
                backend=providers[old.reviews[i].reviewer_id].backend,
                model=providers[old.reviews[i].reviewer_id].model,
                temperature=old.reviews[i].temperature,
                seed=old.reviews[i].seed,
            )
            for i in targets
        ],
    )
    sub.ac = replace(cfg.ac, temperature=old.meta.temperature)
    old.paper.figure_images = list(images or [])  # shown again, archived again
    old.paper.source_path, old.paper.source_type = old.run.source, old.run.source_type
    keep = [None if i in targets else r for i, r in enumerate(old.reviews)]
    return review_then_meta(old.paper, sub, venue, pack, providers, ac_provider, log, keep)
