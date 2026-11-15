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
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field

from .revdiff import (
    WORD_OVERLAP,
    Matcher,
    PlanCheck,
    PlanItemStatus,
    PlanMatch,
    ac_wrote_plan,
    check_plan,
    plan_items,
)
from .runs import RunRecord, _load_run_json, retried

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


def ac_finished(rec: RunRecord) -> bool:
    """Whether the run's AC wrote its revision plan. A run cut short, whose
    AC failed or left the plan empty has none, and checked against it every
    earlier item would read as fixed; such a run is skipped when following
    the plan."""
    try:
        return ac_wrote_plan(_load_run_json(rec))
    except (OSError, ValueError):
        return False


def _followed(runs: Iterable[RunRecord]) -> list[RunRecord]:
    """The runs a plan is followed through (newest first): those whose AC
    finished, less any run a finished `prebuttal retry` completed: the retry
    has the same paper with the missing reviews, so it is not a revision of it."""
    runs = list(runs)
    done = [r for r in runs if ac_finished(r)]
    # a retry whose AC failed was retried again: the last one completes both
    replaced = {x for r in done if r.retry_of for x in retried(runs, r.retry_of)}
    return [r for r in done if r.id not in replaced]


def plan_base(earlier: Iterable[RunRecord], skip: str | None = None) -> RunRecord | None:
    """The run a plan is followed from: the newest of ``earlier`` (newest
    first, same project) that :func:`_followed` keeps, other than ``skip``
    (the run a retry completes, and any run that one retried)."""
    earlier = list(earlier)
    gone = retried(earlier, skip)
    return next((r for r in _followed(earlier) if r.id not in gone), None)


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
        track = PlanTrack(**data)
    except (OSError, ValueError, TypeError):
        return None
    return track if _well_formed(track) else None


def _strs(v: object) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _well_formed(t: PlanTrack) -> bool:
    """A file edited by hand or cut short is computed again, not trusted."""
    return (
        all(isinstance(v, str) for v in (t.a, t.b, t.key, t.matched_by))
        and isinstance(t.by_words, bool)
        and all(_strs(v) for v in (t.a_ids, t.b_ids, t.still, t.new_in_b))
        and isinstance(t.links, dict)
        and all(isinstance(k, str) and _strs(v) for k, v in t.links.items())
    )


def save_track(b: RunRecord, track: PlanTrack) -> None:
    """Into run ``b``'s folder. Raises OSError; callers treat it as non-fatal."""
    data = {"schema": TRACK_SCHEMA, **asdict(track)}
    (b.dir_path / TRACK_FILE).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def keep_diff_check(a: RunRecord, b: RunRecord, pc: PlanCheck | None) -> None:
    """`prebuttal diff` of two consecutive runs: its plan check, when a model
    made it, is the track (no second call). Best effort. Not when B's AC wrote
    no plan: the plan is never followed through such a run."""
    if pc is None or pc.by_words or not pc.b_ac_plan:
        return
    try:
        da, db = _load_run_json(a), _load_run_json(b)
        track = track_from_check(a, b, pc, _plans_key(da, db))
        if track is not None:
            save_track(b, track)
    except (OSError, ValueError):
        pass


def _fits(t: PlanTrack, da: dict, db: dict) -> bool:
    """The kept match is for these very plans: same hash, same ids (each
    once), and every id it names is in them."""
    if t.key != _plans_key(da, db):
        return False
    a_ids = [it["id"] for it in plan_items(da)]
    b_ids = [it["id"] for it in plan_items(db)]
    if a_ids != t.a_ids or b_ids != t.b_ids:
        return False
    if len(set(a_ids)) < len(a_ids) or len(set(b_ids)) < len(b_ids):
        return False  # duplicate ids (a report edited by hand): not followable
    b_refs = set(t.new_in_b) | {x for js in t.links.values() for x in js}
    return (set(t.still) | set(t.links)) <= set(a_ids) and b_refs <= set(b_ids)


def saved_check(a: RunRecord, b: RunRecord) -> PlanCheck | None:
    """The plan check a model made for this very pair (at the end of run
    ``b``, or by an earlier `diff`) while both plans are unchanged, so `diff`
    shows it instead of asking again. None when there is none."""
    try:
        da, db = _load_run_json(a), _load_run_json(b)
    except (OSError, ValueError):
        return None
    t = _load(b)
    if t is None or t.by_words or t.a != a.id or not _fits(t, da, db):
        return None
    plan_a, plan_b = plan_items(da), plan_items(db)
    a_ids, b_ids = t.a_ids, t.b_ids
    ai, bi = {x: i for i, x in enumerate(a_ids)}, {x: j for j, x in enumerate(b_ids)}
    match = PlanMatch(
        still={ai[x] for x in t.still},
        new_b=sorted(bi[x] for x in set(t.new_in_b)),
        label=t.matched_by,
        links={ai[k]: sorted(bi[x] for x in v) for k, v in t.links.items()},
    )
    return PlanCheck(
        items=[
            PlanItemStatus(
                str(it.get("priority", "?")), str(it.get("issue", "")), it["id"] in t.still
            )
            for it in plan_a
        ],
        new_in_b=[str(plan_b[j].get("issue", "")) for j in match.new_b],
        matched_by=t.matched_by,
        by_words=False,
        fell_back=False,
        a_ids=a_ids,
        b_ids=b_ids,
        match=match,
        b_ac_plan=ac_wrote_plan(db),
    )


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
        and _fits(cached, da, db)
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
    """History of the latest plan of one project (``runs`` newest first).
    Runs whose AC wrote no plan (cut short, AC failed) are stepped over."""
    runs = _followed(runs)
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
    # latest id -> the ids it goes back to in the run being walked (several
    # when two earlier items merged into one: the oldest of them counts)
    current = {lid: {lid} for lid in hist}
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
        back: dict[str, set[str]] = {}
        for a_id, b_ids in track.links.items():
            for b_id in b_ids:
                back.setdefault(b_id, set()).add(a_id)
        current = {
            lid: olds
            for lid, cids in current.items()
            if (olds := {a for cid in cids for a in back.get(cid, ())})
        }
        for lid in current:
            hist[lid].since = older.run_no
        if not current:
            break
    return out
