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
    assert "prebuttal show --plan" in out

    for argv in (["show", "--plan"], ["plan"]):  # `plan` stays until 0.6
        assert cli.main(argv) == cli.EXIT_OK
        out = capsys.readouterr().out
        assert out.startswith("# Revision plan — ")
        assert "- [ ] **must** — Baseline set is thin" in out

    for argv in (["show", "--plan", "--json"], ["plan", "--json"]):
        assert cli.main(argv) == cli.EXIT_OK
        items = json.loads(capsys.readouterr().out)
        assert items[0]["priority"] == "must" and items[1]["effort"] == "small"

    assert cli.main(["show", "--plan", "--open"]) == cli.EXIT_USAGE
    assert "--plan prints the plan" in capsys.readouterr().err

    # a run archived before 0.3 has no plan
    rec = load_history()[0]
    p = rec.dir_path / "report.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    del data["meta"]["action_plan"]
    p.write_text(json.dumps(data), encoding="utf-8")
    assert cli.main(["show", "--plan"]) == cli.EXIT_USAGE
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


# -- `prebuttal check`'s findings in the plan and in front of the AC ----------

_CHECK_NOTES = [
    'Pre-flight check (error): no "NeurIPS Paper Checklist" section — the venue requires one',
    "Pre-flight check (warning): an acknowledgements section is visible (page 9)",
    "Pre-flight check skipped: cannot open PDF",  # not a finding
    "hidden text found on page 2",  # another kind of note
]


def test_preflight_findings_round_trip_through_the_notes():
    from prebuttal.check import ERROR, WARNING, CheckResult, preflight_findings, preflight_warnings

    result = CheckResult(source="p.pdf", kind="pdf")
    result.add(WARNING, "anonymity", "an acknowledgements section is visible (page 9)")
    result.add(ERROR, "format", 'no "Impact Statement" section — the venue requires one')
    assert preflight_findings(preflight_warnings(result)) == [
        ("error", 'no "Impact Statement" section — the venue requires one'),
        ("warning", "an acknowledgements section is visible (page 9)"),
    ]
    assert len(preflight_findings(_CHECK_NOTES)) == 2


def test_check_findings_lead_the_plan_and_reach_the_ac(latex_project):
    from conftest import PersonaFakeProvider

    from prebuttal.config import load_config
    from prebuttal.ingestion import ingest
    from prebuttal.orchestrator import CHECK, run_report

    cfg = load_config(None)
    paper = ingest(str(latex_project))
    paper.warnings += _CHECK_NOTES
    ac_calls: list = []
    report = run_report(
        paper,
        cfg,
        get_venue("neurips"),
        {r.id: PersonaFakeProvider() for r in cfg.reviewers},
        PersonaFakeProvider(calls=ac_calls),
        log=lambda m: None,
    )
    plan = report.meta.action_plan
    assert [(it.priority, it.raised_by) for it in plan[:1]] == [("must", [CHECK])]
    assert plan[0].issue.startswith('no "NeurIPS Paper Checklist" section')
    assert plan[1].raised_by != [CHECK]  # the AC's own must comes after
    shoulds = [it for it in plan if it.priority == "should"]
    assert shoulds[0].raised_by == [CHECK]  # ahead of the AC's should
    markdown = render_markdown(report, get_venue("neurips"))
    assert '- [ ] **must** — no "NeurIPS Paper Checklist"' in markdown

    user = ac_calls[0]["user"]
    facts = user.index("A deterministic pre-flight check")
    assert facts > user.index("</submission>")  # outside the untrusted paper text
    assert '- [error] no "NeurIPS Paper Checklist" section' in user
    assert "- [warning] an acknowledgements section is visible" in user
    assert "skipped" not in user[facts:]


def test_ac_prompt_unchanged_without_findings(latex_project):
    from prebuttal.orchestrator import build_ac_user

    assert "pre-flight" not in build_ac_user("pack", [], get_venue("iclr"))


def test_check_items_survive_a_failed_ac_and_a_retry(latex_project):
    from conftest import PersonaFakeProvider

    from prebuttal.config import load_config
    from prebuttal.ingestion import ingest
    from prebuttal.orchestrator import CHECK, review_then_meta, run_report
    from prebuttal.providers.base import ProviderError

    class DownAC(PersonaFakeProvider):
        def _complete(self, **kw):
            raise ProviderError("HTTP 429")

    cfg = load_config(None)
    paper = ingest(str(latex_project))
    paper.warnings += _CHECK_NOTES
    providers = {r.id: PersonaFakeProvider() for r in cfg.reviewers}
    venue = get_venue("neurips")
    report = run_report(paper, cfg, venue, providers, DownAC(), log=lambda m: None)
    assert report.meta.error and [it.raised_by for it in report.meta.action_plan] == [
        [CHECK],
        [CHECK],
    ]

    # `retry` rebuilds the paper from report.json: the notes carry the findings
    old = report_from_dict(json.loads(dumps_json(report, venue)))
    again = review_then_meta(
        old.paper, cfg, venue, report.pack, providers, PersonaFakeProvider(),
        lambda m: None, keep=list(old.reviews),
    )  # fmt: skip
    assert [it.raised_by for it in again.meta.action_plan].count([CHECK]) == 2


def test_diff_shows_a_fixed_check_item_as_gone(
    tmp_path, monkeypatch, latex_project, fake_statuses, fake_config
):
    monkeypatch.chdir(tmp_path)
    for _ in range(2):
        assert cli.main(["run", str(latex_project), "--config", str(fake_config)]) == 0
    b, a = load_history()[:2]
    p = a.dir_path / "report.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["meta"]["action_plan"].insert(
        0,
        {
            "priority": "must",
            "issue": 'no "NeurIPS Paper Checklist" section — the venue requires one',
            "action": "Fix before submitting: a desk-reject risk",
            "raised_by": ["check"],
        },
    )
    p.write_text(json.dumps(data), encoding="utf-8")
    text = render_diff(a, b)
    assert '- not re-detected: [must] no "NeurIPS Paper Checklist" section' in text
