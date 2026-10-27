import json
import sys
from pathlib import Path

import pytest
from conftest import latest_report, make_report

from prebuttal import cli
from prebuttal.config import load_config
from prebuttal.report import dumps_json
from prebuttal.runs import (
    find_run,
    history_path,
    load_history,
    project_summaries,
    render_diff,
    render_projects_table,
    render_runs_table,
    save_run,
)


def _archive(latex_project, *, rating_shift: int = 0):
    report, venue = make_report(latex_project, rating_shift=rating_shift)
    cfg = load_config(None)
    rec = save_run(
        report,
        venue,
        cfg,
        md=f"# Prebuttal Report — run {rating_shift}",
        json_str=dumps_json(report, venue),
        html=None,
    )
    return report, rec


def test_save_and_history_roundtrip(latex_project):
    report, rec = _archive(latex_project)
    assert rec.mean == report.aggregate.mean
    for name in ("report.md", "report.json", "resolved-config.json"):
        assert (rec.dir_path / name).is_file(), name
    hist = load_history()
    assert len(hist) == 1
    assert hist[0].id == rec.id
    assert "run 0" in hist[0].paper_title or hist[0].paper_title == report.paper.title
    table = render_runs_table(hist)
    assert report.paper.title[:20] in table


def test_ids_unique_within_the_same_second(latex_project):
    _a1, r1 = _archive(latex_project)
    _a2, r2 = _archive(latex_project)
    assert r1.id != r2.id


def test_find_run_prefix_and_miss(latex_project):
    _a, rec = _archive(latex_project)
    match, cands = find_run(rec.id[:14])
    assert match is not None and match.id == rec.id and cands == []
    match2, cands2 = find_run("definitely-not-a-run")
    assert match2 is None and cands2 == []


def test_render_diff_ratings_and_weakness_movement(latex_project):
    report_a, rec_a = _archive(latex_project)
    # revise: ratings improve, one weakness fixed, one new appears
    for rev in report_a.reviews:
        rev.fields["weaknesses"] = [
            "Baseline set is thin — no comparison against Perceiver (Table 1).",
            "No standard deviations are reported in Table 1.",
        ]
    report_b, rec_b = _archive(latex_project, rating_shift=2)
    for rev in report_b.reviews:
        rev.fields["weaknesses"] = [
            "Baseline set is thin — no comparison against Perceiver (Table 1).",
            "New flaw: evaluation only on LongBench.",
        ]

    # re-save with the edited weakness lists (save_run snapshot happens above,
    # so patch the archived JSON directly)
    def patch(rec, report):
        data = json.loads((Path(rec.dir) / "report.json").read_text(encoding="utf-8"))
        for stored, rev in zip(data["reviewers"], report.reviews, strict=True):
            stored["fields"]["weaknesses"] = rev.fields["weaknesses"]
        (Path(rec.dir) / "report.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

    patch(rec_a, report_a)
    patch(rec_b, report_b)

    text = render_diff(rec_a, rec_b)
    assert "Revision diff" in text
    assert "Δ +2" in text  # aggregate improved by the shift
    assert "persists:" in text  # Perceiver weakness survives
    assert "gone:" in text  # std reporting weakness fixed
    assert "new:" in text  # LongBench-only flaw appeared
    assert "Heuristic comparison" in text  # honesty label


def test_cli_full_flow_run_runs_show_diff(
    tmp_path, monkeypatch, latex_project, fake_statuses, fake_config, capsys
):
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "prebuttal-home"

    rc = cli.main(["run", str(latex_project), "--config", str(fake_config), "--out-dir", "r1"])
    assert rc == cli.EXIT_OK
    rc = cli.main(["run", str(latex_project), "--config", str(fake_config), "--out-dir", "r2"])
    assert rc == cli.EXIT_OK
    hist = load_history()
    assert len(hist) == 2
    assert (home / "runs").is_dir()

    out = capsys.readouterr().out
    assert "Saved:" in out  # basic run reports the archive id

    rc = cli.main(["runs"])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert hist[0].label in out and hist[1].label in out
    assert hist[0].label.endswith("#2") and hist[1].label.endswith("#1")

    rc = cli.main(["runs", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == cli.EXIT_OK and len(data) == 2 and data[0]["venue"] == "iclr"

    rc = cli.main(["show", hist[1].id[:19], "--json"])  # prefix incl. uuid slice
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert json.loads(out)["aggregate"]["mean"] is not None

    rc = cli.main(["diff", hist[0].id, hist[1].id])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK and "Revision diff" in out

    # --no-save leaves the archive untouched
    rc = cli.main(
        ["run", str(latex_project), "--config", str(fake_config), "--out-dir", "r3", "--no-save"]
    )
    assert rc == cli.EXIT_OK
    assert len(load_history()) == 2


def test_cli_show_unknown_run(tmp_path, monkeypatch, fake_statuses, capsys):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["show", "nope"])
    assert rc == cli.EXIT_USAGE
    assert "no unique run matches" in capsys.readouterr().err


def test_archive_failure_never_breaks_the_run(
    tmp_path, monkeypatch, latex_project, fake_statuses, fake_config, capsys
):
    monkeypatch.chdir(tmp_path)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(cli, "save_run", boom)
    rc = cli.main(["run", str(latex_project), "--config", str(fake_config), "--out-dir", "r"])
    assert rc == cli.EXIT_OK  # the review itself succeeded
    assert "could not archive" in capsys.readouterr().err
    assert latest_report(tmp_path / "r").is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_store_is_private_to_the_user(tmp_path, monkeypatch):
    """Archived runs hold unpublished paper text: no other account may read them."""
    import stat

    from prebuttal.runs import make_private_dir

    home = tmp_path / "home"
    home.mkdir(mode=0o755)
    make_private_dir(home)
    assert stat.S_IMODE(home.stat().st_mode) == 0o700


def test_scale_backfill_for_pre_020_records(latex_project):
    cfg = load_config(None)
    report, venue = make_report(latex_project, venue_key="iclr")
    rec1 = save_run(report, venue, cfg, md="# r1", json_str=dumps_json(report, venue), html=None)
    report2, venue2 = make_report(latex_project, venue_key="neurips", rating_shift=1)
    rec2 = save_run(
        report2, venue2, cfg, md="# r2", json_str=dumps_json(report2, venue2), html=None
    )

    # strip scale to simulate records written before 0.2.0
    lines = history_path().read_text(encoding="utf-8").splitlines()
    stripped = [
        json.dumps({k: v for k, v in json.loads(line).items() if k != "scale"}) for line in lines
    ]
    history_path().write_text("\n".join(stripped) + "\n", encoding="utf-8")

    recs = {r.id: r for r in load_history()}
    assert recs[rec1.id].scale == 10  # iclr, back-filled from the venue
    assert recs[rec2.id].scale == 6  # neurips

    text = render_runs_table(list(recs.values()))
    assert "/10" in text and "/6" in text

    # a raw-mean trend across different rating scales must not be shown
    projects = render_projects_table(project_summaries(list(recs.values())))
    row = next(line for line in projects.splitlines() if line.startswith(rec1.project))
    assert " → " not in row


def test_rewriting_history_keeps_unreadable_lines(latex_project):
    from prebuttal.runs import set_note

    _report, rec = _archive(latex_project)
    with history_path().open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
        fh.write("[1, 2]\n")
    assert [r.id for r in load_history()] == [rec.id]  # skipped, not a crash
    set_note(rec.id, "after ablation")
    lines = history_path().read_text(encoding="utf-8").splitlines()
    assert "{not json" in lines and "[1, 2]" in lines
    assert load_history()[0].note == "after ablation"


def test_diff_keeps_reviewers_that_share_a_persona(latex_project):
    _ra, rec_a = _archive(latex_project)
    _rb, rec_b = _archive(latex_project, rating_shift=1)
    for rec in (rec_a, rec_b):
        p = Path(rec.dir) / "report.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        for r in data["reviewers"]:
            r["persona"] = "adversarial"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    text = render_diff(rec_a, rec_b)
    for key in ("- adversarial:", "- adversarial #2:", "- adversarial #3:"):
        assert key in text
