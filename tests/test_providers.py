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


def test_openrouter_provider_request_shape(monkeypatch):
    import httpx

    from prebuttal.providers.api import OpenRouterProvider

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["referer"] = request.headers.get("HTTP-Referer")
        captured["title"] = request.headers.get("X-Title")
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"rating": 9}'}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 8},
            },
        )

    _install_mock_http(monkeypatch, handler)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    provider = OpenRouterProvider()  # default model is a :free id
    assert provider.model.endswith(":free")
    comp = provider.complete(
        system="S", user="U", temperature=0.6, seed=3, max_tokens=700, retries=0
    )
    assert comp.text == '{"rating": 9}'
    assert comp.usage.prompt_tokens == 20 and comp.usage.completion_tokens == 8
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["auth"] == "Bearer or-test"
    assert captured["referer"] and captured["title"] == "prebuttal"
    body = captured["json"]
    assert body["seed"] == 3 and body["temperature"] == 0.6
    assert "response_format" not in body  # many OpenRouter models reject JSON mode


def test_http_429_marks_slow_backoff(monkeypatch):
    import httpx

    from prebuttal.providers.api import GeminiProvider

    codes = iter([429, 500, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        code = next(codes)
        if code == 200:
            return httpx.Response(
                200,
                json={
                    "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                    "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
                },
            )
        return httpx.Response(code, json={"error": "throttled"})

    _install_mock_http(monkeypatch, handler)
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    sleeps: list[float] = []
    monkeypatch.setattr("prebuttal.providers.base.time.sleep", lambda s: sleeps.append(s))
    provider = GeminiProvider(model="gemini-3.5-flash-lite")
    comp = provider.complete(
        system="S", user="U", temperature=0.4, seed=1, max_tokens=64, retries=2
    )
    assert comp.text == "ok"
    # attempt 0: 429 slow curve 2^0*15=15; attempt 1: 5xx normal curve 2^1*3=6
    assert sleeps == [15.0, 6.0]


def test_openrouter_reasoning_model_burns_budget_no_retry(monkeypatch):
    import httpx

    from prebuttal.providers.api import OpenRouterProvider
    from prebuttal.providers.base import ProviderError

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": None, "reasoning": "thinking..."},
                    }
                ],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 16,
                    "completion_tokens_details": {"reasoning_tokens": 16},
                },
            },
        )

    _install_mock_http(monkeypatch, handler)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    provider = OpenRouterProvider(model="some/reasoner:free")
    with pytest.raises(ProviderError, match="reasoning"):
        provider.complete(system="S", user="U", temperature=0.4, seed=1, max_tokens=16, retries=2)
    assert calls["n"] == 1  # deterministic failure: retrying would waste free quota


def test_openrouter_content_parts_are_joined(monkeypatch):
    import httpx

    from prebuttal.providers.api import OpenRouterProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": [
                                {"type": "text", "text": '{"rating": '},
                                {"type": "text", "text": "8}"},
                            ]
                        },
                    }
                ],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4},
            },
        )

    _install_mock_http(monkeypatch, handler)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    provider = OpenRouterProvider(model="x/y:free")
    comp = provider.complete(
        system="S", user="U", temperature=0.4, seed=1, max_tokens=64, retries=0
    )
    assert comp.text == '{"rating": 8}'


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
    # current Claude models accept only default sampling: never send temperature
    assert "temperature" not in body and "seed" not in body
    assert body["max_tokens"] >= 16_000  # room for (default-on) thinking
    assert "output_config" not in body  # effort unset: the model's default


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

    from prebuttal.providers.agent_cli import _CODEX_OFF, claude_provider, codex_provider

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
    assert cmds[0] == ["claude", "-p", "--tools", "", "--strict-mcp-config", "--model", "opus"]
    # codex's stdin marker "-" must stay the FINAL argument
    assert cmds[1] == [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--ignore-user-config",
        "--ephemeral",
        *(a for f in _CODEX_OFF for a in ("--disable", f)),
        "-c",
        'web_search="disabled"',
        "--model",
        "gpt-5.1",
        "-",
    ]


def test_builtin_agents_run_locked_down_in_empty_cwd(monkeypatch, tmp_path):
    """Prompt-injection guard: a paper must not be able to steer the agent into
    the user's files — no tools for claude, read-only sandbox for codex, and an
    empty temp working directory for both."""
    import os
    import subprocess as sp

    from prebuttal.providers.agent_cli import claude_provider, codex_provider

    seen: list[tuple[list[str], str, list[str]]] = []

    class FakeCompleted:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(cmd, input=None, cwd=None, **kw):
        seen.append((list(cmd), cwd, os.listdir(cwd)))
        return FakeCompleted()

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.chdir(tmp_path)
    for provider in (claude_provider(), codex_provider()):
        provider.complete(system="s", user="u", retries=0)
    for _cmd, cwd, listing in seen:
        assert cwd and os.path.abspath(cwd) != str(tmp_path)
        assert listing == []
        assert not os.path.exists(cwd)  # cleaned up afterwards
    assert seen[0][0][2:5] == ["--tools", "", "--strict-mcp-config"]
    assert "read-only" in seen[1][0]
    assert "--ignore-user-config" in seen[1][0] and "--ephemeral" in seen[1][0]
    # no tool that reads files (keys.env): the sandbox alone allows reads on macOS/Linux
    for feature in ("shell_tool", "unified_exec", "code_mode_host"):
        assert ["--disable", feature] in [seen[1][0][i : i + 2] for i in range(len(seen[1][0]))]


def test_agent_cli_outdated_flag_is_not_retried(monkeypatch):
    import subprocess as sp

    from prebuttal.providers.agent_cli import claude_provider
    from prebuttal.providers.base import ProviderError, TransientProviderError

    calls = []

    class FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "error: unknown option '--tools'"

    def fake_run(cmd, input=None, **kw):
        calls.append(cmd)
        return FakeCompleted()

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ProviderError) as exc:
        claude_provider().complete(system="s", user="u", retries=2)
    assert not isinstance(exc.value, TransientProviderError)
    assert "update claude" in str(exc.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "stderr",
    [
        # claude -p --model haiku-5.5
        '[claude-code:unrecognized_model] {"model":"haiku-5.5"}\nThere\'s an issue with '
        "the selected model (haiku-5.5). It may not exist or you may not have access to it.",
        # codex exec --model no-such-model
        'ERROR: {"type":"error","status":400,"error":{"type":"invalid_request_error",'
        '"code":"model_not_found"}}',
    ],
)
def test_agent_cli_unknown_model_is_not_retried(monkeypatch, stderr):
    import subprocess as sp

    from prebuttal.providers.agent_cli import claude_provider
    from prebuttal.providers.base import ProviderError, TransientProviderError

    calls = []

    class FakeCompleted:
        returncode = 1
        stdout = ""

    FakeCompleted.stderr = stderr

    def fake_run(cmd, input=None, **kw):
        calls.append(cmd)
        return FakeCompleted()

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ProviderError) as exc:
        claude_provider("haiku-5.5").complete(system="s", user="u", retries=2)
    assert not isinstance(exc.value, TransientProviderError)
    assert "model name" in str(exc.value)
    assert len(calls) == 1


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
    assert cmds == [[resolved, "-p", "--tools", "", "--strict-mcp-config"]]


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


def test_overloaded_503_gets_patient_retries_and_honors_retry_after(monkeypatch, capsys):
    import httpx

    from prebuttal.providers.api import GeminiProvider

    responses = iter(
        [
            httpx.Response(503, json={"error": "overloaded"}, headers={"retry-after": "7"}),
            httpx.Response(503, json={"error": "overloaded"}),
            httpx.Response(503, json={"error": "overloaded"}),
            httpx.Response(
                200,
                json={
                    "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                    "usageMetadata": {},
                },
            ),
        ]
    )
    _install_mock_http(monkeypatch, lambda request: next(responses))
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    sleeps: list[float] = []
    monkeypatch.setattr("prebuttal.providers.base.time.sleep", lambda s: sleeps.append(s))
    comp = GeminiProvider(model="gemini-3.8-flash").complete(
        system="S", user="U", temperature=0.4, seed=1, max_tokens=64, retries=2
    )
    assert comp.text == "ok"
    # 3 retries although retries=2: overload gets at least SLOW_MIN_RETRIES
    assert sleeps == [7.0, 30.0, 60.0]
    assert "retrying in 7s (1/4)" in capsys.readouterr().err


def test_overload_retry_budget_and_repair_pass(monkeypatch):
    import httpx

    from prebuttal.providers.api import GeminiProvider
    from prebuttal.providers.base import SLOW_MIN_RETRIES, ProviderError

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, json={"error": "overloaded"})

    _install_mock_http(monkeypatch, handler)
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.setattr("prebuttal.providers.base.time.sleep", lambda s: None)
    provider = GeminiProvider(model="gemini-3.8-flash")
    with pytest.raises(ProviderError, match="503"):
        provider.complete(system="S", user="U", retries=2)
    assert calls["n"] == SLOW_MIN_RETRIES + 1

    calls["n"] = 0
    with pytest.raises(ProviderError):
        provider.complete(system="S", user="U", retries=0)  # repair pass: no retries
    assert calls["n"] == 1


def test_agent_cli_refuses_paper_in_argv_of_a_batch_launcher(monkeypatch):
    """cmd.exe re-parses .cmd/.bat arguments: paper text must never go there."""
    from prebuttal.providers import agent_cli
    from prebuttal.providers.agent_cli import AgentCLIProvider
    from prebuttal.providers.base import ProviderError

    monkeypatch.setattr(agent_cli.os, "name", "nt")
    monkeypatch.setattr(agent_cli.shutil, "which", lambda name: r"C:\tools\myagent.CMD")
    ran: list = []
    monkeypatch.setattr(agent_cli.subprocess, "run", lambda *a, **k: ran.append(a))
    p = AgentCLIProvider("agent-mine", ["myagent"], stdin=False)
    with pytest.raises(ProviderError, match="stdin = true"):
        p.complete(system="s", user="Table & | %PATH%", retries=0)
    assert ran == []


def test_ollama_bad_responses_are_provider_errors(monkeypatch):
    from prebuttal.providers import ollama
    from prebuttal.providers.base import ProviderError, TransientProviderError

    class R:
        def __init__(self, code, text):
            self.status_code, self.text = code, text

        def json(self):
            import json as _json

            return _json.loads(self.text)

    p = ollama.OllamaProvider(model="m")
    monkeypatch.setattr(ollama.httpx, "post", lambda *a, **k: R(200, "<html>proxy</html>"))
    with pytest.raises(ProviderError, match="non-JSON"):
        p._complete(system="s", user="u", temperature=0, seed=None, max_tokens=10)
    monkeypatch.setattr(ollama.httpx, "post", lambda *a, **k: R(500, "loading model"))
    with pytest.raises(TransientProviderError):
        p._complete(system="s", user="u", temperature=0, seed=None, max_tokens=10)


@pytest.mark.parametrize("model", ["--dangerously-skip-permissions", "sonnet & calc", "a|b"])
def test_agent_cli_refuses_unsafe_model_values(monkeypatch, model):
    """A model id from someone's prebuttal.toml must not become a flag or,
    through an npm .cmd launcher, a cmd.exe operator."""
    import subprocess as sp

    from prebuttal.providers.agent_cli import claude_provider
    from prebuttal.providers.base import ProviderError

    calls = []
    monkeypatch.setattr(sp, "run", lambda cmd, **kw: calls.append(cmd))
    with pytest.raises(ProviderError) as exc:
        claude_provider(model).complete(system="s", user="u", retries=2)
    assert "unsafe" in str(exc.value)
    assert calls == []


def test_agent_cli_accepts_real_model_ids():
    from prebuttal.providers.agent_cli import claude_provider

    for model in ("sonnet", "claude-opus-5-5[1m]", "gpt-6-luna", "org/model:free"):
        assert model in claude_provider(model)._build_command()


def test_retry_after_ignores_non_finite_values():
    from prebuttal.providers.api import _retry_after

    assert _retry_after("nan") is None
    assert _retry_after("inf") is None
    assert _retry_after("12") == 12.0


def test_codex_unknown_feature_is_not_retried(monkeypatch):
    import subprocess as sp

    from prebuttal.providers.agent_cli import codex_provider
    from prebuttal.providers.base import ProviderError, TransientProviderError

    calls = []

    class FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "Error: Unknown feature flag: browser_use"

    monkeypatch.setattr(sp, "run", lambda cmd, **kw: calls.append(cmd) or FakeCompleted())
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ProviderError) as exc:
        codex_provider().complete(system="s", user="u", retries=2)
    assert not isinstance(exc.value, TransientProviderError)
    assert "update prebuttal" in str(exc.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("value", "url"),
    [
        ("", "http://127.0.0.1:11434"),
        ("localhost:11434", "http://127.0.0.1:11434"),  # normalised like 0.0.0.0
        ("0.0.0.0:11434", "http://127.0.0.1:11434"),  # Ollama's own server setting
        ("0.0.0.0", "http://127.0.0.1:11434"),
        ("gpu-box:8080", "http://gpu-box:8080"),
        ("https://ollama.example.org", "https://ollama.example.org"),
    ],
)
def test_ollama_host_as_ollama_documents_it(monkeypatch, value, url):
    from prebuttal.providers.ollama import ollama_base_url

    monkeypatch.delenv("PREBUTTAL_OLLAMA_HOST", raising=False)
    if value:
        monkeypatch.setenv("OLLAMA_HOST", value)
    else:
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert ollama_base_url() == url
