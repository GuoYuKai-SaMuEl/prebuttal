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


def test_dry_run_prices_default_model_when_unset():
    cfg = load_config(None)
    statuses = [BackendStatus("api-gemini", "api", True, "key", "gemini-3.5-flash-lite")]
    resolved = [("R1", "api-gemini", "")]
    text = render_dry_run(cfg, resolved, ("api-gemini", ""), 10_000, statuses)
    assert '[pricing.""]' not in text
    assert "unknown price" not in text
    assert "~$" in text  # priced via the backend's default model


def test_dry_run_shows_each_reviewers_real_seed():
    from prebuttal.config import ReviewerConfig, RunConfig

    cfg = RunConfig(
        reviewers=[
            ReviewerConfig("R1", "senior_kind", "relay", seed=7),
            ReviewerConfig("R2", "adversarial", "relay"),
        ]
    )
    out = render_dry_run(cfg, [("R1", "relay", ""), ("R2", "relay", "")], ("relay", ""), 1000, [])
    assert "Seeds: R1=7, R2=44, AC=42" in out


def test_dry_run_total_adds_priced_roles():
    cfg = load_config(None)
    cfg.pricing["m-priced"] = (1.0, 2.0)
    statuses = [BackendStatus("api-openai", "api", True, "key", "m-priced")]
    resolved = [(r.id, "api-openai", "m-priced") for r in cfg.reviewers]
    out = render_dry_run(cfg, resolved, ("api-openai", "m-priced"), 4000, statuses)
    each = [
        float(ln.split("~$")[1].split()[0])
        for ln in out.splitlines()
        if "~$" in ln and "total" not in ln
    ]
    total = float(out.split("total (priced backends): ~$")[1].split()[0])
    assert len(each) == 4 and abs(total - sum(each)) < 1e-3
