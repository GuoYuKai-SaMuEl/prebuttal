"""`prebuttal diff` internals: the RevisionDiff data and the Matcher interface."""

from __future__ import annotations

import json

import pytest

from prebuttal.revdiff import (
    WORD_OVERLAP,
    PlanMatch,
    compute_diff,
    render_diff,
    render_diff_markdown,
)
from prebuttal.runs import RunRecord

A_JSON = {
    "aggregate": {"mean": 4.0, "std": 1.0, "rating_scale": 10},
    "meta": {
        "estimated_rating": 4,
        "action_plan": [
            {"priority": "must", "issue": "No Perceiver baseline in Table 1."},
            {"priority": "should", "issue": "Single seed only."},
        ],
    },
    "reviewers": [
        {"reviewer_id": "R1", "persona": "methodologist", "rating": 4,
         "fields": {"weaknesses": ["No Perceiver baseline in Table 1.", "Single seed only."]}},
        {"reviewer_id": "R2", "persona": "theorist", "rating": 5, "fields": {"weaknesses": []}},
    ],
}  # fmt: skip
B_JSON = {
    "aggregate": {"mean": 5.0, "std": 0.5, "rating_scale": 10},
    "meta": {
        "estimated_rating": 5,
        "action_plan": [{"priority": "must", "issue": "Latent-array models are not compared."}],
    },
    "reviewers": [
        {"reviewer_id": "R1", "persona": "methodologist", "rating": 5,
         "fields": {"weaknesses": ["Latent-array models are not compared.",
                                   "Single seed only, no variance."]}},
        {"reviewer_id": "R2", "persona": "theorist", "rating": 6, "fields": {"weaknesses": []}},
    ],
}  # fmt: skip


def _rec(tmp_path, name: str, data: dict) -> RunRecord:
    d = tmp_path / name
    d.mkdir()
    (d / "report.json").write_text(json.dumps(data), encoding="utf-8")
    return RunRecord(
        id=name, ts="2026-11-08T10:00:00", paper_title="P", source="p.pdf", venue="iclr",
        seed=42, mean=None, std=None, n=2, dir=str(d), scale=10,
    )  # fmt: skip


@pytest.fixture
def runs(tmp_path):
    return _rec(tmp_path, "a", A_JSON), _rec(tmp_path, "b", B_JSON)


def test_compute_diff_is_plain_data(runs):
    d = compute_diff(*runs)
    assert d.mean == (4.0, 5.0) and d.ac_estimate == (4, 5) and d.same_scale
    assert [(r.reviewer, r.a, r.b) for r in d.ratings] == [
        ("R1 · methodologist", 4, 5),
        ("R2 · theorist", 5, 6),
    ]
    (mv,) = d.weaknesses  # theorist has none in either run
    assert mv.reviewer == "R1 · methodologist"
    assert [w.text for w in mv.persists] == ["Single seed only."]
    assert [w.text for w in mv.new] == ["Latent-array models are not compared."]
    assert mv.rounds == (1, 1) and "rounds)" not in render_diff_markdown(d)
    assert d.weaknesses_by_words
    assert d.plan is not None and d.plan.by_words and not d.plan.fell_back
    assert [it.still_raised for it in d.plan.items] == [False, True]
    assert d.plan.new_in_b == ["Latent-array models are not compared."]
    assert d.plan.not_redetected == 1
    assert render_diff_markdown(d) == render_diff(*runs)


class _Matcher:
    label = "fake / m1"

    def __init__(self, weak=None, plan=None):
        self._weak, self._plan = weak, plan

    def weaknesses(self, groups):
        return None if self._weak is None else [self._weak] * len(groups)

    def plan(self, a_plan, b_plan, b_weak):
        return self._plan


def test_a_matcher_answers_both_questions(runs):
    m = _Matcher(weak=[0, 1], plan=PlanMatch(still={0, 1}, new_b=[], label="fake / m1"))
    d = compute_diff(*runs, matcher=m)
    (mv,) = d.weaknesses
    assert mv.gone == []
    assert [w.text for w in mv.persists] == A_JSON["reviewers"][0]["fields"]["weaknesses"]
    assert not d.weaknesses_by_words and not d.plan.by_words
    text = render_diff_markdown(d)
    assert "## Weakness movement (matched by fake / m1)" in text
    assert "## Revision plan of A, checked against B (matched by fake / m1)" in text
    assert "Matching is by wording" not in text


def test_unusable_weakness_answers_fall_back_to_words(runs):
    d = compute_diff(*runs, matcher=_Matcher(weak=None))
    assert d.weaknesses_by_words
    assert d.weaknesses == compute_diff(*runs).weaknesses


def test_failed_plan_answer_falls_back_and_says_so(runs):
    d = compute_diff(*runs, matcher=_Matcher(plan=None))
    assert d.plan.by_words and d.plan.fell_back and d.plan.matched_by == WORD_OVERLAP.label
    assert "model matching failed — fell back to word overlap" in render_diff_markdown(d)


def test_a_reviewer_with_no_weakness_on_one_side_needs_no_matcher(runs, tmp_path):
    class _Never(_Matcher):
        def weaknesses(self, groups):
            raise AssertionError("not asked: nothing to pair")

    b = json.loads(json.dumps(B_JSON))
    b["reviewers"][0]["fields"]["weaknesses"] = []
    d = compute_diff(runs[0], _rec(tmp_path, "b2", b), matcher=_Never())
    (mv,) = d.weaknesses
    assert len(mv.gone) == 2 and not d.weaknesses_by_words


def test_rounds_of_one_reviewer_are_grouped(tmp_path):
    """With `repeats`: a reviewer's rating is the mean of its rounds, and each
    weakness counts the rounds that raised it."""

    def review(rid, k, rating, weak):
        return {"reviewer_id": rid, "repeat": k, "persona": "methodologist",
                "rating": rating, "fields": {"weaknesses": weak}}  # fmt: skip

    a = {
        "aggregate": {"mean": 4.5, "rating_scale": 10, "round_means": [4, 5]},
        "reviewers": [review("R1", 0, 4, ["Single seed only.", "No Perceiver baseline."]),
                      review("R1", 1, 5, ["Only a single seed."])],
    }  # fmt: skip
    b = {
        "aggregate": {"mean": 6, "rating_scale": 10, "round_means": [6, 6]},
        "reviewers": [review("R1", 0, 6, ["Single seed only, no variance."]),
                      review("R1", 1, 6, ["Writing is unclear."])],
    }  # fmt: skip
    d = compute_diff(_rec(tmp_path, "a", a), _rec(tmp_path, "b", b))
    (rc,) = d.ratings
    assert (rc.reviewer, rc.a, rc.b, rc.rounds) == ("R1 · methodologist", 4.5, 6, (2, 2))
    (mv,) = d.weaknesses
    assert mv.rounds == (2, 2)
    assert [(w.text, w.seen_a, w.seen_b) for w in mv.persists] == [("Single seed only.", 2, 1)]
    assert [(w.text, w.seen_a) for w in mv.gone] == [("No Perceiver baseline.", 1)]
    assert [(w.text, w.seen_b) for w in mv.new] == [("Writing is unclear.", 1)]
    text = render_diff_markdown(d)
    assert "- R1 · methodologist: 4.5 → 6  (Δ +1.5)  (mean of 2 → 2 rounds)" in text
    assert "- persists: Single seed only. (A: 2 of 2 rounds) (B: 1 of 2 rounds)" in text
    assert "raised in 1 round only" in text


def test_a_failed_round_is_not_a_round_that_raised_nothing(tmp_path):
    def review(k, weak, ok=True):
        return {"reviewer_id": "R1", "repeat": k, "persona": "methodologist",
                "parse_ok": ok, "rating": 5 if ok else None,
                "fields": {"weaknesses": weak} if ok else {}}  # fmt: skip

    a = {"reviewers": [review(0, ["Single seed only."]), review(1, [], ok=False)]}
    b = {"reviewers": [review(0, ["Single seed only."]), review(1, ["Single seed only."])]}
    d = compute_diff(_rec(tmp_path, "a", a), _rec(tmp_path, "b", b))
    (rc,) = d.ratings
    assert rc.rounds == (1, 2)
    (mv,) = d.weaknesses
    assert mv.rounds == (1, 2) and [(w.seen_a, w.seen_b) for w in mv.persists] == [(1, 2)]
    assert "raised in 1 round only" not in render_diff_markdown(d)
    # a reviewer that failed every round of B: its weaknesses are not "gone"
    gone = {"reviewers": [review(0, [], ok=False)]}
    d = compute_diff(_rec(tmp_path, "a2", a), _rec(tmp_path, "b2", gone))
    assert d.weaknesses == [] and d.ratings[0].b is None
    assert "rounds)" not in render_diff_markdown(d)


def test_a_reviewer_that_failed_throughout_still_has_a_row(tmp_path):
    down = {"reviewer_id": "R2", "persona": "theorist", "parse_ok": False, "fields": {}}
    a = {"reviewers": [*A_JSON["reviewers"][:1], down]}
    b = {"reviewers": [*B_JSON["reviewers"][:1], down]}
    d = compute_diff(_rec(tmp_path, "a", a), _rec(tmp_path, "b", b))
    assert [(r.reviewer, r.a, r.b) for r in d.ratings][-1] == ("R2 · theorist", None, None)


def test_diff_says_when_bs_area_chair_wrote_no_plan(tmp_path):
    b = json.loads(json.dumps(B_JSON))
    b["meta"] = {"parse_ok": False, "action_plan": []}
    d = compute_diff(_rec(tmp_path, "a", A_JSON), _rec(tmp_path, "b", b))
    assert not d.plan.b_ac_plan
    assert "B's area chair wrote no revision plan" in render_diff_markdown(d)
    assert "wrote no revision plan" not in render_diff_markdown(
        compute_diff(_rec(tmp_path, "a2", A_JSON), _rec(tmp_path, "b2", B_JSON))
    )


def test_check_items_alone_are_not_an_ac_plan():
    from prebuttal.revdiff import ac_wrote_plan

    check_only = {"meta": {"action_plan": [
        {"priority": "must", "issue": "No checklist.", "raised_by": ["check"]}]}}  # fmt: skip
    assert not ac_wrote_plan(check_only)
    ac_item = {"priority": "must", "issue": "x", "raised_by": ["R1"]}
    check_only["meta"]["action_plan"].append(ac_item)
    assert ac_wrote_plan(check_only)
