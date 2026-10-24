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
    f.write_text('[default]\nvenue = "cvpr"\n', encoding="utf-8")
    try:
        load_config(f)
        raise AssertionError("should raise")
    except ConfigError as e:
        assert "cvpr" in str(e)


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
