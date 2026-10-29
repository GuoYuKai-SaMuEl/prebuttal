"""Run history: every review run is archived under ~/.prebuttal (best-effort).

This is an *advanced* feature with zero footprint on basic usage: `run` still
works exactly as before; archiving happens silently afterwards and a failure
to archive never fails the run.  Set ``PREBUTTAL_HOME`` to relocate the store
(also used by the test suite for isolation).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .projects import atomic_write, load_projects, slugify


def runs_root() -> Path:
    base = os.environ.get("PREBUTTAL_HOME")
    return Path(base) if base else Path.home() / ".prebuttal"


def make_private_dir(path: Path) -> None:
    """Create ``path`` readable by the user only (0700 on POSIX).

    The store holds unpublished paper text, reviews and API keys; on shared
    machines (university clusters) the default 0755 would expose them to
    every other account.  Re-applied on each use so existing stores created
    by older versions get locked down too.  No-op where chmod can't apply.
    """
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o700)


def history_path() -> Path:
    return runs_root() / "history.jsonl"


def runs_dir() -> Path:
    return runs_root() / "runs"


@contextlib.contextmanager
def store_lock(*, required: bool = False) -> Iterator[None]:
    """Serialize writes to the history and the project registry between
    concurrent processes.

    A lock older than a minute means its holder crashed and is stolen.  A
    busy lock gives way after ~5s: archiving a (paid) run is never blocked,
    the worst case being the duplicate number this lock exists to avoid.
    ``required`` writers (note, rm, rename: whole-file rewrites that could
    drop a concurrent run) raise OSError instead of going on unlocked."""
    p = runs_root() / "history.lock"
    make_private_dir(runs_root())
    held = False
    for _ in range(100):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            held = True
            break
        except (FileExistsError, PermissionError):
            # Windows reports a lock file that is being unlinked this instant
            # (delete-pending) as PermissionError, not FileExistsError — both
            # mean "busy": sleep and retry, never let it escape the lock
            try:
                if time.time() - p.stat().st_mtime > 60:
                    # a crashed holder's lock: rename it away and try to create
                    # the next one.  This narrows the takeover race but does
                    # not fully close it: a waiter that stat'ed before the
                    # takeover can still rename a freshly created lock — which
                    # takes a stale lock to happen at all.
                    stolen = p.with_name(f"{p.name}.stolen-{os.getpid()}")
                    os.rename(p, stolen)
                    stolen.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            time.sleep(0.05)
    if required and not held:
        raise OSError("the run history is busy (another prebuttal is writing it) — try again")
    try:
        yield
    finally:
        if held:
            with contextlib.suppress(OSError):
                p.unlink(missing_ok=True)


def new_run_id(paper_title: str) -> str:
    # uuid tail keeps two runs of the same paper within one second distinct
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}-{slugify(paper_title, 32)}"


@dataclass
class RunRecord:
    id: str
    ts: str
    paper_title: str
    source: str
    venue: str
    seed: int
    mean: float | None
    std: float | None
    n: int
    dir: str
    project: str = ""
    run_no: int = 0  # 1, 2, 3 ... within the project; stable after deletions
    note: str = ""
    scale: float | None = None  # venue rating maximum, for trend charts

    @property
    def dir_path(self) -> Path:
        return Path(self.dir)

    @property
    def label(self) -> str:
        return f"{self.project}#{self.run_no}"

    @property
    def when(self) -> str:
        """``2026-10-25 15:30`` from the id's timestamp prefix."""
        m = re.match(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})", self.id)
        return f"{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}" if m else self.ts[:16]


_FIELDS = set(RunRecord.__dataclass_fields__)

_VENUE_SCALES: dict[str, float | None] = {}


def _venue_scale(venue: str) -> float | None:
    """Rating maximum of ``venue``, so runs archived before 0.2.0 (no
    ``scale`` field) still join score displays, trends and dashboards."""
    if not venue:
        return None
    if venue not in _VENUE_SCALES:
        try:
            from .venues import get_venue  # local import: keys.py pulls in this module

            _VENUE_SCALES[venue] = get_venue(venue).rating_field.max
        except Exception:
            _VENUE_SCALES[venue] = None
    return _VENUE_SCALES[venue]


def _order(r: RunRecord) -> tuple[str, int, str]:
    """Chronological order. Ids carry whole seconds plus a random tail, so two
    runs within one second are ordered by their (increasing) run number."""
    return (r.id[:15], r.run_no, r.id)


def save_run(
    report: Any,
    venue: Any,
    cfg: Any,
    *,
    md: str,
    json_str: str,
    html: str | None,
    project: str = "",
    note: str = "",
) -> RunRecord:
    """Archive one run. Raises OSError on failure; the caller treats it as non-fatal."""
    run_id = new_run_id(report.paper.title)
    make_private_dir(runs_root())
    project = project or slugify(report.paper.title)
    out_dir = runs_dir() / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(md, encoding="utf-8")
    (out_dir / "report.json").write_text(json_str, encoding="utf-8")
    if html:
        (out_dir / "report.html").write_text(html, encoding="utf-8")
    if getattr(report, "pack", ""):  # `prebuttal retry` re-sends exactly this text
        (out_dir / "pack.md").write_text(report.pack, encoding="utf-8")
    images = getattr(report.paper, "figure_images", None) or []
    if images:  # ... and these figures
        fig_dir = out_dir / "figures"
        fig_dir.mkdir(exist_ok=True)
        for i, im in enumerate(images, 1):
            (fig_dir / f"{i:02d}.png").write_bytes(im.png)
        (fig_dir / "figures.json").write_text(
            json.dumps([im.label for im in images], ensure_ascii=False), encoding="utf-8"
        )
    resolved = {
        "prebuttal_version": __version__,
        "venue": venue.key,
        "seed": cfg.seed,
        "config_path": cfg.config_path,
        "pack_sha256": report.run.pack_sha256,
        "reviewers": [
            {
                "id": r.reviewer_id,
                "persona": r.persona,
                "backend": r.backend,
                "model": r.model,
                "temperature": r.temperature,
                "seed": r.seed,
                "rating": r.rating,
                "parse_ok": r.parse_ok,
            }
            for r in report.reviews
        ],
        "ac": {"backend": report.meta.backend, "model": report.meta.model},
    }
    (out_dir / "resolved-config.json").write_text(
        json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with store_lock():
        run_no = 1 + max((r.run_no for r in load_history() if r.project == project), default=0)
        rec = RunRecord(
            id=run_id,
            ts=report.run.generated_at,
            paper_title=report.paper.title,
            source=report.run.source,
            venue=venue.key,
            seed=cfg.seed,
            mean=report.aggregate.mean,
            std=report.aggregate.std,
            n=report.aggregate.n,
            dir=str(out_dir),
            project=project,
            run_no=run_no,
            note=note,
            scale=venue.rating_field.max,
        )
        with history_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")
    return rec


def _read_history() -> tuple[list[RunRecord], list[str]]:
    """The history file's records, and the lines that are not one (kept on rewrite)."""
    p = history_path()
    if not p.is_file():
        return [], []
    records: list[RunRecord] = []
    unreadable: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            records.append(RunRecord(**{k: v for k, v in data.items() if k in _FIELDS}))
        except (ValueError, TypeError, AttributeError):
            unreadable.append(line)  # skip corrupt lines, never crash history reads
    return records, unreadable


def load_history() -> list[RunRecord]:
    """All archived runs, newest first.

    Records written before projects existed get one derived from the title
    and are numbered in date order, so old archives keep working unchanged.
    """
    out, _unreadable = _read_history()
    for rec in out:
        if rec.scale is None:  # runs archived before 0.2.0 have no scale
            rec.scale = _venue_scale(rec.venue)
    out.sort(key=_order)
    counters: dict[str, int] = {}
    for r in out:
        if not r.project:
            r.project = slugify(r.paper_title)
        if not r.run_no:
            r.run_no = counters.get(r.project, 0) + 1
        counters[r.project] = max(counters.get(r.project, 0), r.run_no)
    out.reverse()
    return out


def _rewrite_history(records: list[RunRecord]) -> None:
    ordered = sorted(records, key=_order)
    lines = [json.dumps(r.__dict__, ensure_ascii=False) for r in ordered]
    lines += _read_history()[1]  # lines load_history() skips are kept, not deleted
    atomic_write(history_path(), "".join(line + "\n" for line in lines))


def _update_history(apply: Callable[[list[RunRecord]], None]) -> list[RunRecord]:
    """Read-modify-write the history under the cross-process lock, so a run
    archived while ``note`` / ``rm`` / ``rename`` holds it cannot be lost to
    their full-file rewrite."""
    with store_lock(required=True):
        records = load_history()
        apply(records)
        _rewrite_history(records)
    return records


def set_note(run_id: str, note: str) -> None:
    def apply(records: list[RunRecord]) -> None:
        for r in records:
            if r.id == run_id:
                r.note = note

    _update_history(apply)


def delete_runs(run_ids: set[str]) -> int:
    """Remove runs from the history and delete their archived files."""
    removed: list[RunRecord] = []

    def apply(records: list[RunRecord]) -> None:
        removed.extend(r for r in records if r.id in run_ids)
        records[:] = [r for r in records if r.id not in run_ids]

    _update_history(apply)
    for r in removed:
        if r.dir_path.parent == runs_dir():
            shutil.rmtree(r.dir_path, ignore_errors=True)
    return len(removed)


def rename_in_history(old: str, new: str) -> int:
    n = 0

    def apply(records: list[RunRecord]) -> None:
        nonlocal n
        for r in records:
            if r.project == old:
                r.project = new
                n += 1

    _update_history(apply)
    return n


# ------------------------------------------------------------- run references


@dataclass
class ProjectSummary:
    key: str
    title: str
    runs: list[RunRecord]  # newest first

    @property
    def latest(self) -> RunRecord:
        return self.runs[0]


def project_summaries(records: list[RunRecord] | None = None) -> list[ProjectSummary]:
    """Projects with at least one run, most recently active first."""
    records = load_history() if records is None else records
    titles = {k: p.title for k, p in load_projects().items()}
    groups: dict[str, list[RunRecord]] = {}
    for r in records:  # newest first, so each group is too
        groups.setdefault(r.project, []).append(r)
    return [
        ProjectSummary(key=k, title=titles.get(k) or runs[0].paper_title, runs=runs)
        for k, runs in groups.items()
    ]


_REF_RE = re.compile(r"^(?P<project>[^#~]*)(?:(?P<op>[#~])(?P<num>\d+))?$")


def resolve_ref(ref: str | None) -> tuple[RunRecord | None, list[RunRecord]]:
    """Find a run from what a person would type.

    ``latest`` (or nothing)    newest run of any project
    ``mamba``                  newest run of project *mamba*
    ``mamba#3``                run 3 of *mamba*
    ``mamba~1``                one before the newest of *mamba*
    ``~1``                     one before the newest run of the newest project
    ``20261025-1530``          run id or unique id prefix; else a unique title/id substring

    Returns (match, candidates): candidates is non-empty when ambiguous.
    """
    hist = load_history()
    if not hist:
        return None, []
    ref = (ref or "latest").strip()
    if ref == "latest":
        return hist[0], []
    m = _REF_RE.match(ref)
    if m:
        project = m["project"] or (hist[0].project if m["op"] else "")
        runs = [r for r in hist if r.project == project]
        if runs:
            if m["op"] is None:
                return runs[0], []
            num = int(m["num"])
            if m["op"] == "#":
                hit = next((r for r in runs if r.run_no == num), None)
                return hit, ([] if hit else runs[:10])
            return (runs[num], []) if num < len(runs) else (None, runs[:10])
    return find_run(ref, hist)


def find_run(
    query: str, hist: list[RunRecord] | None = None
) -> tuple[RunRecord | None, list[RunRecord]]:
    """Resolve a run by exact id, unique id prefix, or unique title/id substring.

    Returns (match, candidates): candidates is non-empty when ambiguous.
    """
    hist = load_history() if hist is None else hist
    for r in hist:
        if r.id == query:
            return r, []
    pref = [r for r in hist if r.id.startswith(query)]
    if len(pref) == 1:
        return pref[0], []
    sub = [
        r for r in hist if query.lower() in r.id.lower() or query.lower() in r.paper_title.lower()
    ]
    if len(sub) == 1:
        return sub[0], []
    return None, (pref or sub)[:10]


def previous_run(rec: RunRecord) -> RunRecord | None:
    """The run before ``rec`` in the same project, if any."""
    runs = [r for r in load_history() if r.project == rec.project]
    idx = next(i for i, r in enumerate(runs) if r.id == rec.id)
    return runs[idx + 1] if idx + 1 < len(runs) else None


# ------------------------------------------------------------------ rendering


def _g(v: float | None) -> str:
    return "n/a" if v is None else f"{v:g}"


def _scored(mean: float | None, scale: float | None) -> str:
    return f"{mean:g}/{scale:g}" if mean is not None and scale else _g(mean)


def _delta(a: float | None, b: float | None) -> str:
    return f"  (Δ {b - a:+g})" if a is not None and b is not None else ""


def _score(r: RunRecord) -> str:
    return _scored(r.mean, r.scale)


def _table(rows: list[tuple[str, ...]]) -> str:
    """Left-aligned columns; the last column is free text and not padded."""
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]) - 1)]
    lines = []
    for i, row in enumerate(rows):
        cells = [c.ljust(w) for c, w in zip(row, widths, strict=False)]
        lines.append("  ".join([*cells, row[-1]]).rstrip())
        if i == 0:
            lines.append("-" * min(sum(widths) + 2 * len(widths) + 24, 100))
    return "\n".join(lines)


def render_runs_table(records: list[RunRecord]) -> str:
    if not records:
        return (
            "No saved runs yet. Runs are archived automatically under "
            f"{runs_root()} — see `prebuttal run`."
        )
    rows: list[tuple[str, ...]] = [("run", "date", "venue", "score", "σ", "note / title")]  # noqa: RUF001
    for r in records:
        std = f"{r.std:g}" if r.std is not None else "-"
        rows.append((r.label, r.when, r.venue, _score(r), std, (r.note or r.paper_title)[:50]))
    return _table(rows)


def render_projects_table(projects: list[ProjectSummary]) -> str:
    if not projects:
        return "No projects yet — `prebuttal run <paper>` creates one per paper."
    rows: list[tuple[str, ...]] = [("project", "runs", "latest", "trend", "last run", "title")]
    for p in projects:
        first, last = p.runs[-1], p.latest
        trend = "-"
        # a raw-mean trend across different rating scales (iclr /10 vs
        # neurips /6) compares incomparable numbers — skip it
        if (
            len(p.runs) > 1
            and first.mean is not None
            and last.mean is not None
            and first.scale == last.scale
        ):
            trend = f"{first.mean:g} → {last.mean:g} ({last.mean - first.mean:+g})"
        rows.append((p.key, str(len(p.runs)), _score(last), trend, last.when, p.title[:48]))
    return _table(rows)


def _weak_sim(a: str, b: str) -> float:
    wa = set(re.findall(r"[a-z0-9]+", a.lower()))
    wb = set(re.findall(r"[a-z0-9]+", b.lower()))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _num(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _load_run_json(rec: RunRecord) -> dict:
    p = Path(rec.dir) / "report.json"
    if not p.is_file():
        raise FileNotFoundError(f"archived report.json missing for {rec.id} ({p})")
    return json.loads(p.read_text(encoding="utf-8"))


def _by_persona(reviewers: list[dict]) -> dict[str, dict]:
    """Reviewers keyed by persona; a repeated persona gets ``persona #2``, ...
    so two reviewers sharing one never overwrite each other."""
    out: dict[str, dict] = {}
    for r in reviewers:
        base = str(r.get("persona") or "?")
        key, n = base, 1
        while key in out:
            n += 1
            key = f"{base} #{n}"
        out[key] = r
    return out


def render_diff(
    a: RunRecord,
    b: RunRecord,
    *,
    match_plan: Callable[[list[str], list[str], list[str]], Any] | None = None,
) -> str:
    """Human-readable A→B comparison: scores, per-reviewer ratings, weakness movement."""
    da, db = _load_run_json(a), _load_run_json(b)
    aa, ab = da.get("aggregate", {}), db.get("aggregate", {})
    ma, mb = _num(aa.get("mean")), _num(ab.get("mean"))
    scale = aa.get("rating_scale") or ab.get("rating_scale")

    out: list[str] = ["# Revision diff", ""]
    out.append(f"A · {a.id} · {a.ts} · seed {a.seed}")
    out.append(f"B · {b.id} · {b.ts} · seed {b.seed}")
    out.append("")

    out.append("## Predicted outcome")
    out.append(f"- A {_scored(ma, scale)} → B {_scored(mb, scale)}{_delta(ma, mb)}")
    sa, sb = _num(aa.get("std")), _num(ab.get("std"))
    if sa is not None and sb is not None:
        out.append(f"- disagreement σ {sa:g} → {sb:g}")  # noqa: RUF001
    out.append("")

    ea, eb = da.get("meta", {}), db.get("meta", {})
    va, vb = _num(ea.get("estimated_rating")), _num(eb.get("estimated_rating"))
    if va is not None or vb is not None:
        out.append("## Area chair")
        out.append(f"- AC estimate A {_scored(va, scale)} → B {_scored(vb, scale)}{_delta(va, vb)}")
        out.append("")

    ra, rb = _by_persona(da.get("reviewers", [])), _by_persona(db.get("reviewers", []))
    out.append("## Reviewer ratings (A → B)")
    for persona in sorted(set(ra) | set(rb)):
        x, y = ra.get(persona), rb.get(persona)
        fa = _num(x.get("rating")) if x else None
        fb = _num(y.get("rating")) if y else None
        out.append(f"- {persona}: {_g(fa)} → {_g(fb)}{_delta(fa, fb)}")
    out.append("")

    out.append("## Weakness movement (heuristic: ≥35% word overlap counts as the same weakness)")
    moved_any = False
    for persona in sorted(set(ra) & set(rb)):
        old = list((ra[persona].get("fields") or {}).get("weaknesses") or [])
        new = list((rb[persona].get("fields") or {}).get("weaknesses") or [])
        if not old and not new:
            continue
        remaining: list[str] = []
        gone: list[str] = []
        matched_new: set[int] = set()
        for ow in old:
            best_i, best_s = -1, 0.0
            for i, nw in enumerate(new):
                if i in matched_new:  # one-to-one: a new weakness answers one old one
                    continue
                s = _weak_sim(ow, nw)
                if s > best_s:
                    best_s, best_i = s, i
            if best_s >= 0.35:
                remaining.append(ow)
                matched_new.add(best_i)
            else:
                gone.append(ow)
        fresh = [nw for i, nw in enumerate(new) if i not in matched_new]
        if not (gone or fresh or remaining):
            continue
        moved_any = True
        out.append(f"### {persona}")
        for w in gone:
            out.append(f"- gone: {w[:220]}")
        for w in remaining:
            out.append(f"- persists: {w[:220]}")
        for w in fresh:
            out.append(f"- new: {w[:220]}")
        out.append("")
    if not moved_any:
        out.append("(no weaknesses reported in either run)")
        out.append("")

    plan_a = [it for it in (ea.get("action_plan") or []) if isinstance(it, dict)]
    plan_b = [it for it in (eb.get("action_plan") or []) if isinstance(it, dict)]
    if plan_a:
        a_issues = [str(it.get("issue", "")) for it in plan_a]
        b_plan_issues = [str(it.get("issue", "")) for it in plan_b]
        b_weak = [
            str(w)
            for r in db.get("reviewers", [])
            for w in ((r.get("fields") or {}).get("weaknesses") or [])
        ]
        match = match_plan(a_issues, b_plan_issues, b_weak) if match_plan else None
        if match is not None:
            out.append(f"## Revision plan of A, checked against B (matched by {match.label})")
            still_raised = [i in match.still for i in range(len(plan_a))]
            new = [b_plan_issues[j] for j in match.new_b]
        else:
            # an item is still open while B's plan or any B reviewer still raises it
            out.append(
                "## Revision plan of A, checked against B "
                "(heuristic: ≥35% word overlap with any B plan item or weakness)"
            )
            if match_plan:
                out.append("(model matching failed — fell back to word overlap)")
            b_texts = b_plan_issues + b_weak
            still_raised = [any(_weak_sim(x, t) >= 0.35 for t in b_texts) for x in a_issues]
            new = [x for x in b_plan_issues if not any(_weak_sim(x, y) >= 0.35 for y in a_issues)]
        n_gone = 0
        for it, issue, still in zip(plan_a, a_issues, still_raised, strict=True):
            n_gone += not still
            mark = "still raised" if still else "not re-detected"
            out.append(f"- {mark}: [{it.get('priority', '?')}] {issue[:200]}")
        for issue in new:
            out.append(f"- new in B: {issue[:200]}")
        out.append("")
        out.append(f"{n_gone} of {len(plan_a)} plan items were not re-detected in B.")
        if n_gone and new and match is None:
            # a reworded issue shows up twice: "not re-detected" and "new in B"
            out.append(
                "Matching is by wording: an issue B raises in other words counts as "
                "not re-detected *and* new — read the two lists side by side before "
                "ticking anything off (`prebuttal diff --llm` matches by meaning). "
                "Most reliable with the same backends and seed for both runs."
            )
        out.append("")

    out.append(
        "*Comparison of two simulated runs — same persona ≠ same reviewer; "
        "treat movements as signals, not measurements.*"
    )
    return "\n".join(out)
