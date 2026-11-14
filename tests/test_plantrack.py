"""Following the revision plan across runs (plantrack) and on the dashboard."""

from __future__ import annotations

import json

from conftest import PersonaFakeProvider

from prebuttal import cli
from prebuttal.dashboard import render_dashboard
from prebuttal.diffmatch import match_plan
from prebuttal.models import Usage
from prebuttal.plantrack import TRACK_FILE, project_plan, track_pair
from prebuttal.providers import register_backend
from prebuttal.providers.base import BaseProvider
from prebuttal.revdiff import PlanMatch
from prebuttal.runs import RunRecord, load_history, project_summaries


def _plan(*issues: str) -> dict:
    return {
        "aggregate": {"mean": 5.0, "rating_scale": 10},
        "meta": {"action_plan": [
            {"id": f"P{i}", "priority": "must", "issue": t} for i, t in enumerate(issues, 1)
        ]},
        "reviewers": [],
    }  # fmt: skip


def _rec(tmp_path, n: int, data: dict, mean: float = 5.0) -> RunRecord:
    d = tmp_path / f"run{n}"
    d.mkdir()
    (d / "report.json").write_text(json.dumps(data), encoding="utf-8")
    return RunRecord(
        id=f"2026111{n}-000000-aaaa-p", ts="", paper_title="P", source="p.pdf", venue="iclr",
        seed=42, mean=mean, std=0.5, n=3, dir=str(d), project="p", run_no=n, scale=10,
    )  # fmt: skip


SEED = "Results come from a single random seed."
BASE = "No comparison with the Perceiver baseline."
WRITE = "The method section is hard to follow."


def test_history_of_the_latest_plan_by_wording(tmp_path):
    r1 = _rec(tmp_path, 1, _plan(SEED, BASE))
    r2 = _rec(tmp_path, 2, _plan(SEED, WRITE))
    r3 = _rec(tmp_path, 3, _plan(SEED, WRITE, "Ablations are missing for the router."))
    plan = project_plan([r3, r2, r1])
    assert plan is not None and plan.by_words and plan.previous is r2
    assert [(it.id, it.since) for it in plan.items] == [("P1", 1), ("P2", 2), ("P3", 3)]
    assert plan.dropped == []  # all of #2 is still raised in #3
    plan2 = project_plan([r2, r1])
    assert plan2 is not None and plan2.dropped == [("must", BASE)]
    assert not (r3.dir_path / TRACK_FILE).exists()  # word overlap is never saved


class _Matcher:
    """A model-like matcher that links by position and counts its calls."""

    label = "fake / m1"

    def __init__(self):
        self.calls = 0

    def weaknesses(self, groups):
        return None

    def plan(self, a_plan, b_plan, b_weak):
        self.calls += 1
        n = min(len(a_plan), len(b_plan))
        return PlanMatch(set(range(n)), list(range(n, len(b_plan))), self.label,
                         {i: [i] for i in range(n)})  # fmt: skip


def test_a_model_track_is_kept_and_reused(tmp_path):
    r1 = _rec(tmp_path, 1, _plan(BASE))
    r2 = _rec(tmp_path, 2, _plan("Latent-array models are not compared.", WRITE))
    m = _Matcher()
    t = track_pair(r1, r2, m)
    assert t is not None and not t.by_words and t.links == {"P1": ["P1"]} and t.new_in_b == ["P2"]
    assert (r2.dir_path / TRACK_FILE).is_file()
    assert track_pair(r1, r2, m) == t and m.calls == 1  # the saved one, no second call
    plan = project_plan([r2, r1])  # the dashboard: no matcher, the saved match
    assert plan is not None and not plan.by_words
    assert [it.since for it in plan.items] == [1, 2]  # reworded, still followed by meaning
    # a changed plan is matched again
    (r2.dir_path / "report.json").write_text(json.dumps(_plan(WRITE)), encoding="utf-8")
    track_pair(r1, r2, m)
    assert m.calls == 2


def test_match_plan_links_by_plan_items_only():
    class _Canned(BaseProvider):
        def __init__(self, answer):
            super().__init__("canned", "m1")
            self.answer = answer

        def _complete(self, **kw):
            return json.dumps(self.answer), Usage()

    good = {"a": [{"id": "A1", "still_raised": True, "matched_by": ["W1", "B2"]},
                  {"id": "A2", "still_raised": False, "matched_by": []}],
            "new_in_b": ["B1"]}  # fmt: skip
    m = match_plan(_Canned(good), ["x", "y"], ["p", "q"], ["w"])
    assert m is not None and m.links == {0: [1]}
    bad = {"a": [{"id": "A1", "still_raised": True, "matched_by": ["B9"]},
                 {"id": "A2", "still_raised": False}], "new_in_b": []}  # fmt: skip
    assert match_plan(_Canned(bad), ["x", "y"], ["p", "q"], ["w"]) is None


def test_dashboard_shows_where_each_item_came_from(tmp_path):
    r1 = _rec(tmp_path, 1, _plan(SEED, BASE), mean=5.0)
    r2 = _rec(tmp_path, 2, _plan(SEED, WRITE), mean=5.33)
    from prebuttal.runs import ProjectSummary

    page = render_dashboard([ProjectSummary(key="p", title="P", runs=[r2, r1])], base=tmp_path)
    assert "Revision plan of #2 · 2 items · 1 from earlier runs" in page
    assert "since #1" in page and "new in #2" in page
    assert "No longer raised in #2" in page and "Perceiver" in page
    assert "Matched by wording" in page
    assert "within noise" in page  # +0.33 is not a direction


def test_a_second_run_follows_the_plan(
    latex_project, fake_statuses, fake_config, monkeypatch, capsys
):
    monkeypatch.chdir(fake_config.parent)
    for _ in range(2):
        assert cli.main(["run", str(latex_project), "--config", str(fake_config)]) == 0
    out = capsys.readouterr()
    # the fake AC answers with a review, not a match: word overlap, said so
    assert "following the revision plan from" in out.err
    assert "no longer raised" in out.out and "(by wording)" in out.out
    latest = load_history()[0]
    assert not (latest.dir_path / TRACK_FILE).exists()
    assert project_plan(project_summaries()[0].runs) is not None


def test_diff_of_consecutive_runs_keeps_its_model_match(
    latex_project, fake_statuses, fake_config, model_diff, monkeypatch, capsys
):
    monkeypatch.chdir(fake_config.parent)
    for _ in range(2):
        assert cli.main(["run", str(latex_project), "--config", str(fake_config)]) == 0
    b, a = load_history()[:2]
    n = len(json.loads((a.dir_path / "report.json").read_text(encoding="utf-8"))["meta"]
            ["action_plan"])  # fmt: skip
    answer = {"a": [{"id": f"A{i}", "still_raised": True, "matched_by": [f"B{i}"]}
                    for i in range(1, n + 1)], "new_in_b": []}  # fmt: skip

    class _Canned(PersonaFakeProvider):
        def _complete(self, **kw):
            return json.dumps(answer), Usage()

    register_backend("matcher", lambda m, cfg, t: _Canned(backend="matcher"))
    monkeypatch.setenv("PREBUTTAL_BACKEND", "matcher")
    assert cli.main(["diff"]) == cli.EXIT_OK
    saved = json.loads((b.dir_path / TRACK_FILE).read_text(encoding="utf-8"))
    assert saved["a"] == a.id and not saved["by_words"] and len(saved["still"]) == n
    # not consecutive (B before A): nothing is kept
    (b.dir_path / TRACK_FILE).unlink()
    assert cli.main(["diff", b.label, a.label]) == cli.EXIT_OK
    assert not (a.dir_path / TRACK_FILE).exists() and not (b.dir_path / TRACK_FILE).exists()
