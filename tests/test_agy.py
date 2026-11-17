"""agent-agy: the Antigravity CLI backend (stream-json in and out, locked down)."""

from __future__ import annotations

import json
import os
import subprocess as sp

import pytest

from prebuttal.providers.agent_cli import _AGY_DENY, agy_provider
from prebuttal.providers.base import ProviderError, TransientProviderError


def _result(**fields) -> str:
    base = {"conversation_id": "c", "status": "SUCCESS", "response": "", "num_turns": 1}
    return json.dumps({"event": "result", "result": {**base, **fields}})


def _fake(monkeypatch, *, stdout="", stderr="", returncode=0):
    seen: list[dict] = []

    class Done:
        pass

    def run(cmd, input=None, cwd=None, **kw):
        seen.append({"cmd": list(cmd), "input": input, "cwd": cwd, "ls": os.listdir(cwd)})
        done = Done()
        done.returncode, done.stdout, done.stderr = returncode, stdout, stderr
        return done

    monkeypatch.setattr(sp, "run", run)
    monkeypatch.setattr("shutil.which", lambda name: None)  # keep the bare name
    return seen


def test_prompt_goes_in_as_one_stream_json_event_and_the_answer_comes_back(monkeypatch):
    out = "\n".join(
        [
            json.dumps({"event": "init", "init": {"tools": ["run_command"]}}),
            json.dumps({"event": "step_update", "step_update": {"text_delta": "par"}}),
            "not json",
            _result(
                response='{"rating": 6}\n',
                usage={"input_tokens": 9000, "output_tokens": 40, "thinking_tokens": 10},
            ),
        ]
    )
    seen = _fake(monkeypatch, stdout=out)
    c = agy_provider().complete(system="SYS", user="PAPER & %PATH% | x", retries=0)
    assert c.text == '{"rating": 6}\n'
    assert (c.usage.prompt_tokens, c.usage.completion_tokens) == (9000, 50)
    (call,) = seen
    assert call["input"].endswith("\n") and call["input"].count("\n") == 1
    event = json.loads(call["input"])
    assert event["event"] == "user"
    assert event["message"]["content"] == "SYS\n\n---\n\nPAPER & %PATH% | x"


def test_agy_runs_locked_down_in_an_empty_folder(monkeypatch, tmp_path):
    seen = _fake(monkeypatch, stdout=_result(response="ok"))
    monkeypatch.chdir(tmp_path)
    agy_provider().complete(system="s", user="u", retries=0)
    (call,) = seen
    cmd = call["cmd"]
    assert call["cwd"] and os.path.abspath(call["cwd"]) != str(tmp_path)
    assert call["ls"] == [] and not os.path.exists(call["cwd"])
    assert "--disable-slash-commands" in cmd and "--sandbox" in cmd
    settings = json.loads(cmd[cmd.index("--settings") + 1])
    assert settings["toolPermission"] == "strict"
    # every action that reads a file, runs a command, opens a URL or calls MCP
    for action in ("read_file", "command", "unsandboxed", "read_url", "mcp"):
        assert f"{action}(*)" in settings["permissions"]["deny"]
    assert set(settings["permissions"]["deny"]) == set(_AGY_DENY)


def test_model_and_effort_go_before_the_print_flag(monkeypatch):
    seen = _fake(monkeypatch, stdout=_result(response="ok"))
    p = agy_provider(model="gemini-3.8-flash")
    p.effort = "low"
    p.complete(system="s", user="u", retries=0)
    cmd = seen[0]["cmd"]
    assert cmd[-5:] == ["--model", "gemini-3.8-flash", "--effort", "low", "-p="]


@pytest.mark.parametrize(
    "stdout, says",
    [
        (_result(status="ERROR", error="quota exhausted"), "quota exhausted"),
        (
            _result(response="", denied_actions=[{"action": "read_file"}]),
            "blocked tool: read_file",
        ),
        ("", "without a result event"),
    ],
)
def test_a_run_without_an_answer_is_a_retryable_error(monkeypatch, stdout, says):
    _fake(monkeypatch, stdout=stdout)
    p = agy_provider()
    with pytest.raises(TransientProviderError) as exc:  # complete() retries these
        p._complete(system="s", user="u", temperature=0.5, seed=None, max_tokens=100)
    assert says in str(exc.value)


@pytest.mark.parametrize(
    "reason",
    [  # agy 1.5.10's wording for each kind of bad model/effort pair
        "model x is not recognized as a known model or custom model in settings",
        'gpt-oss-120b has no "high" effort (available: medium)',
        '--effort is not supported for model "gemini-pro-orchestrator-g1-pro"',
        "--model gemini-4-argon-high conflicts with --effort=low",
    ],
)
def test_a_bad_model_or_effort_is_not_retried(monkeypatch, reason):
    # agy follows the one-line error with every model it knows
    err = (
        f'error: invalid model selection (--model "x" --effort "high"): {reason}\n'
        "Available models:\n" + "  Some Model (High)\n" * 60
    )
    calls = _fake(monkeypatch, stderr=err, returncode=1)
    with pytest.raises(ProviderError) as exc:
        agy_provider(model="x").complete(system="s", user="u", retries=2)
    assert not isinstance(exc.value, TransientProviderError)
    assert len(calls) == 1
    assert reason[:60] in str(exc.value)  # the reason, not the model list


def test_an_outdated_agy_is_told_to_update(monkeypatch):
    _fake(
        monkeypatch, stderr="flag provided but not defined: -disable-slash-commands", returncode=2
    )
    with pytest.raises(ProviderError) as exc:
        agy_provider().complete(system="s", user="u", retries=2)
    assert not isinstance(exc.value, TransientProviderError)
    assert "update agy" in str(exc.value)


def test_backends_list_agy_base_models(monkeypatch):
    import prebuttal.modelscan as ms

    listing = "Fetching available models...\n" + "".join(
        f"{m}\t{m.title()}\n"
        for m in (
            "gemini-4-argon-medium",
            "gemini-4-argon-high",
            "gemini-3.8-flash-low",
            "claude-sonnet-5-5-high",
            "gpt-oss-120b-medium",
        )
    )
    _fake(monkeypatch, stdout=listing)
    assert ms.agy_models() == [
        "gemini-4-argon",
        "gemini-3.8-flash",
        "claude-sonnet-5-5",
        "gpt-oss-120b",
    ]
    _fake(monkeypatch, stderr="not signed in", returncode=1)
    (lst,) = ms.scan(only="agent-agy")
    assert lst.models == [] and "could not list models" in lst.note


def test_agy_is_detected_without_a_sign_in_check(monkeypatch):
    import prebuttal.providers.detect as det
    from prebuttal.config import load_config

    asked: list[str] = []
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name == "agy" else None)
    monkeypatch.setattr(det, "signed_out", lambda cli: asked.append(cli) or False)
    monkeypatch.setattr(det, "ollama_tags", lambda base: [])
    by_name = {s.backend: s for s in det.scan_backends(load_config(None))}
    assert by_name["agent-agy"].available is True
    assert asked == []  # agy has no status command to ask
    assert by_name["agent-claude"].available is False


def test_agy_takes_an_effort():
    from prebuttal.models import effort_support, param_support

    assert effort_support("agent-agy")
    assert param_support("agent-agy") == (False, False)  # no temperature or seed
