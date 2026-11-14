"""`repeats` in prebuttal.toml: every reviewer reviews k times, the AC once."""

import json

import pytest
from conftest import FAKE_TOML, PersonaFakeProvider, fake_toml, latest_json, latest_report

from prebuttal import cli
from prebuttal.config import ConfigError, load_config, reviewer_seed
from prebuttal.models import Review
from prebuttal.orchestrator import build_ac_user, review_slots
from prebuttal.providers import register_backend
from prebuttal.providers.base import ProviderError
from prebuttal.runs import load_history
from prebuttal.venues import get_venue

_ROLE = {"backend": "fake", "model": "m", "temperature": 0.4, "seed": 1}


def _with_repeats(toml: str, k: int) -> str:
    return toml.replace("[default]", f"[default]\nrepeats = {k}", 1)


def test_repeats_default_to_one_and_are_checked(tmp_path):
    assert load_config(None).repeats == 1
    p = tmp_path / "prebuttal.toml"
    p.write_text(_with_repeats(FAKE_TOML, 5), encoding="utf-8")
    assert load_config(str(p)).repeats == 5
    for bad in ("0", "6", '"3"', "true", "2.5"):
        p.write_text(_with_repeats(FAKE_TOML, bad), encoding="utf-8")  # type: ignore[arg-type]
        with pytest.raises(ConfigError, match=r"repeats .* from 1 to 5"):
            load_config(str(p))


def test_each_round_steps_the_seed_also_a_reviewers_own(tmp_path):
    p = tmp_path / "prebuttal.toml"
    toml = _with_repeats(FAKE_TOML, 3).replace('id = "R3"', 'id = "R3"\nseed = 100')
    p.write_text(toml, encoding="utf-8")
    cfg = load_config(str(p))
    slots = review_slots(cfg)
    # each reviewer's rounds together, in reviewer order
    assert [s.key for s in slots] == [(r, k) for r in ("R1", "R2", "R3") for k in range(3)]
    assert [s.seed_for(cfg) for s in slots] == [8, 1008, 2008, 9, 1009, 2009, 100, 1100, 2100]
    assert reviewer_seed(cfg, cfg.reviewers[0], 0) == 8  # round 0: the seed of a single run


@pytest.fixture
def repeats_run(latex_project, fake_statuses, tmp_path, monkeypatch):
    calls: list[dict] = []
    register_backend("fake", lambda m, cfg, t: PersonaFakeProvider(model="fake-m", calls=calls))
    cfg_path = tmp_path / "prebuttal.toml"
    cfg_path.write_text(_with_repeats(fake_toml("reports", with_json=True), 2), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return cfg_path, calls


def test_a_run_with_repeats(latex_project, repeats_run, tmp_path, capsys):
    cfg_path, calls = repeats_run
    assert cli.main(["run", str(latex_project), "--config", str(cfg_path)]) == cli.EXIT_OK
    err = capsys.readouterr().err
    assert "[R1·2] done" in err

    ac_calls = [c for c in calls if "estimated_rating" in c["system"]]
    reviewer_calls = [c for c in calls if "estimated_rating" not in c["system"]]
    assert len(reviewer_calls) == 6 and len(ac_calls) == 1  # the AC once, over all rounds
    assert sorted(c["seed"] for c in reviewer_calls) == [8, 9, 10, 1008, 1009, 1010]
    ac_user = ac_calls[0]["user"]
    assert "Each of the 3 reviewers reviewed the paper 2 times" in ac_user
    assert '"round": 2' in ac_user and "summary and weaknesses" not in ac_user

    data = latest_json(tmp_path / "reports")
    assert [(r["reviewer_id"], r["repeat"]) for r in data["reviewers"]] == [
        (r, k) for r in ("R1", "R2", "R3") for k in range(2)
    ]
    assert [r["seed"] for r in data["reviewers"]] == [8, 1008, 9, 1009, 10, 1010]
    md = latest_report(tmp_path / "reports").read_text(encoding="utf-8")
    assert "## Review 2: R1·2" in md and "| R3·2 |" in md
    rec = load_history()[0]
    resolved = json.loads((rec.dir_path / "resolved-config.json").read_text(encoding="utf-8"))
    assert resolved["repeats"] == 2


def test_a_single_run_tells_the_ac_nothing_about_rounds():
    venue = get_venue("iclr")
    reviews = [Review(f"R{i}", "senior_kind", **_ROLE, parse_ok=True) for i in (1, 2, 3)]
    user = build_ac_user("PACK", reviews, venue)
    assert "The three reviews follow as JSON." in user and '"round"' not in user


def test_many_rounds_give_the_ac_short_reviews():
    venue = get_venue("iclr")
    reviews = [
        Review(
            reviewer_id=rid,
            persona="senior_kind",
            repeat=k,
            **_ROLE,
            parse_ok=True,
            fields={"summary": "S", "weaknesses": ["W"], "questions": ["Q" * 500]},
        )
        for rid in ("R1", "R2")
        for k in range(3)
    ]
    full = build_ac_user("PACK", reviews, venue)
    short = build_ac_user("PACK", reviews, venue, max_review_chars=1000)
    assert '"questions"' in full and '"questions"' not in short
    assert '"weaknesses"' in short and "Only each review's summary and weaknesses" in short


def test_dry_run_counts_the_rounds(latex_project, repeats_run, capsys):
    cfg_path, _calls = repeats_run
    toml = cfg_path.read_text(encoding="utf-8").replace("repeats = 2", "repeats = 3")
    cfg_path.write_text(toml, encoding="utf-8")
    assert cli.main(["run", str(latex_project), "--config", str(cfg_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "each reviewer reviews 3 times, the AC once" in out
    assert out.count("(× 3 repeats)") == 3  # noqa: RUF001 - the reviewers, not the AC
    assert "R1=8" in out and "round k adds 1000·k" in out


def test_retry_keeps_each_rounds_seed(latex_project, repeats_run, tmp_path):
    """A reviewer down in both rounds: retry writes both again, seeds unchanged."""
    cfg_path, calls = repeats_run
    down = {"on": True}

    class _Flaky(PersonaFakeProvider):
        def _complete(self, **kw):
            if down["on"]:
                raise ProviderError("HTTP 503: overloaded")
            return super()._complete(**kw)

    register_backend("flaky", lambda m, cfg, t: _Flaky(backend="flaky", calls=calls))
    toml = cfg_path.read_text(encoding="utf-8").replace(
        'persona = "adversarial"\nbackend = "fake"', 'persona = "adversarial"\nbackend = "flaky"'
    )
    cfg_path.write_text(toml, encoding="utf-8")
    assert cli.main(["run", str(latex_project), "--config", str(cfg_path)]) == cli.EXIT_PARTIAL

    down["on"] = False
    calls.clear()
    assert cli.main(["retry"]) == cli.EXIT_OK
    redone = [c for c in calls if "estimated_rating" not in c["system"]]
    assert sorted(c["seed"] for c in redone) == [9, 1009]
    new = json.loads((load_history()[0].dir_path / "report.json").read_text(encoding="utf-8"))
    assert all(r["parse_ok"] for r in new["reviewers"])
    assert [r["seed"] for r in new["reviewers"]] == [8, 1008, 9, 1009, 10, 1010]
