"""`prebuttal diff` internals: the RevisionDiff data and the Matcher interface."""

from __future__ import annotations

import json

import pytest

from prebuttal.diffmatch import ModelMatcher
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
        {"persona": "methodologist", "rating": 4,
         "fields": {"weaknesses": ["No Perceiver baseline in Table 1.", "Single seed only."]}},
        {"persona": "theorist", "rating": 5, "fields": {"weaknesses": []}},
    ],
}  # fmt: skip
B_JSON = {
    "aggregate": {"mean": 5.0, "std": 0.5, "rating_scale": 10},
    "meta": {
        "estimated_rating": 5,
        "action_plan": [{"priority": "must", "issue": "Latent-array models are not compared."}],
    },
    "reviewers": [
        {"persona": "methodologist", "rating": 5,
         "fields": {"weaknesses": ["Latent-array models are not compared.",
                                   "Single seed only, no variance."]}},
        {"persona": "theorist", "rating": 6, "fields": {"weaknesses": []}},
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
        ("methodologist", 4, 5),
        ("theorist", 5, 6),
    ]
    (mv,) = d.weaknesses  # theorist has none in either run
    assert mv.reviewer == "methodologist"
    assert mv.persists == ["Single seed only."] and mv.new == [
        "Latent-array models are not compared."
    ]
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

    def weaknesses(self, old, new):
        return self._weak

    def plan(self, a_plan, b_plan, b_weak):
        return self._plan


def test_a_matcher_answers_both_questions(runs):
    m = _Matcher(weak=[0, 1], plan=PlanMatch(still={0, 1}, new_b=[], label="fake / m1"))
    d = compute_diff(*runs, matcher=m)
    (mv,) = d.weaknesses
    assert mv.gone == [] and mv.persists == A_JSON["reviewers"][0]["fields"]["weaknesses"]
    assert not d.weaknesses_by_words and not d.plan.by_words
    text = render_diff_markdown(d)
    assert "## Weakness movement (matched by fake / m1)" in text
    assert "## Revision plan of A, checked against B (matched by fake / m1)" in text
    assert "Matching is by wording" not in text


def test_out_of_range_plan_answers_cannot_crash_the_diff(runs):
    m = _Matcher(plan=PlanMatch(still={0, 99}, new_b=[0, 0, 7, -1, True], label="fake / m1"))
    d = compute_diff(*runs, matcher=m)
    assert d.plan.new_in_b == ["Latent-array models are not compared."]  # deduped, in range
    render_diff_markdown(d)  # and it renders


@pytest.mark.parametrize("weak", [None, [0], [0, 0], [0, 5], [-1, None]])
def test_unusable_weakness_answers_fall_back_to_words(runs, weak):
    d = compute_diff(*runs, matcher=_Matcher(weak=weak))
    assert d.weaknesses_by_words
    assert d.weaknesses == compute_diff(*runs).weaknesses


def test_failed_plan_answer_falls_back_and_says_so(runs):
    d = compute_diff(*runs, matcher=_Matcher(plan=None))
    assert d.plan.by_words and d.plan.fell_back and d.plan.matched_by == WORD_OVERLAP.label
    assert "(model matching failed — fell back to word overlap)" in render_diff_markdown(d)


def test_model_matcher_leaves_weaknesses_to_word_overlap(runs):
    class _P:
        backend, model = "canned", "m1"

    m = ModelMatcher(_P())  # type: ignore[arg-type]
    assert m.label == "canned / m1" and m.weaknesses(["x"], ["x"]) is None
