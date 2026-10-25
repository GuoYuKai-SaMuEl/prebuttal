import json

import pytest
from conftest import PersonaFakeProvider

from prebuttal import cli
from prebuttal.providers import register_backend
from prebuttal.providers.detect import BackendStatus

FAKE_TOML = """
[default]
venue = "iclr"
seed = 7

[[reviewer]]
id = "R1"
persona = "senior_kind"
backend = "fake"

[[reviewer]]
id = "R2"
persona = "adversarial"
backend = "fake"

[[reviewer]]
id = "R3"
persona = "detail_obsessive"
backend = "fake"

[ac]
backend = "fake"
"""


@pytest.fixture(autouse=True)
def register_fake_backend():
    register_backend(
        "fake", lambda model, cfg, timeout_s: PersonaFakeProvider(model=model or "fake-m")
    )
    yield


@pytest.fixture
def fake_statuses(monkeypatch):
    statuses = [
        BackendStatus("agent-claude", "agent", True, "claude CLI"),
        BackendStatus("agent-codex", "agent", False, "not found"),
        BackendStatus("api-gemini", "api", False, "no key"),
        BackendStatus("api-openai", "api", False, "no key"),
        BackendStatus("api-anthropic", "api", False, "no key"),
        BackendStatus("ollama", "ollama", False, "down"),
    ]
    monkeypatch.setattr(cli, "scan_backends", lambda cfg=None: statuses)
    return statuses


def test_run_end_to_end_with_fake_backend(tmp_path, monkeypatch, latex_project, fake_statuses):
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / "prebuttal.toml"
    cfg_path.write_text(FAKE_TOML, encoding="utf-8")

    rc = cli.main(
        [
            "run",
            str(latex_project),
            "--config",
            str(cfg_path),
            "--json",
            "out.json",
            "--share",
            "--out",
            "report.md",
        ]
    )
    assert rc == cli.EXIT_OK

    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Predicted outcome" in md
    assert "Meta-review" in md

    data = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert data["aggregate"]["mean"] == 6.0
    assert data["run"]["seed"] == 7

    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "pipx install prebuttal" in html


def test_run_creates_missing_output_dirs(tmp_path, monkeypatch, latex_project, fake_statuses):
    """A finished (possibly paid) review must not die on a not-yet-existing --out dir."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PREBUTTAL_HOME", str(tmp_path / "home"))
    cfg_path = tmp_path / "prebuttal.toml"
    cfg_path.write_text(FAKE_TOML, encoding="utf-8")
    rc = cli.main(
        [
            "run",
            str(latex_project),
            "--config",
            str(cfg_path),
            "--share",
            "--out",
            "new/dir/report.md",
            "--json",
            "other/out.json",
        ]
    )
    assert rc == cli.EXIT_OK
    assert (tmp_path / "new/dir/report.md").is_file()
    assert (tmp_path / "new/dir/report.html").is_file()
    assert (tmp_path / "other/out.json").is_file()


def test_run_dry_run_prints_matrix_no_calls(
    tmp_path, monkeypatch, latex_project, fake_statuses, shared_calls
):
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / "prebuttal.toml"
    cfg_path.write_text(FAKE_TOML, encoding="utf-8")

    # dry run must not build providers — replace build with a tripwire
    def tripwire(*a, **k):
        raise AssertionError("dry run must not build providers")

    monkeypatch.setattr(cli, "build_provider", tripwire)

    rc = cli.main(["run", str(latex_project), "--config", str(cfg_path), "--dry-run"])
    assert rc == cli.EXIT_OK
    assert shared_calls == []


def test_run_no_backend(tmp_path, monkeypatch, latex_project):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "scan_backends", lambda cfg=None: [])
    rc = cli.main(["run", str(latex_project)])
    assert rc == cli.EXIT_NO_BACKEND


def test_backends_command(tmp_path, monkeypatch, capsys, fake_statuses):
    rc = cli.main(["backends"])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "agent-claude" in out
    # relay is listed (explicit use) but auto mode must not claim it
    assert "Auto mode will draw from: agent-claude\n" in out


def _dry_run(tmp_path, latex_project, *extra):
    cfg_path = tmp_path / "prebuttal.toml"
    cfg_path.write_text(FAKE_TOML, encoding="utf-8")
    return cli.main(["run", str(latex_project), "--config", str(cfg_path), "--dry-run", *extra])


def test_env_backend_applies_to_all_roles(
    tmp_path, monkeypatch, capsys, latex_project, fake_statuses
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PREBUTTAL_BACKEND", "relay")
    assert _dry_run(tmp_path, latex_project) == cli.EXIT_OK
    out, err = capsys.readouterr()
    assert out.count("→ relay") == 4  # R1-R3 + AC override the toml's "fake"
    assert "PREBUTTAL_BACKEND" in err  # the override is announced, not silent


def test_backend_flag_beats_env(tmp_path, monkeypatch, capsys, latex_project, fake_statuses):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PREBUTTAL_BACKEND", "relay")
    assert _dry_run(tmp_path, latex_project, "--backend", "fake") == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "→ relay" not in out
    assert out.count("→ fake") == 4


def test_empty_env_backend_is_ignored(tmp_path, monkeypatch, capsys, latex_project, fake_statuses):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PREBUTTAL_BACKEND", "  ")
    assert _dry_run(tmp_path, latex_project) == cli.EXIT_OK
    assert capsys.readouterr().out.count("→ fake") == 4


def test_relay_hint_inside_coding_agent(
    tmp_path, monkeypatch, capsys, latex_project, fake_statuses
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")
    assert _dry_run(tmp_path, latex_project) == cli.EXIT_OK
    err = capsys.readouterr().err
    assert "hint: running inside Claude Code" in err
    assert "--backend relay" in err


def test_no_relay_hint_outside_agent_or_when_relay_used(
    tmp_path, monkeypatch, capsys, latex_project, fake_statuses
):
    monkeypatch.chdir(tmp_path)
    assert _dry_run(tmp_path, latex_project) == cli.EXIT_OK
    assert "hint:" not in capsys.readouterr().err

    monkeypatch.setenv("CLAUDECODE", "1")
    assert _dry_run(tmp_path, latex_project, "--backend", "relay") == cli.EXIT_OK
    assert "hint:" not in capsys.readouterr().err  # already in relay mode


def test_backends_command_relay_hint_inside_agent(monkeypatch, capsys, fake_statuses):
    monkeypatch.setenv("GEMINI_CLI", "1")
    assert cli.main(["backends"]) == cli.EXIT_OK
    assert "Hint: running inside Gemini CLI" in capsys.readouterr().out


def test_backends_command_only_relay(monkeypatch, capsys):
    from prebuttal.providers.detect import BackendStatus

    statuses = [BackendStatus("relay", "relay", True, "file bridge")]
    monkeypatch.setattr(cli, "scan_backends", lambda cfg=None: statuses)
    rc = cli.main(["backends"])
    assert rc == cli.EXIT_NO_BACKEND
    assert "--backend relay" in capsys.readouterr().out


def test_backends_command_none_available(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "scan_backends", lambda cfg=None: [])
    rc = cli.main(["backends"])
    assert rc == cli.EXIT_NO_BACKEND
    assert "GEMINI_API_KEY" in capsys.readouterr().out


def test_init(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == cli.EXIT_OK
    assert (tmp_path / "prebuttal.toml").read_text(encoding="utf-8").startswith("# Prebuttal")
    # refuses to overwrite
    assert cli.main(["init"]) == cli.EXIT_USAGE
    assert cli.main(["init", "--force"]) == cli.EXIT_OK


def test_ingest_error_exit_code(tmp_path, monkeypatch, fake_statuses):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["run", str(tmp_path / "no-such-paper.pdf")])
    assert rc == cli.EXIT_USAGE


def test_reports_do_not_leak_absolute_paths(tmp_path_factory, monkeypatch, latex_project):
    from pathlib import Path

    from prebuttal.ingestion import display_path, ingest

    monkeypatch.chdir(latex_project.parent)
    paper = ingest(str(latex_project.resolve()))
    assert paper.source_path == latex_project.name  # relative to cwd
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: latex_project.parent))
    monkeypatch.chdir(tmp_path_factory.mktemp("unrelated-cwd"))
    assert display_path(latex_project) == f"~/{latex_project.name}"
    elsewhere = tmp_path_factory.mktemp("unrelated-home")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: elsewhere))
    assert display_path(latex_project) == latex_project.name
