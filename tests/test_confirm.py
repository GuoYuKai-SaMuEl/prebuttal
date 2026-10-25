"""Plan-confirmation flow: auto+TTY prompts, -y skips, non-TTY proceeds."""

import json

from conftest import latest_report

from prebuttal import cli
from prebuttal.providers.detect import BackendStatus
from prebuttal.runs import load_history

AUTO_TOML = """
[default]
venue = "iclr"
seed = 7

[[reviewer]]
id = "R1"
persona = "senior_kind"
backend = "auto"

[[reviewer]]
id = "R2"
persona = "adversarial"
backend = "auto"

[[reviewer]]
id = "R3"
persona = "detail_obsessive"
backend = "auto"

[ac]
backend = "auto"
"""


def _auto_statuses(monkeypatch):
    """Only the (safe, in-process) fake backend is an auto candidate."""
    statuses = [
        BackendStatus("agent-claude", "agent", False, "not found"),
        BackendStatus("agent-codex", "agent", False, "not found"),
        BackendStatus("api-gemini", "api", False, "no key"),
        BackendStatus("api-openai", "api", False, "no key"),
        BackendStatus("api-anthropic", "api", False, "no key"),
        BackendStatus("ollama", "ollama", False, "down"),
        BackendStatus("fake", "api", True, "in-process test backend", "fake-m"),
        BackendStatus("relay", "relay", True, "explicit only"),
    ]
    monkeypatch.setattr(cli, "scan_backends", lambda cfg=None: statuses)
    return statuses


def _config(tmp_path, toml=AUTO_TOML):
    p = tmp_path / "auto.toml"
    p.write_text(toml, encoding="utf-8")
    return p


def test_dry_run_plan_shows_personas(tmp_path, monkeypatch, latex_project, capsys):
    monkeypatch.chdir(tmp_path)
    _auto_statuses(monkeypatch)
    rc = cli.main(["run", str(latex_project), "--config", str(_config(tmp_path)), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "senior_kind" in out and "adversarial" in out and "area_chair" in out


def test_non_tty_auto_proceeds_with_notice(tmp_path, monkeypatch, latex_project, capsys):
    monkeypatch.chdir(tmp_path)
    _auto_statuses(monkeypatch)
    rc = cli.main(["run", str(latex_project), "--config", str(_config(tmp_path)), "--out-dir", "r"])
    err = capsys.readouterr().err
    assert rc == cli.EXIT_OK
    assert "non-interactive" in err  # plan was announced, then it ran anyway
    assert latest_report(tmp_path / "r").is_file()


def test_yes_flag_silences_notice(tmp_path, monkeypatch, latex_project, capsys):
    monkeypatch.chdir(tmp_path)
    _auto_statuses(monkeypatch)
    rc = cli.main(
        ["run", str(latex_project), "--config", str(_config(tmp_path)), "--out-dir", "r", "-y"]
    )
    captured = capsys.readouterr()
    assert rc == cli.EXIT_OK
    assert "non-interactive" not in captured.err
    assert latest_report(tmp_path / "r").is_file()


def test_explicit_config_never_prompts_or_notices(
    tmp_path, monkeypatch, latex_project, fake_statuses, fake_config, capsys
):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["run", str(latex_project), "--config", str(fake_config), "--out-dir", "r"])
    err = capsys.readouterr().err
    assert rc == cli.EXIT_OK
    assert "non-interactive" not in err  # explicit config = nothing ambiguous


def test_interactive_abort_before_any_calls(tmp_path, monkeypatch, latex_project, capsys):
    monkeypatch.chdir(tmp_path)
    _auto_statuses(monkeypatch)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    def tripwire(*a, **k):
        raise AssertionError("abort must happen before providers are built")

    monkeypatch.setattr(cli, "build_provider", tripwire)
    rc = cli.main(["run", str(latex_project), "--config", str(_config(tmp_path))])
    assert rc == cli.EXIT_USAGE
    assert not (tmp_path / "prebuttal-report.md").exists()


def test_interactive_edit_then_run(tmp_path, monkeypatch, latex_project, capsys):
    monkeypatch.chdir(tmp_path)
    _auto_statuses(monkeypatch)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    # confirm: e(dit) → per reviewer: persona, backend, model (each now always
    # asks, with "(type a custom model id)" as the last model option) → run
    answers = iter(
        [
            "e",  # confirm → edit
            "",
            "2",
            "",  # R1: persona keep, backend → fake, model default
            "",
            "",
            "",  # R2: keep defaults
            "",
            "",
            "",  # R3: keep defaults
            "",
            "",  # AC: backend, model
            "",  # confirm → run
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    rc = cli.main(["run", str(latex_project), "--config", str(_config(tmp_path)), "--out-dir", "r"])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "== R1" in out and "== AC" in out  # the wizard ran
    assert latest_report(tmp_path / "r").is_file()

    # the edited choice is what actually reviewed the paper
    rec = load_history()[0]
    resolved = json.loads((rec.dir_path / "resolved-config.json").read_text(encoding="utf-8"))
    assert resolved["reviewers"][0]["backend"] == "fake"
    assert all(r["backend"] == "fake" for r in resolved["reviewers"])
