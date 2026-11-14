"""Following a project's revision plan across runs (#1 -> #2 -> #3 ...).

Each pair of consecutive runs is matched as `prebuttal diff` matches plans
(:func:`~prebuttal.revdiff.check_plan`). A match made with a model is kept in
the later run's folder (``plan-track.json``), so the dashboard can show where
each item of the latest plan came from without calling a model. It is redone
only when either plan changed, or when it was made by word overlap and a
model is now at hand.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from dataclasses import asdict, dataclass, field

from .revdiff import WORD_OVERLAP, Matcher, PlanCheck, check_plan, plan_items
from .runs import RunRecord, _load_run_json

TRACK_FILE = "plan-track.json"
TRACK_SCHEMA = 1


@dataclass
class PlanTrack:
    """The plan of run ``a`` checked against the next run ``b``."""

    a: str  # run ids
    b: str
    key: str  # both plans' hash: a changed archive is matched again
    matched_by: str
    by_words: bool
    a_ids: list[str] = field(default_factory=list)
    b_ids: list[str] = field(default_factory=list)
    still: list[str] = field(default_factory=list)  # A items B still raises
    links: dict[str, list[str]] = field(default_factory=dict)  # A item -> same B items
    new_in_b: list[str] = field(default_factory=list)


def _plans_key(da: dict, db: dict) -> str:
    texts = [[str(it.get("issue", "")) for it in plan_items(d)] for d in (da, db)]
    return hashlib.sha256(json.dumps(texts).encode("utf-8")).hexdigest()[:16]


def _compute(a: RunRecord, b: RunRecord, da: dict, db: dict, matcher: Matcher) -> PlanTrack | None:
    pc = check_plan(matcher, da, db)
    return None if pc is None else track_from_check(a, b, pc, _plans_key(da, db))


def track_from_check(a: RunRecord, b: RunRecord, pc: PlanCheck, key: str) -> PlanTrack | None:
    if pc.match is None:
        return None
    m = pc.match
    return PlanTrack(
        a=a.id,
        b=b.id,
        key=key,
        matched_by=pc.matched_by,
        by_words=pc.by_words,
        a_ids=pc.a_ids,
        b_ids=pc.b_ids,
        still=[pc.a_ids[i] for i in sorted(m.still)],
        links={pc.a_ids[i]: [pc.b_ids[j] for j in js] for i, js in sorted(m.links.items())},
        new_in_b=[pc.b_ids[j] for j in sorted(set(m.new_b))],
    )


def _load(b: RunRecord) -> PlanTrack | None:
    try:
        data = json.loads((b.dir_path / TRACK_FILE).read_text(encoding="utf-8"))
        data.pop("schema", None)
        return PlanTrack(**data)
    except (OSError, ValueError, TypeError):
        return None


def save_track(b: RunRecord, track: PlanTrack) -> None:
    """Into run ``b``'s folder. Raises OSError; callers treat it as non-fatal."""
    data = {"schema": TRACK_SCHEMA, **asdict(track)}
    (b.dir_path / TRACK_FILE).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def keep_diff_check(a: RunRecord, b: RunRecord, pc: PlanCheck | None) -> None:
    """`prebuttal diff` of two consecutive runs: its plan check, when a model
    made it, is the track (no second call). Best effort."""
    if pc is None or pc.by_words:
        return
    try:
        da, db = _load_run_json(a), _load_run_json(b)
        track = track_from_check(a, b, pc, _plans_key(da, db))
        if track is not None:
            save_track(b, track)
    except (OSError, ValueError):
        pass


def track_pair(a: RunRecord, b: RunRecord, matcher: Matcher | None = None) -> PlanTrack | None:
    """A's plan checked against B (None when A has no plan).

    With a ``matcher``, a result made by a model is saved for later; without
    one, the saved result is used, else word overlap (nothing saved, no call).
    Raises FileNotFoundError when an archive is gone."""
    da, db = _load_run_json(a), _load_run_json(b)
    cached = _load(b)
    if (
        cached is not None
        and cached.a == a.id
        and cached.key == _plans_key(da, db)
        and (not cached.by_words or matcher is None or matcher is WORD_OVERLAP)
    ):
        return cached
    track = _compute(a, b, da, db, matcher or WORD_OVERLAP)
    if track is not None and matcher is not None and not track.by_words:
        with contextlib.suppress(OSError):  # a cache: next time it is computed again
            save_track(b, track)
    return track


# ------------------------------------------------------------------ history


@dataclass
class ItemHistory:
    id: str
    priority: str
    issue: str
    since: int  # run number where this item first appeared


@dataclass
class ProjectPlan:
    """The latest run's plan, each item with where it came from."""

    run: RunRecord
    items: list[ItemHistory]
    previous: RunRecord | None = None
    # the previous run's items the latest run no longer raises: (priority, issue)
    dropped: list[tuple[str, str]] = field(default_factory=list)
    by_words: bool = False  # some link in the history was matched by wording


def project_plan(runs: list[RunRecord]) -> ProjectPlan | None:
    """History of the latest plan of one project (``runs`` newest first)."""
    if not runs:
        return None
    latest = runs[0]
    try:
        items = plan_items(_load_run_json(latest))
    except (OSError, ValueError):
        return None
    if not items:
        return None
    hist = {it["id"]: ItemHistory(it["id"], str(it.get("priority", "?")),
                                  str(it.get("issue", "")), latest.run_no)
            for it in items}  # fmt: skip
    out = ProjectPlan(run=latest, items=list(hist.values()))
    current = {lid: lid for lid in hist}  # latest id -> its id in the run being walked
    for older, newer in zip(runs[1:], runs, strict=False):
        try:
            track = track_pair(older, newer)
            older_plan = plan_items(_load_run_json(older)) if newer is latest else []
        except (OSError, ValueError):
            break
        if track is None:
            break
        out.by_words = out.by_words or track.by_words
        if newer is latest:
            out.previous = older
            raised = set(track.still)
            out.dropped = [
                (str(it.get("priority", "?")), str(it.get("issue", "")))
                for it in older_plan
                if it["id"] not in raised
            ]
        back: dict[str, str] = {}
        for a_id, b_ids in track.links.items():
            for b_id in b_ids:
                back.setdefault(b_id, a_id)
        current = {lid: back[cid] for lid, cid in current.items() if cid in back}
        for lid in current:
            hist[lid].since = older.run_no
        if not current:
            break
    return out
