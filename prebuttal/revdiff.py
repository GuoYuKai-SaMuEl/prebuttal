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

from .runs import RunRecord, _delta, _g, _load_run_json, _num, _scored

SAME = 0.35  # word-overlap (Jaccard) at which two texts count as the same issue


@dataclass
class PlanMatch:
    still: set[int]  # indices into A's plan that B still raises
    new_b: list[int]  # indices into B's plan that A's plan did not contain
    label: str  # who matched, for the report header


class Matcher(Protocol):
    """Decides which texts in two runs name the same problem.

    Either method may return None ("could not tell"); the diff then uses
    word overlap for that question."""

    label: str

    def weaknesses(self, old: list[str], new: list[str]) -> list[int | None] | None:
        """For each old weakness, the index of the new one it matches (one-to-one)."""
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

    def weaknesses(self, old: list[str], new: list[str]) -> list[int | None]:
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
        return PlanMatch(still=still, new_b=new_b, label=self.label)


WORD_OVERLAP = WordOverlap()


# ------------------------------------------------------------------ the diff


@dataclass
class RatingChange:
    reviewer: str  # persona; a repeated persona is ``persona #2``, ...
    a: float | None
    b: float | None


@dataclass
class WeaknessMovement:
    reviewer: str
    gone: list[str] = field(default_factory=list)
    persists: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)


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

    @property
    def same_scale(self) -> bool:
        """Raw scores compare only on one scale (unknown scales are given the benefit)."""
        return self.scale_a == self.scale_b or not (self.scale_a and self.scale_b)


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


def _weaknesses_of(r: dict) -> list[str]:
    return list((r.get("fields") or {}).get("weaknesses") or [])


def _by_words(matcher: Matcher) -> bool:
    return isinstance(matcher, WordOverlap)


def _valid_pairs(got: list[int | None] | None, old: list[str], new: list[str]) -> bool:
    """One answer per old weakness, each a distinct index into ``new`` (or None)."""
    if got is None or len(got) != len(old):
        return False
    picked = [j for j in got if j is not None]
    return len(set(picked)) == len(picked) and all(
        isinstance(j, int) and 0 <= j < len(new) for j in picked
    )


def _match_weaknesses(
    matcher: Matcher, old: list[str], new: list[str]
) -> tuple[list[int | None], bool]:
    """The pairs, and whether word overlap produced them."""
    got = matcher.weaknesses(old, new)
    if got is not None and _valid_pairs(got, old, new):
        return got, _by_words(matcher)
    return WORD_OVERLAP.weaknesses(old, new), True


def _check_plan(matcher: Matcher, da: dict, db: dict) -> PlanCheck | None:
    plan_a = [it for it in (da.get("meta", {}).get("action_plan") or []) if isinstance(it, dict)]
    if not plan_a:
        return None
    plan_b = [it for it in (db.get("meta", {}).get("action_plan") or []) if isinstance(it, dict)]
    a_issues = [str(it.get("issue", "")) for it in plan_a]
    b_issues = [str(it.get("issue", "")) for it in plan_b]
    b_weak = [str(w) for r in db.get("reviewers", []) for w in _weaknesses_of(r)]
    match = matcher.plan(a_issues, b_issues, b_weak)
    fell_back = match is None
    if match is None:
        match = WORD_OVERLAP.plan(a_issues, b_issues, b_weak)
    by_words = fell_back or _by_words(matcher)
    new_b: list[int] = []
    for j in match.new_b:  # a Matcher is public API: drop indices it got wrong
        if (
            isinstance(j, int)
            and not isinstance(j, bool)
            and j not in new_b
            and 0 <= j < len(b_issues)
        ):
            new_b.append(j)
    return PlanCheck(
        items=[
            PlanItemStatus(str(it.get("priority", "?")), issue, i in match.still)
            for i, (it, issue) in enumerate(zip(plan_a, a_issues, strict=True))
        ],
        new_in_b=[b_issues[j] for j in new_b],
        matched_by=match.label,
        by_words=by_words,
        fell_back=fell_back,
    )


def compute_diff(a: RunRecord, b: RunRecord, *, matcher: Matcher | None = None) -> RevisionDiff:
    """Compare run A with run B.  Raises FileNotFoundError if an archive is gone."""
    matcher = matcher or WORD_OVERLAP
    da, db = _load_run_json(a), _load_run_json(b)
    aa, ab = da.get("aggregate", {}), db.get("aggregate", {})
    ea, eb = da.get("meta", {}), db.get("meta", {})
    ra, rb = _by_persona(da.get("reviewers", [])), _by_persona(db.get("reviewers", []))

    ratings = []
    for persona in sorted(set(ra) | set(rb)):
        x, y = ra.get(persona), rb.get(persona)
        ratings.append(
            RatingChange(
                persona, _num(x.get("rating")) if x else None, _num(y.get("rating")) if y else None
            )
        )

    movements: list[WeaknessMovement] = []
    used_words: list[bool] = []
    for persona in sorted(set(ra) & set(rb)):
        old, new = _weaknesses_of(ra[persona]), _weaknesses_of(rb[persona])
        if not old and not new:
            continue
        pairs, words = _match_weaknesses(matcher, old, new)
        used_words.append(words)
        matched = {j for j in pairs if j is not None}
        movements.append(
            WeaknessMovement(
                persona,
                gone=[w for w, j in zip(old, pairs, strict=True) if j is None],
                persists=[w for w, j in zip(old, pairs, strict=True) if j is not None],
                new=[w for j, w in enumerate(new) if j not in matched],
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
        plan=_check_plan(matcher, da, db),
    )


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
    sa, sb = d.std
    if sa is not None and sb is not None:
        out.append(f"- disagreement σ {sa:g} → {sb:g}")  # noqa: RUF001
    out.append("")

    va, vb = d.ac_estimate
    if va is not None or vb is not None:
        out.append("## Area chair")
        ac_delta = _delta(va, vb) if same else ""
        out.append(
            f"- AC estimate A {_scored(va, d.scale_a)} → B {_scored(vb, d.scale_b)}{ac_delta}"
        )
        out.append("")

    out.append("## Reviewer ratings (A → B)")
    for rc in d.ratings:
        out.append(f"- {rc.reviewer}: {_g(rc.a)} → {_g(rc.b)}{_delta(rc.a, rc.b) if same else ''}")
    out.append("")

    if d.weaknesses_by_words:
        out.append(
            "## Weakness movement (heuristic: ≥35% word overlap counts as the same weakness)"
        )
    else:
        out.append(f"## Weakness movement (matched by {d.weaknesses_matched_by})")
    for mv in d.weaknesses:
        out.append(f"### {mv.reviewer}")
        out.extend(f"- gone: {w[:220]}" for w in mv.gone)
        out.extend(f"- persists: {w[:220]}" for w in mv.persists)
        out.extend(f"- new: {w[:220]}" for w in mv.new)
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
            "ticking anything off (`prebuttal diff --llm` matches by meaning). "
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
    "PlanCheck",
    "PlanItemStatus",
    "PlanMatch",
    "RatingChange",
    "RevisionDiff",
    "WeaknessMovement",
    "WordOverlap",
    "compute_diff",
    "render_diff",
    "render_diff_markdown",
    "word_sim",
]
