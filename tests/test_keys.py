from prebuttal import cli
from prebuttal.keys import (
    apply_stored_keys,
    keys_path,
    mask,
    resolve_name,
    source,
    store_key,
    unset_key,
)


def test_store_load_roundtrip(isolated_prebuttal_home, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store_key("GEMINI_API_KEY", "AIzaSyTest1234567890")
    assert keys_path().is_file()
    assert keys_path().read_text(encoding="utf-8").count("AIzaSyTest1234567890") == 1
    applied = apply_stored_keys()
    assert applied == ["GEMINI_API_KEY"]
    import os

    assert os.environ["GEMINI_API_KEY"] == "AIzaSyTest1234567890"
    assert mask("GEMINI_API_KEY") == "AIz…90"
    # loaded from the store this process, so labeled honestly (not "env")
    assert source("GEMINI_API_KEY") == "stored, loaded this run"


def test_env_var_takes_precedence(isolated_prebuttal_home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env-123456")
    store_key("OPENAI_API_KEY", "sk-stored-should-be-ignored")
    applied = apply_stored_keys()
    assert applied == []  # env already set, stored key not applied
    import os

    assert os.environ["OPENAI_API_KEY"] == "sk-from-env-123456"


def test_unset(isolated_prebuttal_home, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store_key("ANTHROPIC_API_KEY", "sk-ant-test-123456")
    assert unset_key("ANTHROPIC_API_KEY") is True
    assert apply_stored_keys() == []
    assert unset_key("ANTHROPIC_API_KEY") is False


def test_resolve_name_friendly_and_env(isolated_prebuttal_home):
    assert resolve_name("gemini") == "GEMINI_API_KEY"
    assert resolve_name("OpenAI") == "OPENAI_API_KEY"
    assert resolve_name("GEMINI_API_KEY") == "GEMINI_API_KEY"
    try:
        resolve_name("groq")
        raise AssertionError("should raise")
    except Exception as e:
        assert "groq" in str(e)


def test_cli_key_flow(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    rc = cli.main(["key", "set", "gemini", "--key", "AIzaSyCli9876543210"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "stored GEMINI_API_KEY" in out
    # key material never echoed back
    assert "AIzaSyCli9876543210" not in out

    rc = cli.main(["key", "status"])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "gemini" in out and "AIz…10" in out
    assert "openai" in out and "not set" in out

    # stored key feeds backend detection on a fresh invocation
    rc = cli.main(["backends"])
    out = capsys.readouterr().out
    assert rc in (cli.EXIT_OK, cli.EXIT_NO_BACKEND)
    assert "api-gemini" in out and "[x]" in out

    rc = cli.main(["key", "unset", "gemini"])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK and "removed GEMINI_API_KEY" in out
    assert not keys_path().exists()


def test_cli_key_rejects_unknown(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["key", "set", "groq", "--key", "x"])
    assert rc == cli.EXIT_USAGE
    assert "unknown key" in capsys.readouterr().err
