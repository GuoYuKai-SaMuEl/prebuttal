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


def _failed_ac(data: dict) -> dict:
    return {**data, "meta": {"parse_ok": False, "action_plan": []}}


def test_a_run_without_an_ac_plan_is_stepped_over(tmp_path):
    r1 = _rec(tmp_path, 1, _plan(SEED, BASE))
    r2 = _rec(tmp_path, 2, _failed_ac(_plan()))  # cut short / AC failed
    r3 = _rec(tmp_path, 3, _plan(SEED, WRITE))
    plan = project_plan([r3, r2, r1])
    assert plan is not None and plan.previous is r1
    assert [it.since for it in plan.items] == [1, 3]
    assert plan.dropped == [("must", BASE)]  # not every item of #1
    # the latest run has no plan: the last one that has is shown
    r4 = _rec(tmp_path, 4, _failed_ac(_plan()))
    plan = project_plan([r4, r3, r2, r1])
    assert plan is not None and plan.run is r3


def test_a_damaged_track_file_is_computed_again(tmp_path):
    r1 = _rec(tmp_path, 1, _plan(BASE))
    r2 = _rec(tmp_path, 2, _plan(BASE, WRITE))
    t = track_pair(r1, r2, _Matcher())
    assert t is not None
    saved = json.loads((r2.dir_path / TRACK_FILE).read_text(encoding="utf-8"))
    (r2.dir_path / TRACK_FILE).write_text(json.dumps({**saved, "links": None}), encoding="utf-8")
    plan = project_plan([r2, r1])  # no AttributeError: by wording instead
    assert plan is not None and plan.by_words


def test_no_plan_line_when_the_ac_wrote_no_plan(
    latex_project, fake_statuses, fake_config, monkeypatch, capsys
):
    from prebuttal import orchestrator
    from prebuttal.models import MetaReview

    monkeypatch.chdir(fake_config.parent)
    assert cli.main(["run", str(latex_project), "--config", str(fake_config)]) == 0
    monkeypatch.setattr(orchestrator, "run_meta",
                        lambda *a, **k: MetaReview("fake", "m", 0.0, error="down"))  # fmt: skip
    capsys.readouterr()
    cli.main(["run", str(latex_project), "--config", str(fake_config)])
    out = capsys.readouterr()
    assert "Plan:" not in out.out and "following the revision plan" not in out.err


def test_diff_shows_the_runs_plan_check_without_asking_again(
    latex_project, fake_statuses, fake_config, model_diff, monkeypatch, capsys
):
    monkeypatch.chdir(fake_config.parent)
    for _ in range(2):
        assert cli.main(["run", str(latex_project), "--config", str(fake_config)]) == 0
    a = load_history()[1]
    n = len(json.loads((a.dir_path / "report.json").read_text(encoding="utf-8"))["meta"]
            ["action_plan"])  # fmt: skip
    answer = {"a": [{"id": f"A{i}", "still_raised": True, "matched_by": [f"B{i}"]}
                    for i in range(1, n + 1)], "new_in_b": []}  # fmt: skip
    asked: list[str] = []

    class _Canned(PersonaFakeProvider):
        def _complete(self, **kw):
            asked.append(kw["system"])
            return json.dumps(answer), Usage()

    register_backend("matcher", lambda m, cfg, t: _Canned(backend="matcher"))
    monkeypatch.setenv("PREBUTTAL_BACKEND", "matcher")
    assert cli.main(["diff"]) == cli.EXIT_OK  # asks, and keeps the answer
    plan_calls = sum("A item" in s for s in asked)  # the plan check's prompt
    asked.clear()
    capsys.readouterr()
    assert cli.main(["diff"]) == cli.EXIT_OK
    assert sum("A item" in s for s in asked) == 0 < plan_calls  # the kept check
    assert "matcher" in capsys.readouterr().out


def test_a_merged_item_goes_back_to_the_oldest_of_its_parts(tmp_path):
    from prebuttal.plantrack import PlanTrack, save_track
    from prebuttal.revdiff import plan_items

    r1 = _rec(tmp_path, 1, _plan(BASE))
    r2 = _rec(tmp_path, 2, _plan(WRITE, BASE))  # P1 new in #2, P2 from #1
    r3 = _rec(tmp_path, 3, _plan("Baselines and writing are both weak."))
    from prebuttal.plantrack import _load_run_json, _plans_key

    def keep(a, b, links):
        da, db = _load_run_json(a), _load_run_json(b)
        ids = lambda d: [it["id"] for it in plan_items(d)]  # noqa: E731
        save_track(b, PlanTrack(a.id, b.id, _plans_key(da, db), "m", False, ids(da), ids(db),
                                list(links), links, []))  # fmt: skip

    keep(r1, r2, {"P1": ["P2"]})
    keep(r2, r3, {"P1": ["P1"], "P2": ["P1"]})  # both of #2 merged into #3's P1
    plan = project_plan([r3, r2, r1])
    assert plan is not None and [it.since for it in plan.items] == [1]


def test_a_kept_match_naming_ids_the_plans_lack_is_not_used(tmp_path):
    r1 = _rec(tmp_path, 1, _plan(SEED, BASE))
    r2 = _rec(tmp_path, 2, _plan(SEED))
    track_pair(r1, r2, _Matcher())
    saved = json.loads((r2.dir_path / TRACK_FILE).read_text(encoding="utf-8"))
    bad = {**saved, "still": ["P99"]}
    (r2.dir_path / TRACK_FILE).write_text(json.dumps(bad), encoding="utf-8")
    plan = project_plan([r2, r1])
    assert plan is not None and plan.by_words  # computed again, not the edited file
    assert plan.dropped == [("must", BASE)]


def test_a_finished_retry_replaces_the_run_it_completes(tmp_path):
    from dataclasses import replace

    r1 = _rec(tmp_path, 1, _plan(SEED, BASE))
    r2 = _rec(tmp_path, 2, _plan(SEED))  # a reviewer was down
    r3 = replace(_rec(tmp_path, 3, _plan(SEED, WRITE)), retry_of=r2.id)
    plan = project_plan([r3, r2, r1])
    assert plan is not None and plan.previous is r1  # not #2: the same paper
    # runs archived before retry_of: the note says it
    r3n = replace(_rec(tmp_path, 4, _plan(SEED, WRITE)), note="retry of p#2")
    r2.project = r3n.project = r1.project
    plan = project_plan([r3n, r2, r1])
    assert plan is not None and plan.previous is r1
