"""User-defined venues: TOML file + form text, found by name or path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FAKE_TOML, latest_report

from prebuttal import cli
from prebuttal.config import ConfigError, apply_overrides, load_config
from prebuttal.report import report_from_dict
from prebuttal.share import render_share_html
from prebuttal.venues import VENUES, VenueError, get_venue, venue_from_report
from prebuttal.venues.custom import load_venue_file, render_template, venue_to_spec

LAB_TOML = """
name = "Lab Review"
form = "lab.md"
rating = "overall"
confidence = "confidence"

[[fields]]
key = "summary"
label = "Summary"
kind = "text"

[[fields]]
key = "weaknesses"
label = "Weaknesses"
kind = "list"

[[fields]]
key = "ethics"
label = "Ethics concerns"
kind = "text"
required = false

[[fields]]
key = "overall"
label = "Overall"
kind = "score"
max = 7
half_steps = true
anchors = { "1" = "Reject", "4" = "Borderline", "7" = "Strong accept" }

[[fields]]
key = "confidence"
label = "Confidence"
kind = "score"
max = 3
"""


def _write(folder: Path, key: str = "lab", toml: str = LAB_TOML, form: str = "# Lab form\n"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{key}.toml").write_text(toml.replace("lab.md", f"{key}.md"), encoding="utf-8")
    (folder / f"{key}.md").write_text(form, encoding="utf-8")
    return folder / f"{key}.toml"


def test_load_custom_venue(tmp_path):
    v = load_venue_file(_write(tmp_path))
    assert v.key == "lab" and v.name == "Lab Review" and v.custom
    assert v.rating_field.max == 7 and v.rating_field.allow_float
    assert v.rating_field.anchor_for(4.5) == "Borderline"
    assert v.field("ethics").required is False
    assert v.form_text() == "# Lab form\n"
    assert '"overall": number  // Overall, scale 1 to 7 (integers or half-steps)' in v.json_spec()


def test_found_by_name_project_dir_first(tmp_path, monkeypatch, isolated_prebuttal_home):
    monkeypatch.chdir(tmp_path)
    _write(isolated_prebuttal_home / "venues", form="# personal\n")
    with pytest.raises(VenueError, match="unknown venue 'nope'"):
        get_venue("nope")
    assert get_venue("lab").form_text() == "# personal\n"
    _write(tmp_path / ".prebuttal" / "venues", form="# project\n")
    assert get_venue("LAB").form_text() == "# project\n"


def test_venue_by_path(tmp_path):
    path = _write(tmp_path / "forms")
    assert get_venue(str(path)).key == "lab"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda t: t.replace('name = "Lab Review"', ""), "missing name"),
        (lambda t: t.replace('rating = "overall"', 'rating = "summary"'), "must name a score"),
        (lambda t: t.replace("max = 7", "max = 1"), "max must be a whole number"),
        (lambda t: t.replace('"7" = "Strong', '"9" = "Strong'), "anchor 9 is outside 1-7"),
        (lambda t: t.replace('kind = "list"', 'kind = "bullets"'), "kind must be one of"),
        (lambda t: t.replace("required = false", "requird = false"), "unknown setting"),
        (lambda t: t.replace('key = "ethics"', 'key = "summary"'), "used twice"),
        (lambda t: t.replace('form = "lab.md"', ""), "no review form"),
        (lambda t: t.replace('form = "lab.md"', 'form = "../secret.txt"'), "same folder"),
        (lambda t: t + "\n[[fields]]\nkey = ", "cannot read venue file"),
    ],
)
def test_invalid_files_say_what_is_wrong(tmp_path, change, message):
    path = _write(tmp_path, toml=change(LAB_TOML))
    with pytest.raises(VenueError, match=message) as e:
        load_venue_file(path)
    assert str(path) in str(e.value)  # every error names the file


def test_builtin_names_cannot_be_shadowed(tmp_path):
    with pytest.raises(VenueError, match="built-in venue"):
        load_venue_file(_write(tmp_path, key="iclr"))


@pytest.mark.parametrize("base", list(VENUES))
def test_template_from_builtin_round_trips(tmp_path, base):
    toml, form = render_template(f"{base}-copy", VENUES[base])
    (tmp_path / f"{base}-copy.toml").write_text(toml, encoding="utf-8")
    (tmp_path / f"{base}-copy.md").write_text(form, encoding="utf-8")
    copy = load_venue_file(tmp_path / f"{base}-copy.toml")
    assert venue_to_spec(copy)["fields"] == venue_to_spec(VENUES[base])["fields"]
    assert copy.form_text() == VENUES[base].form_text()


def test_blank_template_is_valid(tmp_path):
    toml, form = render_template("cvpr")
    (tmp_path / "cvpr.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "cvpr.md").write_text(form, encoding="utf-8")
    assert load_venue_file(tmp_path / "cvpr.toml").rating_field.max == 10


def test_config_venue_path_is_relative_to_config(tmp_path, monkeypatch):
    _write(tmp_path / "forms")
    cfg_path = tmp_path / "prebuttal.toml"
    cfg_path.write_text('[default]\nvenue = "forms/lab.toml"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path.parent)
    cfg = load_config(str(cfg_path))
    assert get_venue(cfg.venue).key == "lab"
    with pytest.raises(ConfigError, match="unknown venue 'cvpr'"):
        apply_overrides(cfg, venue="cvpr")


def test_cli_new_list_show(tmp_path, monkeypatch, capsys, isolated_prebuttal_home):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["venues", "new", "cvpr"]) == 0
    assert (isolated_prebuttal_home / "venues" / "cvpr.toml").is_file()
    assert cli.main(["venues", "new", "icml-2027", "--from", "icml", "--here"]) == 0
    assert (tmp_path / ".prebuttal" / "venues" / "icml-2027.md").is_file()
    assert cli.main(["venues", "new", "icml"]) == cli.EXIT_USAGE  # built in
    assert cli.main(["venues", "new", "cvpr"]) == cli.EXIT_USAGE  # exists
    (isolated_prebuttal_home / "venues" / "broken.toml").write_text("name = 1\n", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["venues"]) == 0
    out = capsys.readouterr().out
    assert "icml-2027" in out and "cvpr" in out and "broken" in out and "INVALID" in out
    assert cli.main(["venues", "show", "icml-2027"]) == 0
    assert "Marginally above publication threshold" in capsys.readouterr().out


def test_run_with_custom_venue_and_render_after_file_is_gone(
    tmp_path, monkeypatch, latex_project, fake_statuses
):
    monkeypatch.chdir(tmp_path)
    toml = (
        LAB_TOML.replace('rating = "overall"', 'rating = "rating"')
        .replace('key = "overall"', 'key = "rating"')
        .replace("max = 7", "max = 10")
        .replace('"7" = "Strong', '"10" = "Strong')
    )
    venue_file = _write(tmp_path / "forms", toml=toml, form="# Lab form: be fair.\n")
    cfg_path = tmp_path / "prebuttal.toml"
    cfg_path.write_text(FAKE_TOML, encoding="utf-8")
    rc = cli.main(
        ["run", str(latex_project), "--config", str(cfg_path), "--venue", str(venue_file),
         "--json", "out.json", "--out-dir", "reports"]
    )  # fmt: skip
    assert rc == cli.EXIT_OK
    data = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert data["venue"]["key"] == "lab" and data["venue"]["custom"] is True
    assert data["venue"]["definition"]["fields"][-2]["max"] == 10
    assert data["aggregate"]["mean"] == 6.0
    assert "Lab Review" in latest_report(tmp_path / "reports").read_text(encoding="utf-8")

    venue_file.unlink()  # the archived report must still render
    venue = venue_from_report(data)
    html = render_share_html(report_from_dict(data), venue, "https://x")
    assert "Lab Review" in html
