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
    provider = AgentCLIProvider("agent-x", [cli_path, "-p"])
    comp = provider.complete(system="s", user="u", retries=0)
    assert calls == [[cli_path, "-p"], ["cmd", "/c", cli_path, "-p"]]
    assert comp.text == "ok"
