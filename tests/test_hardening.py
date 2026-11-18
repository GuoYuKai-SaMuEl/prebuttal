"""Regressions from the 0.7.0 code review: archive integrity, retry inputs,
cross-venue scores, LaTeX sources, malformed JSON and PDFs."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import PersonaFakeProvider, make_pdf_bytes, make_report

from prebuttal import cli
from prebuttal.config import ConfigError, load_config
from prebuttal.models import sha256_text
from prebuttal.report import dumps_json
from prebuttal.runs import (
    comparable,
    history_path,
    load_history,
    project_summaries,
    render_projects_table,
    save_run,
)


def _archive(latex_project, *, venue_key="iclr", note="", rating_shift=0):
    report, venue = make_report(latex_project, venue_key=venue_key, rating_shift=rating_shift)
    return save_run(
        report,
        venue,
        load_config(None),
        md="# r",
        json_str=dumps_json(report, venue),
        html=None,
        note=note,
    )


# ------------------------------------------------------------------ run history


def test_a_line_separator_in_a_note_keeps_the_run_in_the_history(latex_project):
    rec = _archive(latex_project, note="before\u2028after\u0085end")
    assert [r.id for r in load_history()] == [rec.id]
    assert load_history()[0].note == "before\u2028after\u0085end"


def test_scores_of_two_venues_on_one_scale_are_not_compared(latex_project):
    rec = _archive(latex_project)
    icml = replace(rec, venue="icml", id=rec.id + "x")
    assert rec.scale == 10 and comparable(rec, rec)
    assert not comparable(rec, icml)  # ICLR and ICML both rate out of 10


def test_project_trend_needs_one_venue(latex_project):
    a = _archive(latex_project)
    b = _archive(latex_project, rating_shift=1)
    records = [replace(b, venue="icml"), a]
    row = next(
        ln
        for ln in render_projects_table(project_summaries(records)).splitlines()
        if ln.startswith(a.project)
    )
    assert " → " not in row


def test_diff_across_venues_on_one_scale_shows_no_change(latex_project, offline_diff):
    from prebuttal.revdiff import compute_diff

    a = _archive(latex_project)
    b = _archive(latex_project, rating_shift=1)
    d = compute_diff(a, replace(b, venue="icml"))
    assert not d.same_scale and d.noise is None


def test_rename_onto_a_project_known_only_from_the_history_is_refused(latex_project):
    from prebuttal.projects import ProjectError, rename_project

    rec = _archive(latex_project)
    legacy = replace(rec, id=rec.id[:-1] + "z", project="legacy", run_no=1)
    with history_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(legacy.__dict__) + "\n")
    with pytest.raises(ProjectError, match="already exists"):
        rename_project(rec.project, "legacy")
    new, n = rename_project(rec.project, "fresh")
    assert (new, n) == ("fresh", 1)
    assert {r.project for r in load_history()} == {"fresh", "legacy"}


# ------------------------------------------------------------------ config


def test_reviewer_id_ac_is_reserved(tmp_path):
    p = tmp_path / "prebuttal.toml"
    p.write_text('[[reviewer]]\nid = "ac"\npersona = "senior_kind"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="reserved for the area chair"):
        load_config(p)


# ------------------------------------------------------------------ retry inputs


def test_retry_refuses_a_pack_that_changed(tmp_path):
    from prebuttal.retry import RetryError, load_pack

    (tmp_path / "pack.md").write_text("the text", encoding="utf-8")
    assert load_pack(tmp_path, sha256_text("the text")) == "the text"
    assert load_pack(tmp_path) == "the text"  # no recorded hash: as before
    with pytest.raises(RetryError, match="changed since that run"):
        load_pack(tmp_path, sha256_text("other text"))


def test_retry_refuses_incomplete_figures(tmp_path):
    from prebuttal.retry import RetryError, load_figures

    assert load_figures(tmp_path) == []  # none archived
    figs = tmp_path / "figures"
    figs.mkdir()
    (figs / "figures.json").write_text('["page 1", "page 2"]', encoding="utf-8")
    (figs / "01.png").write_bytes(b"png")
    with pytest.raises(RetryError, match="incomplete"):
        load_figures(tmp_path)
    (figs / "02.png").write_bytes(b"png")
    assert [f.label for f in load_figures(tmp_path)] == ["page 1", "page 2"]


def test_retry_refuses_an_edited_custom_form():
    from prebuttal.report import _venue_json
    from prebuttal.retry import RetryError, venue_for_retry
    from prebuttal.venues import get_venue

    assert cli.main(["venues", "new", "mylab"]) == 0
    live = get_venue("mylab")
    data = {"venue": _venue_json(live)}
    assert data["venue"]["form_sha256"] == sha256_text(live.form_text())
    assert venue_for_retry(data).key == "mylab"
    data["venue"]["form_sha256"] = sha256_text("an older form")
    with pytest.raises(RetryError, match="review form"):
        venue_for_retry(data)


# ------------------------------------------------------------------ the AC


class _EmptyAC(PersonaFakeProvider):
    """Valid JSON with the right key names and nothing in them, every time."""

    def _complete(self, **kw):
        _text, usage = super()._complete(**kw)
        return json.dumps({"meta_review": "", "action_plan": []}), usage


def test_an_empty_meta_review_is_not_marked_finished(latex_project, shared_calls):
    from prebuttal.ingestion import ingest
    from prebuttal.orchestrator import run_report
    from prebuttal.venues import get_venue

    cfg = load_config(None)
    providers = {
        r.id: PersonaFakeProvider(backend="fake", calls=shared_calls) for r in cfg.reviewers
    }
    ac = _EmptyAC(backend="fake-ac", calls=shared_calls)
    report = run_report(
        ingest(str(latex_project)), cfg, get_venue("iclr"), providers, ac, log=lambda m: None
    )
    assert not report.meta.parse_ok and report.meta.error
    assert any("not valid JSON" in c["system"] for c in shared_calls)  # one repair asked


# ------------------------------------------------------------------ LaTeX


_CITING = (
    "\\documentclass{article}\\begin{document}\\cite{onlyelsewhere}\n"
    "\\bibliography{refs}\\end{document}\n"
)


def test_a_bib_file_the_paper_does_not_load_does_not_count(tmp_path):
    from prebuttal.check import check_latex
    from prebuttal.venues import get_venue

    (tmp_path / "main.tex").write_text(_CITING, encoding="utf-8")
    (tmp_path / "refs.bib").write_text("@article{other,\n title={T}}\n", encoding="utf-8")
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "draft.bib").write_text(
        "@article{onlyelsewhere,\n title={T}}\n", encoding="utf-8"
    )
    result = check_latex(tmp_path, get_venue("neurips").rules)
    assert any("onlyelsewhere" in f.message for f in result.findings)


def test_the_main_bbl_counts_when_the_bib_is_not_shipped(tmp_path):
    from prebuttal.check import check_latex
    from prebuttal.venues import get_venue

    (tmp_path / "main.tex").write_text(_CITING, encoding="utf-8")
    (tmp_path / "main.bbl").write_text("\\bibitem{onlyelsewhere} X.\n", encoding="utf-8")
    result = check_latex(tmp_path, get_venue("neurips").rules)
    assert not any("onlyelsewhere" in f.message for f in result.findings)
    assert any("cited keys are in the bibliography" in p for p in result.passed)


def test_the_root_main_tex_wins_over_a_nested_one(tmp_path):
    from prebuttal.ingestion.latex import find_root_tex

    (tmp_path / "main.tex").write_text("\\documentclass{article}", encoding="utf-8")
    (tmp_path / "supp").mkdir()
    (tmp_path / "supp" / "main.tex").write_text("\\documentclass{article}", encoding="utf-8")
    assert find_root_tex(tmp_path) == tmp_path / "main.tex"


# ------------------------------------------------------------------ PDF, JSON


def test_a_pdf_that_breaks_while_reading_is_a_pdf_error(monkeypatch):
    from prebuttal.ingestion import pdf

    def boom(*a, **kw):
        raise KeyError("/Font")

    monkeypatch.setattr(pdf, "_ingest", boom)
    with pytest.raises(pdf.PDFError, match=r"cannot read paper\.pdf: KeyError"):
        pdf.ingest_pdf_bytes(make_pdf_bytes(), source_path="dir/paper.pdf")


def test_json_roots_of_the_wrong_type_are_ignored(latex_project, monkeypatch):
    from prebuttal import modelscan, plantrack
    from prebuttal.projects import load_projects, registry_path

    registry_path().parent.mkdir(parents=True, exist_ok=True)
    registry_path().write_text("[1, 2]", encoding="utf-8")
    assert load_projects() == {}
    registry_path().write_text('{"projects": null}', encoding="utf-8")
    assert load_projects() == {}

    rec = _archive(latex_project)
    (rec.dir_path / plantrack.TRACK_FILE).write_text("null", encoding="utf-8")
    assert plantrack._load(rec) is None

    class _Resp:
        status_code = 200

        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    monkeypatch.setattr(modelscan.httpx, "get", lambda *a, **kw: _Resp([1, 2]))
    assert modelscan.openai_models("k") is None
    monkeypatch.setattr(
        modelscan.httpx, "get", lambda *a, **kw: _Resp({"data": [None, {"id": 7}, "x"]})
    )
    assert modelscan.anthropic_models("k") == ["7"]


# ------------------------------------------------------------------ calibration script


def test_calibration_refuses_a_venue_of_another_scale():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "calibration"))
    from calibrate import venue_matches

    assert venue_matches("ICLR.cc/2024/Conference", "iclr")
    assert venue_matches("NeurIPS.cc/2023/Conference", "neurips")
    assert not venue_matches("ICLR.cc/2024/Conference", "icml")
    assert not venue_matches("NeurIPS.cc/2023/Conference", "iclr")


# ------------------------------------------------------------------ second review round


def test_token_counts_of_any_type_never_break_a_report():
    from prebuttal.models import Usage

    u = Usage(None, "x")  # type: ignore[arg-type]
    assert (u.prompt_tokens, u.completion_tokens) == (0, 0)
    u.add(Usage(-5, 3.7))  # type: ignore[arg-type]
    assert (u.prompt_tokens, u.completion_tokens) == (0, 3)


def _figure_dir(tmp_path, labels, files):
    figs = tmp_path / "figures"
    figs.mkdir(exist_ok=True)
    if labels is not None:
        (figs / "figures.json").write_text(json.dumps(labels), encoding="utf-8")
    for name, data in files.items():
        (figs / name).write_bytes(data)


def test_retry_refuses_figures_removed_or_replaced(tmp_path):
    from prebuttal.models import FigureImage, figures_digest
    from prebuttal.retry import RetryError, load_figures

    recorded = figures_digest([FigureImage("p1", b"one"), FigureImage("p2", b"two")])
    _figure_dir(tmp_path, ["p1", "p2"], {"01.png": b"one", "02.png": b"two"})
    assert len(load_figures(tmp_path, recorded)) == 2
    (tmp_path / "figures" / "02.png").write_bytes(b"other")  # same name, other image
    with pytest.raises(RetryError, match="changed since"):
        load_figures(tmp_path, recorded)
    (tmp_path / "figures" / "figures.json").unlink()  # the index gone, images kept
    with pytest.raises(RetryError, match="changed since"):
        load_figures(tmp_path, recorded)
    assert load_figures(tmp_path, figures_digest([])) == []  # a run without figures


def test_a_run_number_is_never_reused_after_rm(latex_project):
    from prebuttal.runs import delete_runs

    a = _archive(latex_project)
    b = _archive(latex_project, rating_shift=1)
    assert (a.run_no, b.run_no) == (1, 2)
    delete_runs({b.id})
    c = _archive(latex_project)
    assert c.run_no == 3


def test_a_rename_during_a_run_archives_it_under_the_new_name(latex_project):
    from prebuttal.projects import rename_project

    a = _archive(latex_project)
    rename_project(a.project, "renamed")
    report, venue = make_report(latex_project)
    rec = save_run(
        report, venue, load_config(None), md="#", json_str="{}", html=None, project=a.project
    )
    assert (rec.project, rec.run_no) == ("renamed", 2)


def test_a_rename_that_fails_halfway_leaves_the_history_as_it_was(latex_project, monkeypatch):
    from prebuttal import projects

    a = _archive(latex_project)

    def broken(_p):
        raise OSError("disk full")

    monkeypatch.setattr(projects, "save_projects", broken)
    with pytest.raises(OSError):
        projects.rename_project(a.project, "elsewhere")
    assert {r.project for r in load_history()} == {a.project}


def test_a_declared_bibliography_that_is_missing_is_a_warning(tmp_path):
    from prebuttal.check import ERROR, WARNING, check_latex
    from prebuttal.venues import get_venue

    (tmp_path / "main.tex").write_text(_CITING, encoding="utf-8")
    (tmp_path / "draft.bib").write_text("@article{onlyelsewhere,\n title={T}}\n", encoding="utf-8")
    result = check_latex(tmp_path, get_venue("neurips").rules)
    found = [f for f in result.findings if "refs.bib" in f.message]
    assert found and found[0].level == WARNING
    assert not any(f.level == ERROR and "onlyelsewhere" in f.message for f in result.findings)


def test_an_empty_report_folder_gets_a_gitignore(tmp_path):
    from prebuttal.outputs import write_local

    empty = tmp_path / "reports"
    empty.mkdir()
    write_local(empty, "demo", "iclr", {"md": "# r"})
    assert (empty / ".gitignore").is_file()
    used = tmp_path / "kept"
    used.mkdir()
    (used / "notes.md").write_text("mine", encoding="utf-8")
    write_local(used, "demo", "iclr", {"md": "# r"})
    assert not (used / ".gitignore").exists()  # a folder the user may commit


class _NullAC(PersonaFakeProvider):
    def _complete(self, **kw):
        _text, usage = super()._complete(**kw)
        return json.dumps({"meta_review": None, "action_plan": [None]}), usage


def test_null_fields_are_no_meta_review(latex_project, shared_calls):
    from prebuttal.ingestion import ingest
    from prebuttal.orchestrator import run_report
    from prebuttal.venues import get_venue

    cfg = load_config(None)
    providers = {
        r.id: PersonaFakeProvider(backend="fake", calls=shared_calls) for r in cfg.reviewers
    }
    ac = _NullAC(backend="fake-ac", calls=shared_calls)
    report = run_report(
        ingest(str(latex_project)), cfg, get_venue("iclr"), providers, ac, log=lambda m: None
    )
    assert not report.meta.parse_ok and report.meta.meta_review == ""
    assert any("not valid JSON" in c["system"] for c in shared_calls)


def test_retry_finds_a_custom_venue_given_as_a_path(tmp_path):
    from prebuttal.report import _venue_json
    from prebuttal.retry import RetryError, venue_for_retry
    from prebuttal.venues import get_venue

    folder = tmp_path / "elsewhere"
    folder.mkdir()
    (folder / "lab-2027.md").write_text("Rate the paper.", encoding="utf-8")
    path = folder / "lab-2027.toml"
    path.write_text(
        'name = "Lab 2027"\nform = "lab-2027.md"\nrating = "rating"\n'
        '[[fields]]\nkey = "rating"\nlabel = "Rating"\nkind = "score"\nmax = 5\n',
        encoding="utf-8",
    )
    live = get_venue(str(path))
    data = {"venue": _venue_json(live)}
    with pytest.raises(RetryError):
        venue_for_retry(data)  # not on the search path by its name
    assert venue_for_retry(data, str(path)).key == live.key


def test_retry_uses_the_runs_settings_and_refuses_a_changed_agent():
    from prebuttal.config import AgentSpec
    from prebuttal.retry import RetryError, retry_config

    cfg = load_config(None)
    cfg.agents["mine"] = AgentSpec(command=["mine", "--fast"])
    resolved = {
        "max_tokens": 1234,
        "budget_chars": 5678,
        "agents": {"mine": {"command": ["mine", "--fast"], "stdin": True}},
    }
    out = retry_config(cfg, resolved, {"agent-mine"})
    assert (out.max_tokens, out.budget_chars) == (1234, 5678)
    resolved["agents"]["mine"]["command"] = ["mine", "--other"]
    with pytest.raises(RetryError, match="custom agent 'mine'"):
        retry_config(cfg, resolved, {"agent-mine"})


def test_the_trend_line_joins_one_venue_only(latex_project):
    from prebuttal.dashboard import _sparkline

    a = _archive(latex_project)
    b = _archive(latex_project, rating_shift=1)
    c = _archive(latex_project)
    assert _sparkline([c, b, replace(a, venue="icml")]).count("<circle") == 2
    assert _sparkline([c, replace(b, venue="icml"), a]) == ""  # one point left


def test_trust_is_bound_to_the_content_that_was_parsed(tmp_path):
    from prebuttal import trust

    p = tmp_path / "prebuttal.toml"
    p.write_text("[default]\nseed = 1\n", encoding="utf-8")
    cfg = load_config(p)
    trust.remember(str(p), cfg.config_sha256)
    assert trust.is_trusted(str(p), cfg.config_sha256)
    p.write_text("[default]\nseed = 2\n", encoding="utf-8")  # swapped after parsing
    assert not trust.is_trusted(str(p))
    assert trust.is_trusted(str(p), cfg.config_sha256)  # what was parsed stays trusted


def test_nested_fields_of_the_wrong_type_in_model_listings(monkeypatch):
    from prebuttal import modelscan

    class _Resp:
        status_code = 200

        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    data = {"models": [{"name": "models/g1", "supportedGenerationMethods": None}]}
    monkeypatch.setattr(modelscan.httpx, "get", lambda *a, **kw: _Resp(data))
    assert modelscan.gemini_models("k") == []
    data = {"data": [{"id": "x/y:free", "architecture": None}, {"id": "a/b", "pricing": None}]}
    monkeypatch.setattr(modelscan.httpx, "get", lambda *a, **kw: _Resp(data))
    assert modelscan.openrouter_catalog() == ([], {})


def test_calibration_accepts_a_years_custom_venue():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "calibration"))
    from calibrate import venue_matches

    assert venue_matches("ICLR.cc/2024/Conference", "iclr-2024")
    assert not venue_matches("ICLR.cc/2024/Conference", "icml-2024")


# ------------------------------------------------------------------ third review round


def test_rm_keeps_a_run_whose_files_cannot_be_deleted(latex_project, monkeypatch):
    from prebuttal import runs

    a = _archive(latex_project)
    b = _archive(latex_project, rating_shift=1)
    real = runs.shutil.rmtree

    def held(path, *args, **kw):
        if Path(path) == b.dir_path:
            raise PermissionError("in use")
        return real(path, *args, **kw)

    monkeypatch.setattr(runs.shutil, "rmtree", held)
    with pytest.raises(OSError, match="could not delete"):
        runs.delete_runs({a.id, b.id})
    assert [r.id for r in load_history()] == [b.id]  # still listed: rm can be tried again
    assert not a.dir_path.exists() and b.dir_path.exists()


def test_rm_of_the_newest_run_of_an_old_registry_keeps_its_number(latex_project):
    from prebuttal.projects import load_projects, registry_path, save_projects
    from prebuttal.runs import delete_runs

    _archive(latex_project)
    b = _archive(latex_project, rating_shift=1)
    projects = load_projects()
    projects[b.project].last_run_no = 0  # as written before 0.7.0
    save_projects(projects)
    assert "last_run_no" not in registry_path().read_text(encoding="utf-8")
    delete_runs({b.id})
    assert _archive(latex_project).run_no == 3


def test_a_renamed_projects_old_name_is_not_given_to_another_paper(tmp_path):
    from prebuttal.projects import assign_project, rename_project

    first = tmp_path / "a.pdf"
    other = tmp_path / "b.pdf"
    key = assign_project(str(first), "Draft")
    rename_project(key, "final")
    assert assign_project(str(other), "Draft") != key


def test_two_retries_of_one_run_are_one_version(latex_project):
    from prebuttal.runs import revisions

    a = _archive(latex_project)
    r1 = replace(_archive(latex_project), retry_of=a.id)
    r2 = replace(_archive(latex_project), retry_of=a.id)
    assert [r.id for r in revisions([r2, r1, a])] == [r2.id]


def test_retry_checks_only_the_agents_it_runs():
    from prebuttal.retry import retry_config

    resolved = {"agents": {"gone": {"command": ["gone"], "stdin": True}}}
    cfg = load_config(None)  # no [agents.gone] here
    assert retry_config(cfg, resolved, {"agent-claude"}).max_tokens == cfg.max_tokens


def test_a_damaged_resolved_config_is_not_read_as_an_old_archive(tmp_path):
    from prebuttal.retry import RetryError, load_resolved

    assert load_resolved(tmp_path) == {}  # archived before it existed
    (tmp_path / "resolved-config.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(RetryError, match="unreadable"):
        load_resolved(tmp_path)


def test_an_unreadable_pack_is_a_retry_error(tmp_path):
    from prebuttal.retry import RetryError, load_pack

    (tmp_path / "pack.md").write_bytes(b"\xff\xfe broken")
    with pytest.raises(RetryError, match="unreadable"):
        load_pack(tmp_path)


def test_a_venue_given_by_a_relative_path_records_where_it_is(tmp_path, monkeypatch):
    from prebuttal.venues import get_venue

    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "lab.md").write_text("Rate it.", encoding="utf-8")
    (rules / "lab.toml").write_text(
        'name = "Lab"\nform = "lab.md"\nrating = "rating"\n'
        '[[fields]]\nkey = "rating"\nlabel = "Rating"\nkind = "score"\nmax = 5\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    venue = get_venue("rules/lab.toml")
    assert Path(venue.origin).is_absolute() and Path(venue.origin) == rules / "lab.toml"


def test_a_stale_bbl_does_not_hide_a_key_missing_from_the_bib(tmp_path):
    from prebuttal.check import check_latex
    from prebuttal.venues import get_venue

    (tmp_path / "main.tex").write_text(_CITING, encoding="utf-8")
    (tmp_path / "refs.bib").write_text("@article{other,\n title={T}}\n", encoding="utf-8")
    (tmp_path / "main.bbl").write_text("\\bibitem{onlyelsewhere} X.\n", encoding="utf-8")
    result = check_latex(tmp_path, get_venue("neurips").rules)
    assert any("onlyelsewhere" in f.message for f in result.findings)


def test_an_over_long_pdf_without_a_references_heading_is_a_warning():
    from prebuttal.check import WARNING, CheckResult, _pdf_format
    from prebuttal.venues import CheckRules

    result = CheckResult(source="x.pdf", kind="pdf")
    rules = CheckRules(page_limit=9)
    _pdf_format(result, rules, [{"text": "Intro", "page": 0, "x": 0, "y": 0}], [(600, 800)] * 11)
    assert [f.level for f in result.findings] == [WARNING]
    assert "11 pages" in result.findings[0].message


def test_a_pdf_that_breaks_while_checked_is_a_check_error(monkeypatch):
    from prebuttal import check
    from prebuttal.ingestion import pdf
    from prebuttal.venues import CheckRules

    def boom(*a, **kw):
        raise ValueError("bad stream")

    monkeypatch.setattr(pdf, "_text_lines", boom)
    with pytest.raises(check.CheckError, match="cannot read PDF: ValueError"):
        check.check_pdf_bytes(make_pdf_bytes(), CheckRules(page_limit=9))


def test_a_root_paper_tex_wins_over_a_nested_main_tex(tmp_path):
    from prebuttal.ingestion.latex import find_root_tex

    (tmp_path / "paper.tex").write_text("\\documentclass{article}", encoding="utf-8")
    (tmp_path / "supp").mkdir()
    (tmp_path / "supp" / "main.tex").write_text("\\documentclass{article}", encoding="utf-8")
    assert find_root_tex(tmp_path) == tmp_path / "paper.tex"


class _ScoreOnly(PersonaFakeProvider):
    def _complete(self, **kw):
        _text, usage = super()._complete(**kw)
        if "estimated_rating" in kw["system"]:
            return _text, usage
        return json.dumps({"rating": 8, "weaknesses": [None]}), usage


def test_a_review_with_a_score_and_no_text_is_not_finished(latex_project, shared_calls):
    from prebuttal.ingestion import ingest
    from prebuttal.orchestrator import run_report
    from prebuttal.venues import get_venue

    cfg = load_config(None)
    providers = {r.id: _ScoreOnly(backend="fake", calls=shared_calls) for r in cfg.reviewers}
    ac = PersonaFakeProvider(backend="fake-ac", calls=shared_calls)
    report = run_report(
        ingest(str(latex_project)), cfg, get_venue("iclr"), providers, ac, log=lambda m: None
    )
    assert not any(r.parse_ok for r in report.reviews)
    assert report.reviews[0].error == "the review has a score but no text"


def test_a_plan_item_whose_issue_is_not_text_is_dropped():
    from prebuttal.orchestrator import coerce_action_plan

    items = coerce_action_plan(
        [{"issue": {"x": 1}, "action": "a"}, {"issue": "Table 3", "action": ["no"]}], ["R1"]
    )
    assert [(i.issue, i.action) for i in items] == [("Table 3", "")]


def test_a_non_text_answer_is_a_provider_error():
    from prebuttal.providers.base import ProviderError

    class _List(PersonaFakeProvider):
        def _complete(self, **kw):
            return ["not", "text"], None

    with pytest.raises(ProviderError, match="not text"):
        _List().complete(system="s", user="u", temperature=0, seed=None, max_tokens=10)


# ------------------------------------------------------------------ fourth review round


def test_an_old_name_is_not_taken_by_project_or_rename(tmp_path):
    from prebuttal.projects import ProjectError, assign_project, rename_project

    draft = assign_project(str(tmp_path / "a.pdf"), "Draft")
    rename_project(draft, "final")
    # --project with the old name means the renamed project, not a new one
    assert assign_project(str(tmp_path / "b.pdf"), "Other", explicit=draft) == "final"
    other = assign_project(str(tmp_path / "c.pdf"), "Third")
    with pytest.raises(ProjectError, match="already exists"):
        rename_project(other, draft)
    assert rename_project("final", draft)[0] == draft  # back to its own old name


def test_a_chapter_named_main_tex_is_not_taken_for_the_paper(tmp_path):
    from prebuttal.ingestion.latex import find_root_tex

    (tmp_path / "manuscript.tex").write_text(
        "\\documentclass{article}\\begin{document}\\input{main}\\end{document}",
        encoding="utf-8",
    )
    (tmp_path / "main.tex").write_text(
        "\\section{Intro}\n% \\documentclass{x} in a comment\n", encoding="utf-8"
    )
    assert find_root_tex(tmp_path) == tmp_path / "manuscript.tex"


def test_rm_deletes_files_outside_the_history_lock(latex_project, monkeypatch):
    from prebuttal import runs

    a = _archive(latex_project)
    held = []
    real = runs.shutil.rmtree

    def watch(path, *args, **kw):
        held.append(_locked(runs))
        return real(path, *args, **kw)

    monkeypatch.setattr(runs.shutil, "rmtree", watch)
    assert runs.delete_runs({a.id}) == 1
    assert held == [False]


def test_every_view_counts_versions_alike(latex_project):
    from prebuttal.runs import previous_version, revisions, version_key

    v1 = _archive(latex_project)
    v2 = _archive(latex_project, rating_shift=1)
    r1 = replace(_archive(latex_project), retry_of=v1.id)  # a retry of v1, after v2
    r2 = replace(_archive(latex_project), retry_of=r1.id)
    runs = [r2, r1, v2, v1]  # newest first
    assert [r.id for r in revisions(runs)] == [v2.id, r2.id]  # v1 stays the older version
    assert previous_version(runs, version_key(runs, v2)).id == r2.id
    assert previous_version(runs, version_key(runs, r1)) is None
    # the middle retry deleted: the recorded version keeps r2 with v1
    kept = [replace(r2, version=v1.id), v2, v1]
    assert [r.id for r in revisions(kept)] == [v2.id, r2.id]


def test_a_retry_records_its_version(latex_project):
    a = _archive(latex_project)
    report, venue = make_report(latex_project)
    r1 = save_run(
        report,
        venue,
        load_config(None),
        md="#",
        json_str="{}",
        html=None,
        project=a.project,
        retry_of=a.id,
    )
    r2 = save_run(
        report,
        venue,
        load_config(None),
        md="#",
        json_str="{}",
        html=None,
        project=a.project,
        retry_of=r1.id,
    )
    assert r1.version == r2.version == a.id


def test_references_in_the_left_column_end_the_page_there():
    from prebuttal.check import CheckResult, _pdf_format
    from prebuttal.venues import CheckRules

    w, h = 600.0, 800.0
    lines = [{"text": "Intro", "page": 0, "x": 50, "y": 100}]
    lines += [{"text": "body", "page": 1, "x": 50, "y": 100}]
    lines += [{"text": "References", "page": 2, "x": 50, "y": 300}]
    # the right column of the references page starts higher than the heading
    lines += [{"text": f"[{i}] ref", "page": 2, "x": 320, "y": 80 + 20 * i} for i in range(5)]
    result = CheckResult(source="x.pdf", kind="pdf")
    _pdf_format(result, CheckRules(page_limit=2), lines, [(w, h)] * 3)
    assert not result.findings
    assert "main text 2 of 2 pages" in result.passed


def test_diff_says_when_no_reviewer_is_in_both_runs(latex_project, offline_diff):
    from prebuttal.revdiff import compute_diff, render_diff_markdown

    a = _archive(latex_project)
    b = _archive(latex_project, rating_shift=1)
    data = json.loads((b.dir_path / "report.json").read_text(encoding="utf-8"))
    for r in data["reviewers"]:
        r["reviewer_id"] = "X" + r["reviewer_id"]
    (b.dir_path / "report.json").write_text(json.dumps(data), encoding="utf-8")
    text = render_diff_markdown(compute_diff(a, b))
    assert "no reviewer is in both runs" in text


def test_an_object_summary_is_no_text():
    from prebuttal.orchestrator import _has_text, coerce_fields
    from prebuttal.venues import get_venue

    venue = get_venue("iclr")
    fields = coerce_fields({"summary": {"a": 1}, "rating": 8}, venue)
    assert fields["summary"] == "" and not _has_text(fields, venue)


def test_latest_files_of_formats_not_written_are_removed(tmp_path):
    from prebuttal.outputs import write_local

    write_local(tmp_path / "r", "demo", "iclr", {"md": "# one", "json": "{}"})
    write_local(tmp_path / "r", "demo", "iclr", {"md": "# two"})
    assert (tmp_path / "r" / "demo" / "latest.md").read_text(encoding="utf-8") == "# two"
    assert not (tmp_path / "r" / "demo" / "latest.json").exists()


def test_retry_settings_of_the_wrong_type_are_a_damaged_archive():
    from prebuttal.retry import RetryError, retry_config

    cfg = load_config(None)
    assert retry_config(cfg, {}, set()).max_tokens == cfg.max_tokens  # an old archive
    for bad in ({"max_tokens": None}, {"agents": []}, {"budget_chars": "9"}):
        with pytest.raises(RetryError, match="invalid"):
            retry_config(cfg, bad, set())


def test_a_report_json_of_the_wrong_shape_is_a_value_error():
    from prebuttal.report import report_from_dict

    for bad in (None, [], {"reviewers": {}}, {"reviewers": [], "meta": {}, "aggregate": {}}):
        with pytest.raises(ValueError):
            report_from_dict(bad)  # type: ignore[arg-type]


def test_a_venue_rating_that_is_not_a_name_is_a_venue_error():
    from prebuttal.venues import VenueError
    from prebuttal.venues.custom import venue_from_spec

    spec = {
        "name": "X",
        "rating": ["rating"],
        "fields": [{"key": "rating", "label": "R", "kind": "score", "max": 5}],
    }
    with pytest.raises(VenueError, match="must name a score field"):
        venue_from_spec("x", spec, form="Rate it.")


# ------------------------------------------------------------------ fifth review round


def _locked(runs) -> bool:
    """Whether someone holds the history lock (probed with a short wait)."""
    try:
        with runs.store_lock(wait_s=0):
            return False
    except OSError:
        return True


def test_archiving_writes_only_under_the_lock(latex_project, monkeypatch):
    from prebuttal import runs

    _archive(latex_project)
    seen = []
    real = runs._write_run_files

    def check(*a, **kw):
        seen.append(_locked(runs))  # held by this save
        return real(*a, **kw)

    monkeypatch.setattr(runs, "_write_run_files", check)
    _archive(latex_project)
    assert seen == [True] and len(load_history()) == 2
    assert not _locked(runs)  # and released


def test_a_lock_file_left_behind_is_not_a_held_lock(latex_project):
    from prebuttal import runs

    runs.runs_root().mkdir(parents=True, exist_ok=True)
    (runs.runs_root() / "history.lock").write_text("", encoding="utf-8")  # a crash's leftover
    assert not _locked(runs)
    _archive(latex_project)
    assert len(load_history()) == 1


def test_a_scores_only_form_is_complete_with_its_scores():
    from prebuttal.orchestrator import _has_text, coerce_fields
    from prebuttal.venues.custom import venue_from_spec

    venue = venue_from_spec(
        "scores",
        {
            "name": "Scores",
            "rating": "rating",
            "fields": [{"key": "rating", "label": "R", "kind": "score", "max": 5}],
        },
        form="Rate it.",
    )
    assert _has_text(coerce_fields({"rating": 5}, venue), venue)


def test_version_order_survives_the_first_run_deleted_or_filtered(latex_project):
    from prebuttal.runs import revisions

    # ids carry the time a version started (archived within one second here)
    v1 = replace(_archive(latex_project), id="20260101-000001-aaaa-p")
    v2 = replace(_archive(latex_project, rating_shift=1), id="20260101-000002-bbbb-p")
    r1 = replace(_archive(latex_project), id="20260101-000003-cccc-p", retry_of=v1.id)
    r1 = replace(r1, version=v1.id)
    assert [r.id for r in revisions([r1, v2])] == [v2.id, r1.id]  # v1 deleted
    assert [r.id for r in revisions([r1, v2, v1], keep=lambda r: r is not v1)] == [
        v2.id,
        r1.id,
    ]


def test_a_retry_of_the_first_version_follows_no_plan(latex_project):
    from prebuttal.plantrack import plan_base

    v1 = _archive(latex_project)
    v2 = _archive(latex_project, rating_shift=1)
    assert plan_base([v2, v1], skip=v1.id) is None  # not v2: it came after
    v3 = _archive(latex_project)
    assert plan_base([v3, v2, v1], skip=v2.id).id == v1.id


def test_the_projects_score_is_the_newest_versions(latex_project):
    from prebuttal.runs import ProjectSummary

    v1 = _archive(latex_project)
    v2 = _archive(latex_project, rating_shift=1)
    late = replace(_archive(latex_project), retry_of=v1.id, version=v1.id)
    p = ProjectSummary(key=v1.project, title="", runs=[late, v2, v1])
    assert p.latest.id == late.id and p.current.id == v2.id
    row = next(ln for ln in render_projects_table([p]).splitlines() if ln.startswith(v1.project))
    assert f"{v2.mean:g}" in row


def test_a_change_from_a_missing_reviewer_is_not_called_noise(latex_project, offline_diff):
    from prebuttal.revdiff import compute_diff, render_diff_markdown

    a = _archive(latex_project)
    b = _archive(latex_project)
    data = json.loads((b.dir_path / "report.json").read_text(encoding="utf-8"))
    data["reviewers"][1]["parse_ok"] = False
    data["reviewers"][1]["rating"] = None
    (b.dir_path / "report.json").write_text(json.dumps(data), encoding="utf-8")
    d = compute_diff(a, b)
    assert d.panel_change and d.noise is None
    assert "the change may come from who is missing" in render_diff_markdown(d)


def test_a_new_archive_without_its_resolved_config_is_damaged(tmp_path):
    from prebuttal.retry import RetryError, load_resolved

    assert load_resolved(tmp_path, "0.6.1") == {}  # an old archive
    with pytest.raises(RetryError, match="missing"):
        load_resolved(tmp_path, "0.7.0")


def test_nested_report_sections_of_the_wrong_type_fail_when_read(latex_project):
    from prebuttal.report import report_from_dict

    rec = _archive(latex_project)
    data = json.loads((rec.dir_path / "report.json").read_text(encoding="utf-8"))
    report_from_dict(data)  # as written: fine
    bad = json.loads(json.dumps(data))
    bad["reviewers"][0]["fields"] = []
    with pytest.raises(ValueError, match="reviewer 1"):
        report_from_dict(bad)
    bad = json.loads(json.dumps(data))
    bad["meta"]["action_plan"] = [None]
    with pytest.raises(ValueError, match="revision plan"):
        report_from_dict(bad)


# ------------------------------------------------------------------ sixth review round


def test_the_history_lock_has_one_holder_however_long_it_is_held(latex_project, monkeypatch):
    import os
    import time

    from prebuttal import runs

    monkeypatch.setattr(runs, "_LOCK_WAIT_S", 0.2)
    with runs.store_lock():
        lock = runs.runs_root() / "history.lock"
        old = time.time() - 3600
        os.utime(lock, (old, old))  # an hour old: no longer read as a crashed holder's
        with pytest.raises(OSError, match="busy"), runs.store_lock():
            pass


def test_project_registration_never_writes_unlocked(tmp_path, monkeypatch):
    from prebuttal import runs
    from prebuttal.projects import assign_project, load_projects

    monkeypatch.setattr(runs, "_LOCK_WAIT_S", 0.2)
    with runs.store_lock(), pytest.raises(OSError, match="busy"):
        assign_project(str(tmp_path / "a.pdf"), "Draft")
    assert load_projects() == {}


def test_a_review_kept_nowhere_is_printed_with_exit_7(
    latex_project, fake_statuses, fake_config, monkeypatch, capsys
):
    from prebuttal import runs

    def broken(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(runs, "_write_run_files", broken)
    toml = fake_config.read_text(encoding="utf-8")
    fake_config.write_text(toml + '\n[output]\ndir = ""\n', encoding="utf-8")
    rc = cli.main(["run", str(latex_project), "--config", str(fake_config), "-y"])
    out = capsys.readouterr()
    assert rc == cli.EXIT_UNSAVED == 7
    assert "could not be saved anywhere" in out.err and "# Prebuttal" in out.out


def test_optional_text_fields_are_not_required():
    from prebuttal.orchestrator import _has_text, coerce_fields
    from prebuttal.venues.custom import venue_from_spec

    venue = venue_from_spec(
        "notes",
        {
            "name": "Notes",
            "rating": "rating",
            "fields": [
                {"key": "rating", "label": "R", "kind": "score", "max": 5},
                {"key": "note", "label": "Note", "kind": "text", "required": False},
            ],
        },
        form="Rate it.",
    )
    assert _has_text(coerce_fields({"rating": 5, "note": ""}, venue), venue)


def test_versions_started_in_one_second_keep_their_order(latex_project):
    from prebuttal.runs import revisions

    v1 = replace(_archive(latex_project), id="20260101-000001-aaaa-p")
    v2 = replace(_archive(latex_project, rating_shift=1), id="20260101-000001-bbbb-p")
    r1 = replace(
        _archive(latex_project),
        id="20260101-000009-cccc-p",
        retry_of=v1.id,
        version=v1.id,
        version_no=v1.run_no,
    )
    assert v1.run_no < v2.run_no < r1.run_no
    assert [r.id for r in revisions([r1, v2])] == [v2.id, r1.id]  # v1 deleted
    assert [r.id for r in revisions([r1, v2, v1], keep=lambda r: r is not v1)] == [
        v2.id,
        r1.id,
    ]


def test_a_retry_records_its_versions_number(latex_project):
    a = _archive(latex_project)
    report, venue = make_report(latex_project)
    r = save_run(
        report,
        venue,
        load_config(None),
        md="#",
        json_str="{}",
        html=None,
        project=a.project,
        retry_of=a.id,
    )
    assert (r.version, r.version_no) == (a.id, a.run_no)


def test_a_missing_round_is_a_changed_panel(latex_project, offline_diff):
    from prebuttal.revdiff import slot_change

    rows = [
        {"reviewer_id": "R1", "persona": "p", "repeat": 0, "rating": 8},
        {"reviewer_id": "R1", "persona": "p", "repeat": 1, "rating": 8},
        {"reviewer_id": "R2", "persona": "q", "repeat": 0, "rating": 4},
        {"reviewer_id": "R2", "persona": "q", "repeat": 1, "rating": 4},
    ]
    fewer = [*rows[:3], {**rows[3], "parse_ok": False, "rating": None}]
    assert slot_change(rows, fewer) == ["R2 · q round 2 (A only)"]
    assert slot_change(rows, rows) == []


def test_the_dashboard_gives_no_direction_when_ratings_differ(latex_project):
    from prebuttal.dashboard import _delta
    from prebuttal.runs import ProjectSummary

    a = _archive(latex_project)
    b = _archive(latex_project, rating_shift=1)
    data = json.loads((b.dir_path / "report.json").read_text(encoding="utf-8"))
    data["reviewers"][1]["parse_ok"] = False
    data["reviewers"][1]["rating"] = None
    (b.dir_path / "report.json").write_text(json.dumps(data), encoding="utf-8")
    html = _delta(ProjectSummary(key=a.project, title="", runs=[b, a]))
    assert "ratings differ" in html and "up" not in html and "down" not in html


def test_a_new_archives_resolved_config_needs_every_field(tmp_path):
    from prebuttal.retry import RetryError, load_resolved

    (tmp_path / "resolved-config.json").write_text("{}", encoding="utf-8")
    assert load_resolved(tmp_path, "0.6.1") == {}
    with pytest.raises(RetryError, match="lacks max_tokens"):
        load_resolved(tmp_path, "0.7.0")


def test_null_review_fields_read_as_empty(latex_project):
    from prebuttal.report import render_markdown, report_from_dict
    from prebuttal.venues import venue_from_report

    rec = _archive(latex_project)
    data = json.loads((rec.dir_path / "report.json").read_text(encoding="utf-8"))
    data["reviewers"][0]["fields"] = None
    report = report_from_dict(data)
    assert report.reviews[0].fields == {}
    assert render_markdown(report, venue_from_report(data))


# ------------------------------------------------------------------ seventh review round


def test_a_named_project_is_kept_when_registering_fails(
    latex_project, fake_statuses, fake_config, monkeypatch
):
    from prebuttal import cli as cli_mod

    def busy(*a, **kw):
        raise OSError("the run history is busy")

    monkeypatch.setattr(cli_mod, "assign_project", busy)
    rc = cli.main(
        ["run", str(latex_project), "--config", str(fake_config), "-y", "--project", "Expected"]
    )
    assert rc == cli.EXIT_OK
    assert load_history()[0].project == "expected"


def test_projects_rm_keeps_a_project_that_got_a_run_meanwhile(latex_project, monkeypatch):
    from prebuttal import runs

    a = _archive(latex_project)
    real = runs.delete_runs

    def and_one_more(ids):
        n = real(ids)
        _archive(latex_project)  # archived while the project was being deleted
        return n

    monkeypatch.setattr(cli, "delete_runs", and_one_more)
    assert cli.main(["projects", "rm", a.project, "-y"]) != cli.EXIT_OK
    from prebuttal.projects import load_projects

    assert a.project in load_projects() and len(load_history()) == 1


def test_an_ac_report_with_every_reviewer_failed_is_still_kept(
    latex_project, fake_statuses, fake_config, monkeypatch, capsys
):
    from prebuttal import runs
    from prebuttal.providers import register_backend
    from prebuttal.providers.base import ProviderError

    class _Down(PersonaFakeProvider):
        def _complete(self, **kw):
            if "estimated_rating" not in kw["system"]:
                raise ProviderError("HTTP 503")
            return super()._complete(**kw)

    register_backend("fake", lambda m, cfg, t: _Down(model="fake-m"))

    def broken(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(runs, "_write_run_files", broken)
    toml = fake_config.read_text(encoding="utf-8")
    fake_config.write_text(toml + '\n[output]\ndir = ""\n', encoding="utf-8")
    rc = cli.main(["run", str(latex_project), "--config", str(fake_config), "-y"])
    assert rc == cli.EXIT_UNSAVED
    assert "# Prebuttal" in capsys.readouterr().out


def test_rm_of_a_versions_first_run_keeps_old_retries_in_place(latex_project):
    from prebuttal.runs import delete_runs, rewrite_history, store_lock

    v1 = _archive(latex_project)
    v2 = _archive(latex_project, rating_shift=1)
    r1 = _archive(latex_project)
    with store_lock():  # as written before 0.7.0: a retry with no version
        recs = [replace(r, retry_of=v1.id) if r.id == r1.id else r for r in load_history()]
        rewrite_history(recs)
    delete_runs({v1.id})
    kept = next(r for r in load_history() if r.id == r1.id)
    assert (kept.version, kept.version_no) == (v1.id, v1.run_no)
    assert v1.run_no < v2.run_no


def test_a_custom_agent_with_no_recorded_settings_is_not_retried():
    from prebuttal.config import AgentSpec
    from prebuttal.retry import RetryError, retry_config

    cfg = load_config(None)
    cfg.agents["mine"] = AgentSpec(command=["mine"])
    resolved = {"prebuttal_version": "0.7.0", "agents": {}}
    with pytest.raises(RetryError, match="no settings for custom agent"):
        retry_config(cfg, resolved, {"agent-mine"})
    assert retry_config(cfg, {"agents": {}}, {"agent-mine"})  # an older archive


def test_another_model_for_a_reviewer_is_a_changed_panel():
    from prebuttal.revdiff import slot_change

    a = [{"reviewer_id": "R1", "persona": "p", "rating": 8, "backend": "x", "model": "m1"}]
    b = [{**a[0], "model": "m2"}]
    assert slot_change(a, b) == ["R1 · p model x/m1 → x/m2"]


def test_a_field_value_of_the_wrong_type_fails_when_read(latex_project):
    from prebuttal.report import report_from_dict

    rec = _archive(latex_project)
    data = json.loads((rec.dir_path / "report.json").read_text(encoding="utf-8"))
    data["reviewers"][0]["fields"]["weaknesses"] = 3.5
    report_from_dict(json.loads(json.dumps(data)))  # a number is a value
    data["reviewers"][0]["fields"]["weaknesses"] = {"a": 1}
    with pytest.raises(ValueError, match="invalid field 'weaknesses'"):
        report_from_dict(data)


def test_reports_name_the_required_fields_a_reviewer_left_out(latex_project):
    from prebuttal.report import left_out, render_markdown
    from prebuttal.share import render_share_html

    report, venue = make_report(latex_project)
    report.reviews[0].fields["questions"] = []
    label = next(f.label for f in venue.fields if f.key == "questions")
    assert label in left_out(report.reviews[0], venue)
    assert f"Left out by this reviewer: {label}" in render_markdown(report, venue)
    assert f"left out: {label}" in render_share_html(report, venue, "https://example.org")
