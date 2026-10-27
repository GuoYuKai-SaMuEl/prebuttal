"""`prebuttal diff --llm`: revision-plan items matched by meaning."""

import json

from conftest import PersonaFakeProvider

from prebuttal import cli
from prebuttal.diffmatch import match_plan
from prebuttal.models import Usage
from prebuttal.providers import register_backend
from prebuttal.providers.base import BaseProvider, ProviderError
from prebuttal.runs import load_history


class _Canned(BaseProvider):
    def __init__(self, answer: str | Exception):
        super().__init__("canned", "m1")
        self.answer = answer
        self.prompts: list[str] = []

    def _complete(self, *, system, user, temperature, seed, max_tokens):
        self.prompts.append(user)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer, Usage()


A = ["No Perceiver baseline in Table 1.", "Single seed only."]
B = ["Comparison with latent-array models is missing.", "Only English datasets."]
W = ["Results come from one random seed."]


def test_match_plan_parses_and_validates():
    p = _Canned(
        json.dumps(
            {
                "a": [
                    {"id": "A1", "still_raised": True, "matched_by": ["B1"]},
                    {"id": "A2", "still_raised": True, "matched_by": ["W1"]},
                ],
                "new_in_b": ["B2", "B9", "nonsense"],
            }
        )
    )
    m = match_plan(p, A, B, W)
    assert m is not None and m.still == {0, 1} and m.new_b == [1]
    assert m.label == "canned / m1"
    assert "<submission>" in p.prompts[0]  # model output is fenced as data


def test_match_plan_rejects_incomplete_or_failed_answers():
    assert match_plan(_Canned('{"a": [{"id": "A1", "still_raised": false}]}'), A, B, W) is None
    assert match_plan(_Canned("not json"), A, B, W) is None
    assert match_plan(_Canned(ProviderError("down")), A, B, W) is None


def _two_runs(latex_project, fake_config, monkeypatch):
    monkeypatch.chdir(fake_config.parent)
    for _ in range(2):
        assert cli.main(["run", str(latex_project), "--config", str(fake_config)]) == 0
    return load_history()


def test_cli_diff_llm_uses_the_model_match(
    latex_project, fake_statuses, fake_config, monkeypatch, capsys
):
    hist = _two_runs(latex_project, fake_config, monkeypatch)
    plan = json.loads((hist[1].dir_path / "report.json").read_text(encoding="utf-8"))["meta"]
    n = len(plan["action_plan"])
    answer = json.dumps(
        {"a": [{"id": f"A{i}", "still_raised": i == 1} for i in range(1, n + 1)], "new_in_b": []}
    )
    register_backend("matcher", lambda m, cfg, t: _Canned(answer))
    capsys.readouterr()

    monkeypatch.setenv("PREBUTTAL_BACKEND", "matcher")  # the AC backend, without a flag
    rc = cli.main(["diff", "--llm"])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "matched by canned / m1" in out
    assert out.count("- still raised:") == 1
    assert f"{n - 1} of {n} plan items were not re-detected" in out
    assert "Matching is by wording" not in out


def test_cli_diff_llm_falls_back_to_word_overlap(
    latex_project, fake_statuses, fake_config, monkeypatch, capsys
):
    _two_runs(latex_project, fake_config, monkeypatch)
    # the fake backend answers with a review, not a plan match
    register_backend("fake", lambda m, cfg, t: PersonaFakeProvider(model="fake-m"))
    capsys.readouterr()
    monkeypatch.setenv("PREBUTTAL_BACKEND", "fake")
    rc = cli.main(["diff", "--llm"])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "model matching failed — fell back to word overlap" in out
