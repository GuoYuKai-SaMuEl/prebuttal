"""Reasoning effort: config, per-backend request shapes, and how reports show it."""

import json

import httpx
import pytest
from test_providers import _install_mock_http

from prebuttal.config import ConfigError, apply_overrides, load_config, role_effort
from prebuttal.models import effort_support, param_support

OK_OPENAI = {
    "choices": [{"message": {"content": '{"rating": 7}'}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
}


def _capture(monkeypatch, response: dict) -> dict:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json=response)

    _install_mock_http(monkeypatch, handler)
    return captured


def _call(provider, effort: str = "high") -> None:
    provider.effort = effort
    provider.complete(system="S", user="U", temperature=0.5, seed=9, max_tokens=800, retries=0)


# ------------------------------------------------------------------- config


def test_effort_config_levels_and_precedence(tmp_path):
    p = tmp_path / "p.toml"
    p.write_text(
        '[default]\neffort = "medium"\n'
        '[[reviewer]]\nid = "R1"\npersona = "senior_kind"\neffort = "high"\n'
        '[[reviewer]]\nid = "R2"\npersona = "adversarial"\n'
        '[ac]\neffort = "low"\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert [role_effort(cfg, r) for r in ("R1", "R2", "AC")] == ["high", "medium", "low"]

    cfg = apply_overrides(cfg, effort="low")  # --effort wins everywhere
    assert {role_effort(cfg, r) for r in ("R1", "R2", "AC")} == {"low"}

    assert role_effort(load_config(None), "R1") == ""  # unset: each model's default

    p.write_text('[default]\neffort = "extreme"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown effort"):
        load_config(p)


def test_support_matrix():
    assert effort_support("agent-claude") and effort_support("agent-codex")
    assert not effort_support("agent-mytool") and not effort_support("relay")
    assert effort_support("api-openai", "gpt-5.6-terra")
    assert not effort_support("api-openai", "gpt-4.1-mini")
    assert effort_support("ollama", "gpt-oss:20b") and not effort_support("ollama", "llama3.1")
    # sampling: Claude API models take only defaults; OpenAI reasoning models no temperature
    assert param_support("api-anthropic", "claude-sonnet-5-5") == (False, False)
    assert param_support("api-openai", "gpt-5.6-terra") == (False, True)
    assert param_support("api-openai", "gpt-4.1-mini") == (True, True)
    # later generations are reasoning models too (a gpt-6 must not get temperature)
    for m in ("gpt-6-luna", "gpt-7", "gpt-10-mini", "o4-mini", "openai/gpt-6-luna"):
        assert param_support("api-openai", m) == (False, True), m
    assert param_support("api-openai", "gpt-4o-mini") == (True, True)


# ------------------------------------------------------------ request shapes


def test_openai_reasoning_model(monkeypatch):
    from prebuttal.providers.api import OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    cap = _capture(monkeypatch, OK_OPENAI)
    _call(OpenAIProvider(model="gpt-5.6-terra"))
    body = cap["json"]
    assert body["reasoning_effort"] == "high"
    assert "temperature" not in body and "max_tokens" not in body
    assert body["max_completion_tokens"] >= 16_000
    assert body["seed"] == 9

    _call(OpenAIProvider(model="gpt-5.6-terra"), effort="")
    assert "reasoning_effort" not in cap["json"]


def test_openai_classic_model_ignores_effort(monkeypatch):
    from prebuttal.providers.api import OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    cap = _capture(monkeypatch, OK_OPENAI)
    provider = OpenAIProvider(model="gpt-4.1-mini")
    _call(provider)
    assert "reasoning_effort" not in cap["json"]
    assert cap["json"]["temperature"] == 0.5 and cap["json"]["max_tokens"] == 800
    assert provider.applied_effort == ""  # reported as the model default


def test_anthropic_effort(monkeypatch):
    from prebuttal.providers.api import AnthropicProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    cap = _capture(
        monkeypatch,
        {"content": [{"type": "text", "text": "{}"}], "usage": {}},
    )
    _call(AnthropicProvider(model="claude-sonnet-5-5"), effort="low")
    assert cap["json"]["output_config"] == {"effort": "low"}
    assert "temperature" not in cap["json"]


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gemini-3.5-flash-lite", {"thinkingLevel": "medium"}),
        ("gemini-2.5-flash", {"thinkingBudget": 8192}),
    ],
)
def test_gemini_effort(monkeypatch, model, expected):
    from prebuttal.providers.api import GeminiProvider

    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    cap = _capture(
        monkeypatch,
        {"candidates": [{"content": {"parts": [{"text": "{}"}]}}], "usageMetadata": {}},
    )
    _call(GeminiProvider(model=model), effort="medium")
    assert cap["json"]["generationConfig"]["thinkingConfig"] == expected


def test_openrouter_effort(monkeypatch):
    from prebuttal.providers.api import OpenRouterProvider

    monkeypatch.setenv("OPENROUTER_API_KEY", "or")
    cap = _capture(monkeypatch, OK_OPENAI)
    _call(OpenRouterProvider(model="some/model"))
    assert cap["json"]["reasoning"] == {"effort": "high"}


def test_agent_cli_effort_flags():
    from prebuttal.providers.agent_cli import claude_provider, codex_provider

    claude = claude_provider()
    claude.effort = "low"
    assert claude._build_command()[-2:] == ["--effort", "low"]

    codex = codex_provider(model="gpt-6.1-sol")
    codex.effort = "high"
    cmd = codex._build_command()
    assert cmd[-1] == "-"  # stdin marker stays last
    assert cmd[-5:-1] == ["--model", "gpt-6.1-sol", "-c", 'model_reasoning_effort="high"']

    codex.effort = ""
    assert "model_reasoning_effort" not in " ".join(codex._build_command())


# ------------------------------------------------------------------ reports


def test_report_and_dry_run_show_effort(latex_project):
    from conftest import make_report

    from prebuttal.dryrun import render_dry_run
    from prebuttal.providers.detect import BackendStatus
    from prebuttal.report import render_markdown

    report, venue = make_report(latex_project)
    report.reviews[0].effort = "high"
    md = render_markdown(report, venue)
    assert "· effort high ·" in md
    assert "| high |" in md and "| default |" in md

    cfg = load_config(None)
    cfg = apply_overrides(cfg, effort="medium")
    statuses = [BackendStatus("relay", "relay", True, "")]
    plan = render_dry_run(cfg, [("R1", "agent-claude", "")], ("relay", ""), 1000, statuses)
    assert "effort: medium" in plan
    assert "not supported here" in plan  # relay AC has no effort control


@pytest.mark.parametrize(
    "model, ok",
    [
        ("", True),  # the default model
        ("claude-sonnet-5-5", True),
        ("claude-opus-4-6", True),
        ("claude-fable-5-1", True),
        ("claude-opus-4-5", True),
        ("claude-opus-4-5-20251101", True),
        ("claude-sonnet-4-5", False),
        ("claude-haiku-4-5", False),
        ("claude-sonnet-4", False),
        ("claude-3-7-sonnet-latest", False),
    ],
)
def test_anthropic_effort_only_where_the_api_takes_it(model, ok):
    assert effort_support("api-anthropic", model) is ok
