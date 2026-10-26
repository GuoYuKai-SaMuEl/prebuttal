"""The area chair's revision plan: parsing, rendering, CLI, diff."""

from __future__ import annotations

import json

from conftest import make_report

from prebuttal import cli
from prebuttal.orchestrator import build_ac_system, coerce_action_plan
from prebuttal.report import dumps_json, render_markdown, report_from_dict
from prebuttal.runs import load_history, render_diff
from prebuttal.share import render_share_html
from prebuttal.venues import get_venue


def test_coerce_normalises_orders_and_drops_junk():
    raw = [
        {"priority": "low", "issue": "Typos in Section 2", "action": "Proofread"},
        {"priority": "Critical!", "issue": "Proof of Lemma 3 has a gap", "action": "Fix it",
         "raised_by": "r2, R9 / R3", "effort": "L"},
        {"priority": "must", "action": "no issue given -> dropped"},
        "not an object",
        {"issue": "Unclear notation", "raised_by": ["R1", "R1"], "effort": "tiny"},
    ]  # fmt: skip
    items = coerce_action_plan(raw, ["R1", "R2", "R3"])
    assert [it.priority for it in items] == ["must", "should", "could"]
    must = items[0]
    assert must.raised_by == ["R2", "R3"]  # unknown R9 dropped, case-folded
    assert must.effort == "large"
    assert items[1].issue == "Unclear notation" and items[1].raised_by == ["R1"]
    assert items[1].effort == ""  # unknown effort label
    assert coerce_action_plan("nope", ["R1"]) == []
    many = [{"issue": f"issue {i}"} for i in range(30)]
    assert len(coerce_action_plan(many, ["R1"])) == 10


def test_ac_is_asked_for_a_plan():
    assert '"action_plan"' in build_ac_system(get_venue("iclr"))


def test_plan_in_markdown_html_and_json(latex_project):
    report, venue = make_report(latex_project)
    plan = report.meta.action_plan
    assert [it.priority for it in plan] == ["must", "should"]
    md = render_markdown(report, venue)
    assert "## Revision plan" in md
    assert md.index("## Revision plan") < md.index("## Meta-review")
    assert "- [ ] **must** — Baseline set is thin" in md
    assert "(R2, R3 · effort: medium)" in md
    html = render_share_html(report, venue, "https://x")
    assert "Revision plan" in html and 'class="prio prio-must"' in html
    data = json.loads(dumps_json(report, venue))
    assert data["meta"]["action_plan"][0]["raised_by"] == ["R2", "R3"]
    again = report_from_dict(data).meta.action_plan
    assert again == plan


def test_cli_run_prints_fix_first_and_plan_command(
    tmp_path, monkeypatch, latex_project, fake_statuses, fake_config, capsys
):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["run", str(latex_project), "--config", str(fake_config)]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Fix first: [must] Baseline set is thin" in out
    assert "prebuttal plan" in out

    assert cli.main(["plan"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("# Revision plan — ")
    assert "- [ ] **must** — Baseline set is thin" in out

    assert cli.main(["plan", "--json"]) == cli.EXIT_OK
    items = json.loads(capsys.readouterr().out)
    assert items[0]["priority"] == "must" and items[1]["effort"] == "small"

    # a run archived before 0.3 has no plan
    rec = load_history()[0]
    p = rec.dir_path / "report.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    del data["meta"]["action_plan"]
    p.write_text(json.dumps(data), encoding="utf-8")
    assert cli.main(["plan"]) == cli.EXIT_USAGE
    assert "has no revision plan" in capsys.readouterr().err


def test_diff_checks_plan_items_against_the_next_run(
    tmp_path, monkeypatch, latex_project, fake_statuses, fake_config, capsys
):
    monkeypatch.chdir(tmp_path)
    for _ in range(2):
        assert cli.main(["run", str(latex_project), "--config", str(fake_config)]) == 0
    b, a = load_history()[:2]
    # revision B fixed the baselines: no reviewer or plan item raises them any more
    p = b.dir_path / "report.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    for r in data["reviewers"]:
        r["fields"]["weaknesses"] = ["Writing is dense in Section 3."]
    data["meta"]["action_plan"] = [
        data["meta"]["action_plan"][1],
        {"priority": "could", "issue": "Figure 2 axis labels are unreadable.", "action": "x"},
    ]
    p.write_text(json.dumps(data), encoding="utf-8")

    text = render_diff(a, b)
    assert "## Revision plan of A, checked against B" in text
    assert "- not re-detected: [must] Baseline set is thin" in text
    assert "- still raised: [should] No variance across seeds" in text
    assert "- new in B: Figure 2 axis labels" in text
    assert "1 of 2 plan items were not re-detected in B." in text
    assert "Matching is by wording" in text  # a new item appeared: warn about rewording
