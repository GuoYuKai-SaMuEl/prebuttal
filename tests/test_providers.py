import json

import pytest

from prebuttal.config import load_config
from prebuttal.providers import scan_backends
from prebuttal.providers.detect import (
    BackendStatus,
    NoBackendError,
    resolve_backends,
)


def test_scan_reports_all_candidates(monkeypatch):
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name == "claude" else None
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    import prebuttal.providers.detect as det

    monkeypatch.setattr(det, "ollama_models", lambda base: [])

    cfg = load_config(None)
    statuses = scan_backends(cfg)
    by_name = {s.backend: s.available for s in statuses}
    assert by_name["agent-claude"] is True
    assert by_name["agent-codex"] is False
    assert by_name["api-openai"] is True
    assert by_name["api-gemini"] is False
    assert by_name["ollama"] is False


def test_auto_prefers_cross_model_agents(monkeypatch):
    cfg = load_config(None)
    statuses = [
        BackendStatus("agent-claude", "agent", True, ""),
        BackendStatus("agent-codex", "agent", True, ""),
        BackendStatus("api-gemini", "api", True, "", "gemini-2.5-flash"),
        BackendStatus("api-openai", "api", False, ""),
    ]
    resolved, ac = resolve_backends(cfg, statuses)
    backends = [b for (_r, b, _m) in resolved]
    assert backends == ["agent-claude", "agent-codex", "api-gemini"]
    assert resolved[2][2] == "gemini-2.5-flash"  # model default filled in
    assert ac[0] == "agent-claude"


def test_auto_cycles_when_only_one_backend():
    cfg = load_config(None)
    statuses = [BackendStatus("ollama", "ollama", True, "", "llama3.1")]
    resolved, ac = resolve_backends(cfg, statuses)
    assert [b for (_r, b, _m) in resolved] == ["ollama"] * 3
    assert ac == ("ollama", "llama3.1")  # ollama default model filled in


def test_auto_never_picks_relay():
    """Regression: with only claude installed, R2 used to land on relay and block."""
    cfg = load_config(None)
    statuses = [
        BackendStatus("agent-claude", "agent", True, ""),
        BackendStatus("relay", "relay", True, ""),
    ]
    resolved, ac = resolve_backends(cfg, statuses)
    assert [b for (_r, b, _m) in resolved] == ["agent-claude"] * 3
    assert ac[0] == "agent-claude"


def test_only_relay_available_is_no_backend():
    """Relay alone must not silently satisfy auto mode — exit 3 with guidance."""
    cfg = load_config(None)
    with pytest.raises(NoBackendError) as exc:
        resolve_backends(cfg, [BackendStatus("relay", "relay", True, "")])
    assert "--backend relay" in str(exc.value)


def test_explicit_relay_needs_no_auto_candidate():
    cfg = load_config(None)
    for r in cfg.reviewers:
        r.backend = "relay"
    cfg.ac.backend = "relay"
    resolved, ac = resolve_backends(cfg, [BackendStatus("relay", "relay", True, "")])
    assert [b for (_r, b, _m) in resolved] == ["relay"] * 3
    assert ac[0] == "relay"


def test_detect_host_agent(monkeypatch):
    from prebuttal.providers.detect import detect_host_agent

    assert detect_host_agent() is None
    monkeypatch.setenv("CLAUDECODE", "0")  # explicitly off
    assert detect_host_agent() is None
    monkeypatch.setenv("CLAUDECODE", "1")
    assert detect_host_agent() == "Claude Code"


def test_no_backend_raises_with_guidance(monkeypatch):
    cfg = load_config(None)
    monkeypatch.setattr("prebuttal.providers.detect.scan_backends", lambda c: [])
    from prebuttal.providers.detect import resolve_backends as rb

    with pytest.raises(NoBackendError) as exc:
        rb(cfg, [])
    assert "GEMINI_API_KEY" in str(exc.value)


def test_explicit_backends_pass_through(monkeypatch):
    cfg = load_config(None)
    for r in cfg.reviewers:
        r.backend = "agent-claude"
        r.model = "my-model"
    statuses = [BackendStatus("ollama", "ollama", True, "", "llama3.1")]
    resolved, _ac = resolve_backends(cfg, statuses)
    assert all(b == "agent-claude" and m == "my-model" for (_r, b, m) in resolved)


# ------------------------------------------------------------- API provider


def _install_mock_http(monkeypatch, handler):
    """Route provider HTTP through an httpx.MockTransport; returns call list."""
    import httpx

    import prebuttal.providers.api as api_mod

    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    class MockClient(httpx.Client):
        def __init__(self, **kw):
            kw.pop("timeout", None)
            super().__init__(transport=httpx.MockTransport(wrapped), timeout=30)

    monkeypatch.setattr(api_mod.httpx, "Client", MockClient)
    return calls


def test_gemini_provider_request_shape(monkeypatch):
    import httpx

    from prebuttal.providers.api import GeminiProvider

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": '{"rating": 6}'}]}}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
            },
        )

    calls = _install_mock_http(monkeypatch, handler)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    provider = GeminiProvider(model="gemini-2.5-flash")
    comp = provider.complete(
        system="SYS", user="USR", temperature=0.7, seed=123, max_tokens=1000, retries=0
    )
    assert comp.text == '{"rating": 6}'
    assert comp.usage.prompt_tokens == 10
    assert captured["generationConfig"]["seed"] == 123
    assert captured["generationConfig"]["temperature"] == 0.7
    assert captured["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert "gemini-2.5-flash:generateContent" in str(calls[0].url)


def test_openai_provider_request_shape(monkeypatch):
    import httpx

    from prebuttal.providers.api import OpenAIProvider

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"rating": 7}'}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 6},
            },
        )

    _install_mock_http(monkeypatch, handler)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.example/v1")

    provider = OpenAIProvider(model="gpt-4.1-mini")
    comp = provider.complete(
        system="S", user="U", temperature=0.5, seed=9, max_tokens=800, retries=0
    )
    assert comp.text == '{"rating": 7}'
    assert comp.usage.prompt_tokens == 11 and comp.usage.completion_tokens == 6
    assert captured["url"] == "https://proxy.example/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-test"
    body = captured["json"]
    assert body["seed"] == 9 and body["temperature"] == 0.5
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0] == {"role": "system", "content": "S"}
    assert body["messages"][1] == {"role": "user", "content": "U"}


def test_anthropic_provider_request_shape(monkeypatch):
    import httpx

    from prebuttal.providers.api import AnthropicProvider

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key"] = request.headers.get("x-api-key")
        captured["version"] = request.headers.get("anthropic-version")
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": '{"a": 1}'}],
                "usage": {"input_tokens": 7, "output_tokens": 3},
            },
        )

    _install_mock_http(monkeypatch, handler)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-test")

    provider = AnthropicProvider(model="claude-sonnet-4-5")
    comp = provider.complete(
        system="S", user="U", temperature=0.3, seed=5, max_tokens=900, retries=0
    )
    assert comp.text == '{"a": 1}'
    assert comp.usage.prompt_tokens == 7 and comp.usage.completion_tokens == 3
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["key"] == "ak-test"
    assert captured["version"] == "2023-06-01"
    body = captured["json"]
    assert body["system"] == "S"
    assert body["messages"] == [{"role": "user", "content": "U"}]
    assert body["temperature"] == 0.3
    assert "seed" not in body  # Anthropic has no seed parameter — recorded, not sent


def test_agent_cli_prompt_on_stdin(monkeypatch):
    import subprocess as sp

    from prebuttal.providers.agent_cli import AgentCLIProvider

    recorded = {}

    class FakeCompleted:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    def fake_run(cmd, input=None, **kw):
        recorded["cmd"] = cmd
        recorded["input"] = input
        return FakeCompleted()

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: None)  # keep the bare name
    provider = AgentCLIProvider("agent-claude", ["claude", "-p"])
    comp = provider.complete(system="SYS", user="USR", retries=0)
    assert recorded["cmd"] == ["claude", "-p"]
    assert "SYS" in recorded["input"] and "USR" in recorded["input"]
    assert comp.text == '{"ok": true}'
    assert not comp.usage.known  # CLI backends report no usage


def test_agent_cli_missing_binary(monkeypatch):
    import subprocess as sp

    from prebuttal.providers.agent_cli import AgentCLIProvider
    from prebuttal.providers.base import ProviderError

    def fake_run(*a, **kw):
        raise FileNotFoundError("nope")

    monkeypatch.setattr(sp, "run", fake_run)
    provider = AgentCLIProvider("agent-x", ["nonexistent-cli", "-p"])
    with pytest.raises(ProviderError) as exc:
        provider.complete(system="s", user="u", retries=0)
    assert "not found" in str(exc.value)


def test_agent_cli_forwards_model_flag(monkeypatch):
    """A per-reviewer `model` must reach the CLI command, not just the report."""
    import subprocess as sp

    from prebuttal.providers.agent_cli import claude_provider, codex_provider

    cmds: list[list[str]] = []

    class FakeCompleted:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(cmd, input=None, **kw):
        cmds.append(list(cmd))
        return FakeCompleted()

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: None)  # keep the bare name
    claude_provider(model="opus").complete(system="s", user="u", retries=0)
    codex_provider(model="gpt-5.1").complete(system="s", user="u", retries=0)
    assert cmds[0] == ["claude", "-p", "--model", "opus"]
    # codex's stdin marker "-" must stay the FINAL argument
    assert cmds[1] == ["codex", "exec", "--skip-git-repo-check", "--model", "gpt-5.1", "-"]


def test_agent_cli_windows_cmd_fallback(monkeypatch):
    """Windows .cmd launchers that CreateProcess can't run directly retry via cmd /c."""
    import subprocess as sp

    from prebuttal.providers.agent_cli import AgentCLIProvider

    calls: list[list[str]] = []

    class FakeCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    cli_path = "C:\\tools\\claude.cmd"

    def fake_run(cmd, input=None, **kw):
        calls.append(list(cmd))
        if cmd[0] == cli_path:
            raise OSError("[WinError 193] %1 is not a valid Win32 application")
        return FakeCompleted()

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: None)  # host-independent
    provider = AgentCLIProvider("agent-x", [cli_path, "-p"])
    comp = provider.complete(system="s", user="u", retries=0)
    assert calls == [[cli_path, "-p"], ["cmd", "/c", cli_path, "-p"]]
    assert comp.text == "ok"


def test_agent_cli_runs_resolved_path(monkeypatch):
    """Regression: Windows npm installs `claude.cmd`; CreateProcess can't find the
    bare name, so the path `shutil.which` detected must be what gets launched."""
    import subprocess as sp

    from prebuttal.providers.agent_cli import claude_provider

    cmds: list[list[str]] = []

    class FakeCompleted:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(cmd, input=None, **kw):
        cmds.append(list(cmd))
        return FakeCompleted()

    resolved = "C:\\Users\\me\\AppData\\Roaming\\npm\\claude.CMD"
    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: resolved if name == "claude" else None)
    claude_provider().complete(system="s", user="u", retries=0)
    assert cmds == [[resolved, "-p"]]


def test_agent_cli_does_not_inherit_stored_keys(monkeypatch, isolated_prebuttal_home):
    """Regression: a key from keys.env leaking into `claude -p` switches it from
    subscription auth to API billing. Keys the user exported themselves stay."""
    import os
    import subprocess as sp

    from prebuttal import keys
    from prebuttal.providers.agent_cli import claude_provider

    # setenv first so monkeypatch restores the real state after apply_stored_keys
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-user-exported")
    monkeypatch.setattr(keys, "_applied", set())
    keys.store_key("ANTHROPIC_API_KEY", "sk-ant-stored-123456")
    keys.store_key("OPENAI_API_KEY", "sk-openai-stored-123456")
    assert keys.apply_stored_keys() == ["ANTHROPIC_API_KEY"]
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-stored-123456"  # API backends still see it

    envs: list[dict] = []

    class FakeCompleted:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(cmd, input=None, env=None, **kw):
        envs.append(env)
        return FakeCompleted()

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: None)
    claude_provider().complete(system="s", user="u", retries=0)
    assert envs[0] is not None
    assert "ANTHROPIC_API_KEY" not in envs[0]
    assert envs[0]["OPENAI_API_KEY"] == "sk-user-exported"
