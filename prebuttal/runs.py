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
import sys
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


_LOCK_WAIT_S = 5.0  # note, rm, rename, key set, project registration
_ARCHIVE_WAIT_S = 600.0  # archiving a finished (paid) run waits longer


def _try_lock(fd: int) -> bool:
    """An operating-system lock on ``fd``: released by the OS when its holder
    exits or crashes, so there is no stale lock to guess about, and two
    holders are impossible (a lock is per open file, so per process and per
    thread here)."""
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def store_lock(*, wait_s: float | None = None) -> Iterator[None]:
    """Serialize writes to the history and the project registry between
    concurrent processes (and threads).

    Every writer holds it: a busy lock is waited for ``wait_s`` (default
    :data:`_LOCK_WAIT_S`), then OSError — nothing is ever written unlocked.
    The lock file itself stays; holding is the OS lock on it."""
    make_private_dir(runs_root())
    p = runs_root() / "history.lock"
    fd = os.open(p, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + (_LOCK_WAIT_S if wait_s is None else wait_s)
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise OSError(
                    "the run history is busy (another prebuttal is writing it) — try again"
                )
            time.sleep(0.05)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


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
    # the panel mean of each round when the run had several (`repeats`), so
    # diff and the dashboard need not reread report.json; None for one round
    round_means: list[float] | None = None
    # `prebuttal retry`: the id of the run this one completes (and replaces
    # when following the revision plan)
    retry_of: str | None = None
    # the first run of this version of the paper: a retry's original, kept
    # even if the runs between are deleted (None: itself, or before 0.7.0)
    version: str | None = None
    version_no: int = 0  # that first run's number (0: itself, or before 0.7.0)

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


def comparable(a: RunRecord, b: RunRecord) -> bool:
    """Whether two runs' raw scores compare: one venue, one scale.

    A shared maximum is not enough — ICLR and ICML both rate out of 10, but
    an 8 means "accept, good paper" on one form and "top 50% of accepted
    papers" on the other."""
    return (a.venue or "").lower() == (b.venue or "").lower() and a.scale == b.scale


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


def _write_run_files(
    out_dir: Path, report: Any, md: str, json_str: str, html: str | None, resolved: dict
) -> None:
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
    (out_dir / "resolved-config.json").write_text(
        json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _backends(report: Any) -> set[str]:
    return {r.backend for r in report.reviews} | {report.meta.backend}


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
    retry_of: str | None = None,
) -> RunRecord:
    """Archive one run. Raises OSError on failure; the caller treats it as non-fatal."""
    make_private_dir(runs_root())
    project = project or slugify(report.paper.title)
    resolved = {
        "prebuttal_version": __version__,
        "venue": venue.key,
        # the run's own seed: a retry keeps the one of the run it completes,
        # whatever prebuttal.toml in the folder it is started from says
        "seed": report.run.seed,
        # from the reviews, not cfg: a retry redoes slots of the run it completes
        "repeats": max((r.repeat for r in report.reviews), default=0) + 1,
        "config_path": cfg.config_path,
        "pack_sha256": report.run.pack_sha256,
        "reviewers": [
            {
                "id": r.reviewer_id,
                "repeat": r.repeat,
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
        # what `retry` must run with again, whatever folder it starts from
        "max_tokens": cfg.max_tokens,
        "budget_chars": cfg.budget_chars,
        "venue_path": venue.origin,  # a custom venue's file ("" built in)
        "agents": {
            name: {"command": spec.command, "stdin": spec.stdin}
            for name, spec in cfg.agents.items()
            if any(b == f"agent-{name}" for b in _backends(report))
        },
    }
    # the run's files are written under the lock too, but nothing is paid for
    # while waiting: the reviews are done.  A holder that crashed releases it
    with store_lock(wait_s=_ARCHIVE_WAIT_S):
        # the id's time and the run number are both taken under the lock: two
        # runs saved at once across a second boundary must not get ids in one
        # order and numbers in the other (history is ordered by the id's time)
        from .projects import Project, current_key, load_projects, save_projects

        projects = load_projects()
        # renamed while this run was reviewing: archive it under the new name
        project = current_key(projects, project)
        run_id = new_run_id(report.paper.title)
        out_dir = runs_dir() / run_id
        _write_run_files(out_dir, report, md, json_str, html, resolved)
        proj = projects.get(project)
        # one past the highest number ever given: after `rm` of the newest run
        # its #N must not come back pointing at another report
        run_no = 1 + max(
            max((r.run_no for r in load_history() if r.project == project), default=0),
            proj.last_run_no if proj else 0,
        )
        rec = RunRecord(
            id=run_id,
            ts=report.run.generated_at,
            paper_title=report.paper.title,
            source=report.run.source,
            venue=venue.key,
            seed=report.run.seed,
            mean=report.aggregate.mean,
            std=report.aggregate.std,
            n=report.aggregate.n,
            dir=str(out_dir),
            project=project,
            run_no=run_no,
            note=note,
            scale=venue.rating_field.max,
            round_means=list(rm) if len(rm := report.aggregate.round_means) > 1 else None,
            retry_of=retry_of,
            version=(v := _version_of_retry(retry_of) if retry_of else None),
            version_no=_version_no(v) if v else 0,
        )
        with history_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")
        if proj is None:  # archived without `assign_project` (a script, an old project)
            proj = projects[project] = Project(
                key=project, title=report.paper.title, created=time.strftime("%Y-%m-%dT%H:%M:%S")
            )
        proj.last_run_no = run_no
        # best effort: the run is archived; a lost counter only means the
        # history's own maximum is used next time
        with contextlib.suppress(OSError):
            save_projects(projects)
    return rec


def _read_history() -> tuple[list[RunRecord], list[str]]:
    """The history file's records, and the lines that are not one (kept on rewrite)."""
    p = history_path()
    if not p.is_file():
        return [], []
    records: list[RunRecord] = []
    unreadable: list[str] = []
    # JSONL lines end in "\n" only: splitlines() would also break a record at a
    # U+2028 / U+0085 kept verbatim in a title or note (ensure_ascii=False)
    for line in p.read_text(encoding="utf-8").split("\n"):
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


def rewrite_history(records: list[RunRecord]) -> None:
    """Replace the history file with ``records``; the caller holds :func:`store_lock`."""
    ordered = sorted(records, key=_order)
    lines = [json.dumps(r.__dict__, ensure_ascii=False) for r in ordered]
    lines += _read_history()[1]  # lines load_history() skips are kept, not deleted
    atomic_write(history_path(), "".join(line + "\n" for line in lines))


def _update_history(apply: Callable[[list[RunRecord]], None]) -> list[RunRecord]:
    """Read-modify-write the history under the cross-process lock, so a run
    archived while ``note`` / ``rm`` / ``rename`` holds it cannot be lost to
    their full-file rewrite."""
    with store_lock():
        records = load_history()
        apply(records)
        rewrite_history(records)
    return records


def set_note(run_id: str, note: str) -> None:
    def apply(records: list[RunRecord]) -> None:
        for r in records:
            if r.id == run_id:
                r.note = note

    _update_history(apply)


def delete_runs(run_ids: set[str]) -> int:
    """Delete runs' archived files, then drop from the history the runs whose
    files are gone.  A folder that cannot be deleted (a file held open on
    Windows) keeps its run listed, so `rm` can be tried again; OSError then
    names what is left, after the others are deleted."""
    removed: list[RunRecord] = []
    left: list[str] = []
    # the files go first, outside the lock (a slow disk must not hold it while
    # a run is being archived); the history is then read afresh under it
    for r in load_history():
        if r.id not in run_ids:
            continue
        if r.dir_path.parent == runs_dir() and r.dir_path.exists():
            try:
                shutil.rmtree(r.dir_path)
            except OSError as e:
                left.append(f"{r.label}: {e}")
                continue
        removed.append(r)
    gone = {r.id for r in removed}

    def apply(records: list[RunRecord]) -> None:
        _keep_run_numbers(records, gone)
        _keep_versions(records, gone)
        records[:] = [r for r in records if r.id not in gone]

    _update_history(apply)
    if left:
        raise OSError(
            f"deleted {len(removed)} run(s); could not delete "
            + "; ".join(left)
            + " — they stay listed: close what holds them and run `prebuttal rm` again"
        )
    return len(removed)


def _keep_versions(records: list[RunRecord], run_ids: set[str]) -> None:
    """Before a version's first run leaves the history, its retries record it
    (``version``, ``version_no``): retries archived before 0.7.0 do not, and
    would lose the version's place once that run is gone."""
    for first in (r for r in records if r.id in run_ids):
        for r in records:
            if r.id in run_ids or r.id == first.id:
                continue
            if version_key(records, r) == first.id:
                r.version = first.id
                r.version_no = r.version_no or first.run_no


def _keep_run_numbers(records: list[RunRecord], run_ids: set[str]) -> None:
    """Before runs leave the history, the registry keeps each project's highest
    number (a registry from before 0.7.0 has none): #N is never given again."""
    from .projects import Project, load_projects, save_projects

    projects = load_projects()
    changed = False
    for key in {r.project for r in records if r.id in run_ids}:
        top = max((r.run_no for r in records if r.project == key), default=0)
        proj = projects.get(key) or Project(key=key)
        if top > proj.last_run_no:
            proj.last_run_no = top
            projects[key] = proj
            changed = True
    if changed:
        save_projects(projects)


# ------------------------------------------------------------- run references


@dataclass
class ProjectSummary:
    key: str
    title: str
    runs: list[RunRecord]  # newest first

    @property
    def latest(self) -> RunRecord:
        """The most recent run (for "last run" times)."""
        return self.runs[0]

    @property
    def current(self) -> RunRecord:
        """The run that stands for the newest version of the paper: its score
        is the project's score, as trends and `diff` count versions — a
        retry of v1 made after v2 is not the latest score."""
        return revisions(self.runs)[0]


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


def version_key(runs: list[RunRecord], rec: RunRecord) -> str:
    """The id of the first run of ``rec``'s version of the paper: a retry, a
    retry of that retry, ... and the run they complete share it."""
    if rec.version:
        return rec.version
    by_id = {r.id: r for r in runs}
    run_id, seen = rec.id, set()
    while run_id not in seen:
        seen.add(run_id)
        cur = by_id.get(run_id)
        if cur is None:
            return run_id
        if cur.version:
            return cur.version
        if not cur.retry_of:
            return run_id
        run_id = cur.retry_of
    return run_id


def _version_no(version: str) -> int:
    """The run number of ``version``'s first run (read under the lock)."""
    runs = load_history()
    first = next((r for r in runs if r.id == version), None)
    if first is not None:
        return first.run_no
    # deleted: another retry of it may have kept the number
    return next((r.version_no for r in runs if r.version == version and r.version_no), 0)


def _version_start(runs: list[RunRecord], key: str, members: list[int]) -> tuple[str, int]:
    """When a version started: its first run's time (from the id, which
    outlives the run) and number (that run's, or the one its retries keep)."""
    first = next((r for r in runs if r.id == key), None)
    if first is not None:
        no = first.run_no
    else:
        no = next((runs[i].version_no for i in members if runs[i].version_no), 0)
        no = no or min(runs[i].run_no for i in members)
    return key[:15], no


def _version_of_retry(retry_of: str) -> str:
    """The version a new retry of ``retry_of`` belongs to (read under the lock)."""
    return version_of_id(load_history(), retry_of)


def version_of_id(runs: list[RunRecord], run_id: str) -> str:
    """:func:`version_key` of the run ``run_id`` (itself if it is not in ``runs``)."""
    rec = next((r for r in runs if r.id == run_id), None)
    return version_key(runs, rec) if rec is not None else run_id


def revisions(
    runs: list[RunRecord], keep: Callable[[RunRecord], bool] | None = None
) -> list[RunRecord]:
    """One run per version of the paper, newest version first: the newest run
    of each version (a finished `prebuttal retry` stands for the run it
    completes, and the newer of two retries for both), versions ordered by
    when their first run was made — a retry of v1 made after v2 is still v1.

    Every view that compares versions (trends, `diff`, the `Change:` line,
    the dashboard, the revision plan) goes through this one rule.  ``keep``:
    only such runs stand for a version (the plan: those whose AC finished);
    versions are still told apart through all of ``runs``."""
    runs = list(runs)
    groups: dict[str, list[int]] = {}
    for i, r in enumerate(runs):  # newest first
        if keep is None or keep(r):
            groups.setdefault(version_key(runs, r), []).append(i)
    # a version is as old as its first run: its id's time and its number,
    # kept by its retries when it is deleted or filtered out (newest first)
    order = sorted(groups.items(), key=lambda kv: _version_start(runs, kv[0], kv[1]), reverse=True)
    return [runs[min(idx)] for _key, idx in order]


def previous_version(runs: list[RunRecord], key: str | None) -> RunRecord | None:
    """The newest run of the version before ``key`` in ``runs`` (newest first,
    one project) — or of the newest version when ``key`` is not among them
    (a run not archived yet)."""
    vs = revisions(runs)
    keys = [version_key(runs, r) for r in vs]
    if key in keys:
        i = keys.index(key)
        return vs[i + 1] if i + 1 < len(vs) else None
    return vs[0] if vs else None


def previous_run(rec: RunRecord) -> RunRecord | None:
    """The run before ``rec``'s version of the paper, same project: for a retry,
    the version before the one it completes (the same paper, not a revision)."""
    runs = [r for r in load_history() if r.project == rec.project]
    if not any(r.id == rec.id for r in runs):
        return None
    return previous_version(runs, version_key(runs, rec))


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
        versions = revisions(p.runs)  # a retry and the run it completes: one version
        first, last = versions[-1], p.current
        trend = "-"
        # a raw-mean trend across venues (iclr /10 vs neurips /6, or even
        # iclr /10 vs icml /10) compares incomparable numbers — skip it
        if (
            len(versions) > 1
            and first.mean is not None
            and last.mean is not None
            and comparable(first, last)
        ):
            trend = f"{first.mean:g} → {last.mean:g} ({last.mean - first.mean:+g})"
        rows.append((p.key, str(len(p.runs)), _score(last), trend, p.latest.when, p.title[:48]))
    return _table(rows)


def _num(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _load_run_json(rec: RunRecord) -> dict:
    p = Path(rec.dir) / "report.json"
    if not p.is_file():
        raise FileNotFoundError(f"archived report.json missing for {rec.id} ({p})")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):  # ValueError, as for broken JSON: callers catch it
        raise ValueError(f"archived report.json of {rec.label} is not a report")
    return data
