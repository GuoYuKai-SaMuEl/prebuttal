"""`prebuttal diff`: compare two archived runs of the same paper.

Two layers: :func:`compute_diff` reads both runs' ``report.json`` into a
:class:`RevisionDiff` (plain data, also what a dashboard or a later run can
read), and :func:`render_diff_markdown` prints it.

Which weakness or plan item in B "is the same" as one in A is the job of a
:class:`Matcher`.  :class:`WordOverlap` is the offline one; a model-backed
matcher (``diffmatch.ModelMatcher``) can answer either question, and any
question it cannot answer falls back to word overlap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from .noise import NoiseCheck, check_noise
from .runs import RunRecord, _delta, _g, _load_run_json, _num, _scored

SAME = 0.35  # word-overlap (Jaccard) at which two texts count as the same issue


@dataclass
class PlanMatch:
    still: set[int]  # indices into A's plan that B still raises
    new_b: list[int]  # indices into B's plan that A's plan did not contain
    label: str  # who matched, for the report header
    # A item -> the B plan items that are the same issue (to follow an item
    # across runs); an A item B raises only in a weakness has none
    links: dict[int, list[int]] = field(default_factory=dict)


Pairs = list[int | None]  # for each old weakness, the new one it matches, or None


class Matcher(Protocol):
    """Decides which texts in two runs name the same problem.

    Either method may return None ("could not tell"), and ``weaknesses`` may
    return None for one reviewer; the diff then uses word overlap there."""

    label: str

    def weaknesses(self, groups: list[tuple[list[str], list[str]]]) -> list[Pairs | None] | None:
        """For each reviewer's (old, new) weaknesses: for each old one, the index
        of the new one it matches (one-to-one), or None."""
        ...

    def plan(self, a_plan: list[str], b_plan: list[str], b_weak: list[str]) -> PlanMatch | None:
        """Which of A's plan items B still raises, and which of B's plan items are new."""
        ...


def word_sim(a: str, b: str) -> float:
    wa = set(re.findall(r"[a-z0-9]+", a.lower()))
    wb = set(re.findall(r"[a-z0-9]+", b.lower()))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


class WordOverlap:
    """The offline matcher: ≥35% shared words counts as the same issue."""

    label = "word overlap"

    def weaknesses(self, groups: list[tuple[list[str], list[str]]]) -> list[Pairs | None]:
        return [self.pairs(old, new) for old, new in groups]

    def pairs(self, old: list[str], new: list[str]) -> Pairs:
        taken: set[int] = set()
        out: list[int | None] = []
        for ow in old:
            best_i, best_s = -1, 0.0
            for i, nw in enumerate(new):
                if i in taken:  # one-to-one: a new weakness answers one old one
                    continue
                s = word_sim(ow, nw)
                if s > best_s:
                    best_s, best_i = s, i
            if best_s >= SAME:
                taken.add(best_i)
                out.append(best_i)
            else:
                out.append(None)
        return out

    def plan(self, a_plan: list[str], b_plan: list[str], b_weak: list[str]) -> PlanMatch:
        # an item is still open while B's plan or any B reviewer still raises it
        b_texts = b_plan + b_weak
        still = {i for i, x in enumerate(a_plan) if any(word_sim(x, t) >= SAME for t in b_texts)}
        new_b = [j for j, x in enumerate(b_plan) if not any(word_sim(x, y) >= SAME for y in a_plan)]
        links = {
            i: same
            for i, x in enumerate(a_plan)
            if (same := [j for j, y in enumerate(b_plan) if word_sim(x, y) >= SAME])
        }
        return PlanMatch(still=still, new_b=new_b, label=self.label, links=links)


WORD_OVERLAP = WordOverlap()


# ------------------------------------------------------------------ the diff


@dataclass
class RatingChange:
    reviewer: str  # ``R1 · senior_kind``
    a: float | None  # with `repeats`: the mean of the reviewer's rounds
    b: float | None
    rounds: tuple[int, int] = (1, 1)  # reviews of this reviewer in A, in B


@dataclass
class Weakness:
    text: str
    seen_a: int = 0  # rounds of A that raised it (with `repeats`, can be < rounds)
    seen_b: int = 0


@dataclass
class WeaknessMovement:
    reviewer: str
    gone: list[Weakness] = field(default_factory=list)
    persists: list[Weakness] = field(default_factory=list)
    new: list[Weakness] = field(default_factory=list)
    rounds: tuple[int, int] = (1, 1)


@dataclass
class PlanItemStatus:
    priority: str
    issue: str
    still_raised: bool


@dataclass
class PlanCheck:
    """A's revision plan, checked against B."""

    items: list[PlanItemStatus]
    new_in_b: list[str]
    matched_by: str  # Matcher.label of whoever answered
    by_words: bool  # answered by word overlap (as chosen, or as the fallback)
    fell_back: bool  # a model matcher was asked and could not answer
    # the plan ids (P1, P2...; by position in runs before 0.6.1) and the
    # answer itself, so the plan can be followed across runs (plantrack)
    a_ids: list[str] = field(default_factory=list)
    b_ids: list[str] = field(default_factory=list)
    match: PlanMatch | None = None

    @property
    def not_redetected(self) -> int:
        return sum(not it.still_raised for it in self.items)


@dataclass
class RevisionDiff:
    a: RunRecord
    b: RunRecord
    scale_a: float | None
    scale_b: float | None
    mean: tuple[float | None, float | None]
    std: tuple[float | None, float | None]
    ac_estimate: tuple[float | None, float | None]
    ratings: list[RatingChange]
    weaknesses: list[WeaknessMovement]  # reviewers in both runs with any weakness
    weaknesses_by_words: bool  # any reviewer's weaknesses matched by word overlap
    weaknesses_matched_by: str  # Matcher.label, when not by words
    plan: PlanCheck | None  # None when A has no plan
    # the panel means of each round (`repeats`); one or none for a single run
    round_means: tuple[list[float], list[float]] = ([], [])

    @property
    def same_scale(self) -> bool:
        """Raw scores compare only on one scale (unknown scales are given the benefit)."""
        return self.scale_a == self.scale_b or not (self.scale_a and self.scale_b)

    @property
    def noise(self) -> NoiseCheck | None:
        """Whether the predicted score's change can be told from run-to-run noise;
        None when there is nothing to compare (no score, or not one known scale)."""
        ma, mb = self.mean
        scale = self.scale_b or self.scale_a
        if ma is None or mb is None or not scale or not self.same_scale:
            return None
        return check_noise(ma, mb, *self.round_means, scale)


def _by_reviewer(reviewers: list[dict]) -> dict[str, list[dict]]:
    """Reviews keyed ``R1 · senior_kind``: each reviewer's rounds (`repeats`)
    together. A reviewer whose persona changed between runs is a different
    one, so its ratings are never compared."""
    out: dict[str, list[dict]] = {}
    for i, r in enumerate(reviewers):
        rid = str(r.get("reviewer_id") or f"#{i + 1}")
        out.setdefault(f"{rid} · {r.get('persona') or '?'}", []).append(r)
    return out


def _mean_rating(reviews: list[dict]) -> float | None:
    got = [v for r in reviews if (v := _num(r.get("rating"))) is not None]
    return round(sum(got) / len(got), 2) if got else None


def _weaknesses_of(r: dict) -> list[str]:
    return [str(w) for w in (r.get("fields") or {}).get("weaknesses") or []]


def _merged_weaknesses(reviews: list[dict]) -> list[tuple[str, int]]:
    """One reviewer's weaknesses over its rounds, each once (by wording), with
    the number of rounds that raised it. A single review: each seen once."""
    merged: list[tuple[str, set[int]]] = []
    for k, r in enumerate(reviews):
        for w in _weaknesses_of(r):
            same = next((m for m in merged if k not in m[1] and word_sim(m[0], w) >= SAME), None)
            if same is not None:
                same[1].add(k)
            else:
                merged.append((w, {k}))
    return [(text, len(rounds)) for text, rounds in merged]


def _by_words(matcher: Matcher) -> bool:
    return isinstance(matcher, WordOverlap)


def _valid_pairs(got: object, old: list[str], new: list[str]) -> bool:
    """One answer per old weakness, each a distinct index into ``new`` (or None)."""
    if not isinstance(got, list) or len(got) != len(old):
        return False
    picked = [j for j in got if j is not None]
    return len(set(picked)) == len(picked) and all(_index_ok(j, len(new)) for j in picked)


def _match_weaknesses(
    matcher: Matcher, groups: list[tuple[list[str], list[str]]]
) -> list[tuple[Pairs, bool]]:
    """Each reviewer's pairs, and whether word overlap produced them."""
    got = matcher.weaknesses(groups) if any(o and n for o, n in groups) else None
    if not isinstance(got, list) or len(got) != len(groups):
        got = [None] * len(groups)
    out: list[tuple[Pairs, bool]] = []
    for (old, new), pairs in zip(groups, got, strict=True):
        if not (old and new):  # nothing to pair: no matcher needed
            out.append(([None] * len(old), _by_words(matcher)))
        elif pairs is not None and _valid_pairs(pairs, old, new):
            out.append((pairs, _by_words(matcher)))
        else:
            out.append((WORD_OVERLAP.pairs(old, new), True))
    return out


def _index_ok(j: object, n: int) -> bool:
    return isinstance(j, int) and not isinstance(j, bool) and 0 <= j < n


def _valid_plan(m: PlanMatch, n_a: int, n_b: int) -> bool:
    if not isinstance(m.links, dict):
        return False
    linked_ok = all(
        _index_ok(i, n_a) and isinstance(js, list) and all(_index_ok(j, n_b) for j in js)
        for i, js in m.links.items()
    )
    return (
        linked_ok
        and all(_index_ok(i, n_a) for i in m.still)
        and all(_index_ok(j, n_b) for j in m.new_b)
    )


def plan_items(data: dict) -> list[dict]:
    """A report.json's revision plan, each item with its id (by position when
    the run predates plan ids)."""
    items = [it for it in (data.get("meta", {}).get("action_plan") or []) if isinstance(it, dict)]
    return [{**it, "id": str(it.get("id") or f"P{n}")} for n, it in enumerate(items, 1)]


def check_plan(matcher: Matcher, da: dict, db: dict) -> PlanCheck | None:
    """A's revision plan (report.json ``da``) checked against B; None when A has none."""
    plan_a = plan_items(da)
    if not plan_a:
        return None
    plan_b = plan_items(db)
    a_issues = [str(it.get("issue", "")) for it in plan_a]
    b_issues = [str(it.get("issue", "")) for it in plan_b]
    b_weak = [str(w) for r in db.get("reviewers", []) for w in _weaknesses_of(r)]
    match = matcher.plan(a_issues, b_issues, b_weak)
    # a Matcher is public API: an answer with an index it got wrong is not
    # trusted at all, as for weaknesses
    fell_back = match is None or not _valid_plan(match, len(a_issues), len(b_issues))
    if fell_back or match is None:
        match = WORD_OVERLAP.plan(a_issues, b_issues, b_weak)
    by_words = fell_back or _by_words(matcher)
    return PlanCheck(
        items=[
            PlanItemStatus(str(it.get("priority", "?")), issue, i in match.still)
            for i, (it, issue) in enumerate(zip(plan_a, a_issues, strict=True))
        ],
        new_in_b=[b_issues[j] for j in sorted(set(match.new_b))],
        matched_by=match.label,
        by_words=by_words,
        fell_back=fell_back,
        a_ids=[it["id"] for it in plan_a],
        b_ids=[it["id"] for it in plan_b],
        match=match,
    )


def compute_diff(a: RunRecord, b: RunRecord, *, matcher: Matcher | None = None) -> RevisionDiff:
    """Compare run A with run B.  Raises FileNotFoundError if an archive is gone."""
    matcher = matcher or WORD_OVERLAP
    da, db = _load_run_json(a), _load_run_json(b)
    aa, ab = da.get("aggregate", {}), db.get("aggregate", {})
    ea, eb = da.get("meta", {}), db.get("meta", {})
    ra, rb = _by_reviewer(da.get("reviewers", [])), _by_reviewer(db.get("reviewers", []))

    ratings = [
        RatingChange(
            key,
            _mean_rating(ra.get(key, [])),
            _mean_rating(rb.get(key, [])),
            (len(ra.get(key, [])), len(rb.get(key, []))),
        )
        for key in sorted(set(ra) | set(rb))
    ]

    both = sorted(set(ra) & set(rb))
    merged = {k: (_merged_weaknesses(ra[k]), _merged_weaknesses(rb[k])) for k in both}
    keys = [k for k in both if merged[k][0] or merged[k][1]]
    groups = [([t for t, _n in merged[k][0]], [t for t, _n in merged[k][1]]) for k in keys]
    movements: list[WeaknessMovement] = []
    used_words: list[bool] = []
    for key, (pairs, words) in zip(keys, _match_weaknesses(matcher, groups), strict=True):
        old, new = merged[key]
        used_words.append(words)
        matched = {j for j in pairs if j is not None}
        movements.append(
            WeaknessMovement(
                key,
                gone=[Weakness(t, n) for (t, n), j in zip(old, pairs, strict=True) if j is None],
                persists=[
                    Weakness(t, n, new[j][1])
                    for (t, n), j in zip(old, pairs, strict=True)
                    if j is not None
                ],
                new=[Weakness(t, 0, n) for j, (t, n) in enumerate(new) if j not in matched],
                rounds=(len(ra[key]), len(rb[key])),
            )
        )

    return RevisionDiff(
        a=a,
        b=b,
        scale_a=_num(aa.get("rating_scale")) or a.scale,
        scale_b=_num(ab.get("rating_scale")) or b.scale,
        mean=(_num(aa.get("mean")), _num(ab.get("mean"))),
        std=(_num(aa.get("std")), _num(ab.get("std"))),
        ac_estimate=(_num(ea.get("estimated_rating")), _num(eb.get("estimated_rating"))),
        ratings=ratings,
        weaknesses=movements,
        weaknesses_by_words=not used_words or any(used_words),
        weaknesses_matched_by=matcher.label,
        plan=check_plan(matcher, da, db),
        round_means=(_round_means(aa), _round_means(ab)),
    )


def _round_means(agg: dict) -> list[float]:
    """The round means a report.json stores (none before 0.7)."""
    got = agg.get("round_means")
    vals = [_num(x) for x in got] if isinstance(got, list) else []
    return [v for v in vals if v is not None]


# ------------------------------------------------------------------ rendering


def render_diff_markdown(d: RevisionDiff) -> str:
    a, b, same = d.a, d.b, d.same_scale
    out: list[str] = ["# Revision diff", ""]
    out.append(f"A · {a.id} · {a.ts} · seed {a.seed}")
    out.append(f"B · {b.id} · {b.ts} · seed {b.seed}")
    out.append("")

    ma, mb = d.mean
    out.append("## Predicted outcome")
    delta = _delta(ma, mb) if same else "  (venue changed — raw means are not comparable)"
    out.append(f"- A {_scored(ma, d.scale_a)} → B {_scored(mb, d.scale_b)}{delta}")
    if (noise := d.noise) is not None:
        out.extend(_noise_lines(noise))
    sa, sb = d.std
    if sa is not None and sb is not None:
        out.append(f"- disagreement σ {sa:g} → {sb:g}")  # noqa: RUF001
    out.append("")

    va, vb = d.ac_estimate
    if va is not None or vb is not None:
        out.append("## Area chair")
        ac_delta = _delta(va, vb) if same else ""
        checked = "  (not noise-checked: one estimate per run)" if ac_delta else ""
        out.append(
            f"- AC estimate A {_scored(va, d.scale_a)} → B {_scored(vb, d.scale_b)}"
            f"{ac_delta}{checked}"
        )
        out.append("")

    out.append("## Reviewer ratings (A → B; single reviews — treat as anecdotes)")
    for rc in d.ratings:
        ka, kb = rc.rounds
        of = f"  (mean of {ka} → {kb} rounds)" if max(ka, kb) > 1 else ""
        out.append(
            f"- {rc.reviewer}: {_g(rc.a)} → {_g(rc.b)}{_delta(rc.a, rc.b) if same else ''}{of}"
        )
    out.append("")

    if d.weaknesses_by_words:
        out.append(
            "## Weakness movement (heuristic: ≥35% word overlap counts as the same weakness)"
        )
    else:
        out.append(f"## Weakness movement (matched by {d.weaknesses_matched_by})")
    for mv in d.weaknesses:
        out.append(f"### {mv.reviewer}")
        ka, kb = mv.rounds
        out.extend(f"- gone: {w.text[:220]}{_seen(w.seen_a, ka, 'A')}" for w in mv.gone)
        out.extend(
            f"- persists: {w.text[:220]}{_seen(w.seen_a, ka, 'A')}{_seen(w.seen_b, kb, 'B')}"
            for w in mv.persists
        )
        out.extend(f"- new: {w.text[:220]}{_seen(w.seen_b, kb, 'B')}" for w in mv.new)
        once = [w for w in mv.gone + mv.persists if ka > 1 and w.seen_a == 1]
        once += [w for w in mv.persists + mv.new if kb > 1 and w.seen_b == 1]
        if once:
            out.append("(raised in 1 round only: may be chance, as a single review is)")
        out.append("")
    if not d.weaknesses:
        out.append("(no weaknesses reported in either run)")
        out.append("")

    if d.plan is not None:
        _render_plan_check(out, d.plan)

    out.append(
        "*Comparison of two simulated runs — same persona ≠ same reviewer; "
        "treat movements as signals, not measurements.*"
    )
    return "\n".join(out)


def _seen(seen: int, rounds: int, side: str) -> str:
    """`` (A: 2 of 3 rounds)`` for a side with several rounds, else empty."""
    return f" ({side}: {seen} of {rounds} rounds)" if rounds > 1 else ""


def _noise_lines(n: NoiseCheck) -> list[str]:
    verdict = "within run-to-run noise" if n.within else "larger than run-to-run noise"
    if n.measured:
        source = f"measured: {n.rounds_a} and {n.rounds_b} rounds"
    elif n.estimated:
        source = "estimated — not measured on this paper"
    else:
        side, rounds = ("A", n.rounds_a) if n.rounds_a else ("B", n.rounds_b)
        source = f"measured on {side} ({rounds} rounds), estimated for the other run"
    lines = [f"  {verdict} (±{n.band:g}, {source})"]
    if n.within and not n.measured:
        lines.append("  `repeats = 3` in prebuttal.toml measures it for your paper")
    return lines


def _render_plan_check(out: list[str], pc: PlanCheck) -> None:
    if not pc.by_words:
        out.append(f"## Revision plan of A, checked against B (matched by {pc.matched_by})")
    else:
        out.append(
            "## Revision plan of A, checked against B "
            "(heuristic: ≥35% word overlap with any B plan item or weakness)"
        )
        if pc.fell_back:
            out.append("(model matching failed — fell back to word overlap)")
    for it in pc.items:
        mark = "still raised" if it.still_raised else "not re-detected"
        out.append(f"- {mark}: [{it.priority}] {it.issue[:200]}")
    for issue in pc.new_in_b:
        out.append(f"- new in B: {issue[:200]}")
    out.append("")
    n_gone = pc.not_redetected
    out.append(f"{n_gone} of {len(pc.items)} plan items were not re-detected in B.")
    if n_gone and pc.new_in_b and pc.by_words:
        # a reworded issue shows up twice: "not re-detected" and "new in B"
        out.append(
            "Matching is by wording: an issue B raises in other words counts as "
            "not re-detected *and* new — read the two lists side by side before "
            "ticking anything off (with a model backend for the AC, `prebuttal diff` "
            "matches by meaning: `prebuttal backends`). "
            "Most reliable with the same backends and seed for both runs."
        )
    out.append("")


def render_diff(a: RunRecord, b: RunRecord, *, matcher: Matcher | None = None) -> str:
    """Human-readable A→B comparison: scores, per-reviewer ratings, weakness movement."""
    return render_diff_markdown(compute_diff(a, b, matcher=matcher))


__all__ = [
    "SAME",
    "WORD_OVERLAP",
    "Matcher",
    "Pairs",
    "PlanCheck",
    "PlanItemStatus",
    "PlanMatch",
    "RatingChange",
    "RevisionDiff",
    "Weakness",
    "WeaknessMovement",
    "WordOverlap",
    "check_plan",
    "compute_diff",
    "plan_items",
    "render_diff",
    "render_diff_markdown",
    "word_sim",
]
