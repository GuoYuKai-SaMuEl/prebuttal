import pytest

from prebuttal.config import (
    ConfigError,
    apply_overrides,
    default_reviewers,
    load_config,
    reviewer_seed,
)


def test_defaults_without_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no prebuttal.toml present
    cfg = load_config(None)
    assert cfg.venue == "neurips"
    assert len(cfg.reviewers) == 3
    assert [r.persona for r in cfg.reviewers] == [
        "senior_kind",
        "adversarial",
        "detail_obsessive",
    ]
    assert cfg.reviewers[1].temperature == 0.7
    assert all(r.backend == "auto" for r in cfg.reviewers)


def test_load_toml(tmp_path):
    f = tmp_path / "prebuttal.toml"
    f.write_text(
        """
[default]
venue = "iclr"
seed = 7

[[reviewer]]
id = "R1"
persona = "senior_kind"
backend = "agent-claude"

[[reviewer]]
id = "R2"
persona = "adversarial"
backend = "agent-codex"
temperature = 0.9

[[reviewer]]
id = "R3"
persona = "paper_roast"
backend = "ollama"
model = "llama3.1"

[ac]
backend = "api-gemini"

[agents.myagent]
command = ["myagent", "--headless"]
stdin = true

[pricing."gemini-9-pro"]
in = 1.25
out = 10.0
""",
        encoding="utf-8",
    )
    cfg = load_config(f)
    assert cfg.venue == "iclr"
    assert cfg.seed == 7
    assert [r.id for r in cfg.reviewers] == ["R1", "R2", "R3"]
    assert cfg.reviewers[2].model == "llama3.1"
    assert cfg.ac.backend == "api-gemini"
    assert cfg.agents["myagent"].command == ["myagent", "--headless"]
    assert cfg.pricing["gemini-9-pro"] == (1.25, 10.0)
    assert cfg.pricing["gemini-2.5-flash"][0] == 0.30  # defaults retained


def test_invalid_venue_rejected(tmp_path):
    f = tmp_path / "prebuttal.toml"
    f.write_text('[default]\nvenue = "aaai"\n', encoding="utf-8")
    try:
        load_config(f)
        raise AssertionError("should raise")
    except ConfigError as e:
        assert "aaai" in str(e)


def test_duplicate_reviewer_id_rejected(tmp_path):
    f = tmp_path / "prebuttal.toml"
    f.write_text(
        """
[[reviewer]]
id = "R1"
persona = "senior_kind"

[[reviewer]]
id = "R1"
persona = "adversarial"
""",
        encoding="utf-8",
    )
    try:
        load_config(f)
        raise AssertionError("should raise")
    except ConfigError as e:
        assert "duplicate" in str(e)


def test_overrides():
    cfg = load_config(None)
    cfg = apply_overrides(
        cfg, venue="acl", seed=99, backend="ollama", model="llama3.1", reviewers_count=4
    )
    assert cfg.venue == "acl"
    assert cfg.seed == 99
    assert all(r.backend == "ollama" for r in cfg.reviewers)
    assert all(r.model == "llama3.1" for r in cfg.reviewers)
    assert len(cfg.reviewers) == 4
    assert cfg.reviewers[3].persona == "senior_kind"  # cycle restarts


def test_reviewer_seed_sequence():
    cfg = load_config(None)
    cfg = apply_overrides(cfg, seed=42)
    assert [reviewer_seed(cfg, r, i) for i, r in enumerate(cfg.reviewers)] == [43, 44, 45]
    cfg.reviewers[0].seed = 1000
    assert reviewer_seed(cfg, cfg.reviewers[0], 0) == 1000


def test_default_reviewers_clamp():
    assert len(default_reviewers(9)) == 5
    assert len(default_reviewers(0)) == 1


def _toml(tmp_path, text):
    f = tmp_path / "prebuttal.toml"
    f.write_text(text, encoding="utf-8")
    return f


@pytest.mark.parametrize(
    "text",
    [
        '[default]\nseed = "abc"\n',
        'reviewer = "R1"\n',
        '[[reviewer]]\nid = "R1"\ntemperature = "hot"\n',
    ],
)
def test_wrong_value_types_are_config_errors(tmp_path, text):
    with pytest.raises(ConfigError, match="invalid value"):
        load_config(_toml(tmp_path, text))


def test_agent_without_command_rejected(tmp_path):
    with pytest.raises(ConfigError, match="needs command"):
        load_config(_toml(tmp_path, "[agents.mine]\nstdin = true\n"))


def test_reviewer_seed_from_toml(tmp_path):
    cfg = load_config(
        _toml(tmp_path, '[[reviewer]]\nid = "R1"\nseed = 7\n[[reviewer]]\nid = "R2"\n')
    )
    assert cfg.reviewers[0].seed == 7
    assert reviewer_seed(cfg, cfg.reviewers[0], 0) == 7
    assert cfg.reviewers[1].seed is None


def test_reviewers_count_keeps_configured_reviewers(tmp_path):
    cfg = load_config(
        _toml(
            tmp_path,
            '[[reviewer]]\nid = "A"\npersona = "adversarial"\nbackend = "api-gemini"\n'
            'model = "m1"\n[[reviewer]]\nid = "R2"\nbackend = "ollama"\n',
        )
    )
    grown = apply_overrides(cfg, reviewers_count=4).reviewers
    assert [r.id for r in grown] == ["A", "R2", "R3", "R4"]
    assert (grown[0].backend, grown[0].model, grown[0].persona) == (
        "api-gemini",
        "m1",
        "adversarial",
    )
    assert grown[1].backend == "ollama"
    shrunk = apply_overrides(load_config(tmp_path / "prebuttal.toml"), reviewers_count=1)
    assert [(r.id, r.backend) for r in shrunk.reviewers] == [("A", "api-gemini")]


def test_backend_override_drops_models_meant_for_another_backend():
    """--backend api-gemini must not send the file's `sonnet` to Gemini."""
    from prebuttal.config import ACConfig, ReviewerConfig, RunConfig

    cfg = RunConfig(
        reviewers=[
            ReviewerConfig("R1", "senior_kind", "agent-claude", "sonnet"),
            ReviewerConfig("R2", "adversarial", "api-gemini", "gemini-3.8-flash"),
        ],
        ac=ACConfig(backend="agent-claude", model="opus"),
    )
    cfg = apply_overrides(cfg, backend="api-gemini")
    assert [r.model for r in cfg.reviewers] == ["", "gemini-3.8-flash"]  # same backend keeps it
    assert cfg.ac.model == ""
    cfg = apply_overrides(cfg, backend="agent-codex", model="gpt-6-luna")
    assert {r.model for r in cfg.reviewers} == {"gpt-6-luna"} and cfg.ac.model == "gpt-6-luna"
