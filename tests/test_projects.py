"""Projects, local report folders, run references and the management commands."""

import json
from pathlib import Path

import pytest

from prebuttal import cli
from prebuttal.config import ConfigError, load_config
from prebuttal.projects import assign_project, load_projects, slugify, source_identity
from prebuttal.runs import history_path, load_history, resolve_ref

PROJECT = "latent-bottleneck-transformers"


@pytest.fixture
def run(tmp_path, monkeypatch, latex_project, fake_statuses, fake_config, capsys):
    """``run(*extra)`` reviews the fixture paper once; returns (rc, stdout)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_open_in_browser", lambda path: None)

    def _run(*extra: str):
        rc = cli.main(["run", str(latex_project), "--config", str(fake_config), *extra])
        return rc, capsys.readouterr().out

    return _run


def _cli(capsys, *argv: str):
    rc = cli.main(list(argv))
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


# ------------------------------------------------------------ local outputs


def test_default_run_writes_md_and_html_into_a_fresh_folder(run, tmp_path):
    rc, out = run()
    assert rc == cli.EXIT_OK
    reports = tmp_path / "prebuttal-reports"
    proj = reports / PROJECT
    (run_dir,) = [d for d in proj.iterdir() if d.is_dir()]
    assert run_dir.name.endswith("_iclr")
    assert (run_dir / "report.md").is_file() and (run_dir / "report.html").is_file()
    assert not (run_dir / "report.json").exists()  # JSON lives in the archive
    assert (proj / "latest.md").read_text(encoding="utf-8") == (run_dir / "report.md").read_text(
        encoding="utf-8"
    )
    # unpublished work stays out of git
    assert "*" in (reports / ".gitignore").read_text(encoding="utf-8")
    assert f"Saved:    {PROJECT}#1" in out
    assert "Report:" in out and "report.md" in out
    assert "prebuttal diff" not in out  # nothing to diff on the first run


def test_second_run_never_overwrites_and_reports_the_change(run, tmp_path):
    run()
    rc, out = run("--note", "added Perceiver baseline")
    assert rc == cli.EXIT_OK
    run_dirs = [d for d in (tmp_path / "prebuttal-reports" / PROJECT).iterdir() if d.is_dir()]
    assert len(run_dirs) == 2  # same minute -> "-2" suffix, not an overwrite
    assert f"Change:   +0 vs {PROJECT}#1" in out
    assert "prebuttal diff" in out
    assert load_history()[0].note == "added Perceiver baseline"


def test_format_and_output_dir_choices(run, tmp_path):
    run("--format", "json", "--out-dir", "out")
    (run_dir,) = [d for d in (tmp_path / "out" / PROJECT).iterdir() if d.is_dir()]
    assert [p.name for p in run_dir.iterdir()] == ["report.json"]

    rc, _ = run("--format", "pdf")
    assert rc == cli.EXIT_USAGE  # rejected before any review runs


def test_no_save_leaves_the_store_untouched(run, tmp_path):
    rc, out = run("--no-save")
    assert rc == cli.EXIT_OK and "Saved:" not in out
    assert load_history() == [] and load_projects() == {}
    assert (tmp_path / "prebuttal-reports" / PROJECT / "latest.html").is_file()


def test_output_dir_empty_keeps_reports_in_the_archive_only(run, tmp_path):
    rc, out = run("--out-dir", "")
    assert rc == cli.EXIT_OK
    assert not (tmp_path / "prebuttal-reports").exists()
    assert "Report:" not in out
    assert (load_history()[0].dir_path / "report.html").is_file()


def test_output_config_section(tmp_path):
    cfg_path = tmp_path / "p.toml"
    cfg_path.write_text('[output]\ndir = "rev"\nformats = ["html", "json"]\n', encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.output_dir == "rev" and cfg.output_formats == ("html", "json")
    cfg_path.write_text('[output]\nformats = ["docx"]\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(cfg_path)


# ----------------------------------------------------------------- projects


def test_project_follows_the_source_not_the_title(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")
    key = assign_project(str(pdf), "Mamba: Linear-Time Sequence Modeling")
    assert key == "mamba-linear-time-sequence"
    assert assign_project(str(pdf), "Mamba-2: a renamed revision") == key
    assert load_projects()[key].title == "Mamba-2: a renamed revision"
    # a different paper with the same title gets its own project
    other = tmp_path / "other.pdf"
    other.write_bytes(b"%PDF")
    assert assign_project(str(other), "Mamba: Linear-Time Sequence Modeling") == key + "-2"


def test_arxiv_versions_share_a_project():
    assert source_identity("2312.00752v2") == source_identity("https://arxiv.org/abs/2312.00752")


def test_explicit_project_name(run):
    rc, out = run("--project", "My Thesis Ch3")
    assert rc == cli.EXIT_OK
    assert "my-thesis-ch3#1" in out
    rc, out = run()  # the source now belongs to that project
    assert "my-thesis-ch3#2" in out


def test_slugify_keeps_keys_short():
    assert slugify("Direct Preference Optimization: Your Language Model is Secretly") == (
        "direct-preference-optimization"
    )
    assert slugify("") == "paper"


def test_projects_list_rename_and_rm(run, capsys):
    run()
    run()
    rc, out, _ = _cli(capsys, "projects")
    assert rc == cli.EXIT_OK and PROJECT in out and "Latent Bottleneck" in out

    rc, out, _ = _cli(capsys, "projects", "--json")
    (entry,) = json.loads(out)
    assert entry["project"] == PROJECT and entry["runs"] == 2

    rc, out, _ = _cli(capsys, "projects", "rename", PROJECT, "lbt")
    assert rc == cli.EXIT_OK
    assert {r.label for r in load_history()} == {"lbt#1", "lbt#2"}
    rc, out = run()
    assert "lbt#3" in out  # new runs of the same source follow the rename

    rc, _, err = _cli(capsys, "projects", "rm", "lbt")
    assert rc == cli.EXIT_USAGE and "-y" in err  # non-interactive needs -y
    rc, out, _ = _cli(capsys, "projects", "rm", "lbt", "-y")
    assert rc == cli.EXIT_OK and load_history() == []


# ------------------------------------------------------------ run references


def test_run_references(run):
    for _ in range(3):
        run()
    newest = load_history()[0]
    assert resolve_ref(None)[0] == newest
    assert resolve_ref("latest")[0] == newest
    assert resolve_ref(PROJECT)[0] == newest
    assert resolve_ref(f"{PROJECT}#1")[0].run_no == 1
    assert resolve_ref(f"{PROJECT}~1")[0].run_no == 2
    assert resolve_ref("~2")[0].run_no == 1
    assert resolve_ref(newest.id[:20])[0] == newest
    match, candidates = resolve_ref(f"{PROJECT}#9")
    assert match is None and len(candidates) == 3


def test_legacy_history_without_projects_still_loads(tmp_path):
    rec = {
        "id": "20250101-120000-abcd-old-paper",
        "ts": "2025-01-01T12:00:00+00:00",
        "paper_title": "Old Paper",
        "source": "old.pdf",
        "venue": "iclr",
        "seed": 42,
        "mean": 5.0,
        "std": 1.0,
        "n": 3,
        "dir": str(tmp_path / "x"),
    }
    history_path().parent.mkdir(parents=True, exist_ok=True)
    history_path().write_text(json.dumps(rec) + "\n", encoding="utf-8")
    (loaded,) = load_history()
    assert loaded.label == "old-paper#1"


# -------------------------------------------------------- management commands


def test_show_open_diff_note_export_rm(run, tmp_path, capsys, monkeypatch):
    rc, _, err = _cli(capsys, "diff")
    assert rc == cli.EXIT_USAGE and "no saved runs" in err

    run()
    rc, _, err = _cli(capsys, "diff")
    assert rc == cli.EXIT_USAGE and "first run" in err
    run()

    rc, out, _ = _cli(capsys, "show")
    assert rc == cli.EXIT_OK and "Prebuttal" in out
    rc, out, _ = _cli(capsys, "diff")  # latest vs the one before it
    assert rc == cli.EXIT_OK and "Revision diff" in out
    rc, out, _ = _cli(capsys, "diff", f"{PROJECT}#1", f"{PROJECT}#2")
    assert rc == cli.EXIT_OK and "Revision diff" in out

    opened: list[Path] = []
    monkeypatch.setattr(cli, "_open_in_browser", opened.append)
    rc, out, _ = _cli(capsys, "show", f"{PROJECT}#1", "--open")
    assert rc == cli.EXIT_OK and opened[0].name == "report.html"

    rc, out, _ = _cli(capsys, "note", "latest", "rebuttal draft v2")
    assert rc == cli.EXIT_OK
    rc, out, _ = _cli(capsys, "runs", PROJECT)
    assert "rebuttal draft v2" in out

    rc, out, _ = _cli(capsys, "show", "-o", "exported.md")
    assert rc == cli.EXIT_OK and (tmp_path / "exported.md").is_file()

    # a bare project name is refused: it is one word away from `projects rm`
    rc, _, err = _cli(capsys, "rm", PROJECT, "-y")
    assert rc == cli.EXIT_USAGE and f"prebuttal projects rm {PROJECT}" in err
    assert len(load_history()) == 2

    rc, out, _ = _cli(capsys, "rm", f"{PROJECT}#1", "-y")
    assert rc == cli.EXIT_OK
    assert [r.run_no for r in load_history()] == [2]  # numbers stay stable
    assert not resolve_ref(f"{PROJECT}#1")[0]


def test_open_renders_html_for_runs_archived_without_it(run, capsys, monkeypatch):
    run()
    rec = load_history()[0]
    (rec.dir_path / "report.html").unlink()
    opened: list[Path] = []
    monkeypatch.setattr(cli, "_open_in_browser", opened.append)
    rc, _, _ = _cli(capsys, "show", "--open")
    assert rc == cli.EXIT_OK
    assert "Latent Bottleneck" in opened[0].read_text(encoding="utf-8")


def test_projects_open_is_the_html_overview(run, capsys, monkeypatch):
    run()
    run("--note", "<script>alert(1)</script>")
    opened: list[Path] = []
    monkeypatch.setattr(cli, "_open_in_browser", opened.append)
    rc, _, _ = _cli(capsys, "projects", "--open")
    assert rc == cli.EXIT_OK
    html = opened[0].read_text(encoding="utf-8")
    assert "Latent Bottleneck Transformers" in html
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert "<svg" in html  # trend line once there are two runs
    for rec in load_history():  # relative links resolve next to the dashboard
        link = rec.dir_path.relative_to(opened[0].parent).as_posix() + "/report.html"
        assert f'href="{link}"' in html
        assert (opened[0].parent / link).is_file()


def test_old_history_commands_are_hidden_aliases(run, capsys, monkeypatch, tmp_path):
    """open / export / dashboard and run --stdout / --format work until 0.6, with a notice."""
    run()
    opened: list[Path] = []
    monkeypatch.setattr(cli, "_open_in_browser", opened.append)
    for argv, new in (
        (["open"], "show --open"),
        (["export", "-o", "x.md"], "show -o FILE"),
        (["dashboard", "--no-open"], "projects --open"),
    ):
        rc, _, err = _cli(capsys, *argv)
        assert rc == cli.EXIT_OK and f"is now `prebuttal {new}`" in err
    assert len(opened) == 1  # open; dashboard --no-open writes without opening
    assert (tmp_path / "x.md").is_file()

    rc, out = run("--stdout", "--format", "md")
    assert rc == cli.EXIT_OK and "# Prebuttal" in out

    help_text = cli.build_parser().format_help()
    listed = {ln.split()[0] for ln in help_text.splitlines() if ln[:5].strip() and ln[:4] == "    "}
    assert not listed & {"open", "export", "dashboard"}
    run_help = cli.build_parser()._subparsers._group_actions[0].choices["run"].format_help()
    assert "--stdout" not in run_help and "--format" not in run_help


def test_show_views_are_exclusive(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["show", "--json", "--open"])
    assert exc.value.code == 2


def test_local_folder_named_like_an_arxiv_id_stays_local(tmp_path, monkeypatch):
    """An unpacked arXiv source folder is the user's (maybe revised) copy."""
    from prebuttal import ingestion

    monkeypatch.chdir(tmp_path)
    (tmp_path / "2312.00752").mkdir()
    (tmp_path / "2312.00752" / "main.tex").write_text(
        "\\documentclass{article}\\title{My Revision}\\begin{document}"
        "\\section{Intro}x\\end{document}",
        encoding="utf-8",
    )

    def no_download(*a, **k):
        raise AssertionError("must not fetch from arXiv")

    monkeypatch.setattr(ingestion, "ingest_arxiv", no_download)
    assert ingestion.ingest("2312.00752").title == "My Revision"
    assert source_identity("2312.00752").startswith("path:")
    assert source_identity("2401.00001").startswith("arxiv:")  # no such folder here
