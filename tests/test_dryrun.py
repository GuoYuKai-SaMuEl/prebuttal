from prebuttal.config import load_config
from prebuttal.dryrun import render_dry_run
from prebuttal.providers.detect import BackendStatus


def test_dry_run_matrix_and_costs():
    cfg = load_config(None)
    statuses = [
        BackendStatus("agent-claude", "agent", True, "claude CLI"),
        BackendStatus("api-gemini", "api", True, "key", "gemini-2.5-flash"),
        BackendStatus("ollama", "ollama", True, "up", "llama3.1"),
    ]
    resolved = [
        ("R1", "agent-claude", ""),
        ("R2", "api-gemini", "gemini-2.5-flash"),
        ("R3", "ollama", "llama3.1"),
    ]
    text = render_dry_run(cfg, resolved, ("agent-claude", ""), 40_000, statuses)

    assert "dry run" in text.lower()
    assert "R1   → agent-claude" in text.replace("  ", "  ") or "agent-claude" in text
    assert "subscription" in text  # agent CLI: no per-token cost
    assert "~$" in text  # gemini priced
    assert "local model — free" in text  # ollama
    assert "total" in text
    assert "Seeds: R1=43" in text
    # token math: 40000 chars -> 10000 tokens + overhead
    assert "10,000 tokens" in text
    assert "nothing will be called" in text.lower() or "no model was called" in text.lower()


def test_dry_run_unknown_model_pricing_hint():
    cfg = load_config(None)
    statuses = [BackendStatus("api-openai", "api", True, "key", "gpt-99")]
    resolved = [("R1", "api-openai", "gpt-99")]
    text = render_dry_run(cfg, resolved, ("api-openai", "gpt-99"), 10_000, statuses)
    assert "unknown price" in text
    assert "[pricing." in text  # tells the user how to add pricing


def test_dry_run_openrouter_free_is_zero_cost():
    cfg = load_config(None)
    statuses = [BackendStatus("api-openrouter", "api", True, "key")]
    free_id = "acme/model:free"
    resolved = [("R1", "api-openrouter", free_id)]
    text = render_dry_run(cfg, resolved, ("api-openrouter", free_id), 10_000, statuses)
    assert ":free tier — $0" in text
    assert "unknown price" not in text
