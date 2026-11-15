"""`prebuttal diff`: weaknesses and revision-plan items matched by meaning."""

import json

from conftest import PersonaFakeProvider

from prebuttal import cli
from prebuttal.diffmatch import match_plan, match_weaknesses
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
                "new_in_b": ["B2", "b2"],
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
    # one item that does not exist and the whole answer is not used
    full = [{"id": "A1", "still_raised": True}, {"id": "A2", "still_raised": False}]
    for bad in ({"a": full, "new_in_b": ["B9"]}, {"a": [*full, {"id": "A7"}], "new_in_b": []}):
        assert match_plan(_Canned(json.dumps(bad)), A, B, W) is None
    # ids int() can't read, a still_raised that is not a bool, an item both
    # carried on and new: not used (and never an exception)
    for odd in ("A²", "A" + "9" * 5000):
        ans = {"a": [{"id": odd, "still_raised": True}, full[1]], "new_in_b": []}
        assert match_plan(_Canned(json.dumps(ans)), A, B, W) is None
    for bad in (
        {"a": [{"id": "A1", "still_raised": "true"}, full[1]], "new_in_b": []},
        {"a": [{"id": "A1"}, full[1]], "new_in_b": []},
        {"a": [{"id": "A1", "still_raised": True, "matched_by": ["B1"]}, full[1]],
         "new_in_b": ["B1"]},
    ):  # fmt: skip
        assert match_plan(_Canned(json.dumps(bad)), A, B, W) is None


def test_match_plan_new_items_are_the_ones_nothing_carries_on():
    # new_in_b left out: B2 is still new, as on the dashboard (which reads links)
    ans = {"a": [{"id": "A1", "still_raised": True, "matched_by": ["B1"]},
                 {"id": "A2", "still_raised": False}], "new_in_b": []}  # fmt: skip
    m = match_plan(_Canned(json.dumps(ans)), A, B, W)
    assert m is not None and m.links == {0: [0]} and m.new_b == [1]


def test_match_weaknesses_answers_each_reviewer_in_one_call():
    groups = [(["Single seed only."], ["One random seed.", "No ablation."]),
              (["Unclear writing.", "No code."], ["Code is missing."])]  # fmt: skip
    answer = {"G1": {"A1": "B1"}, "G2": {"A1": None, "A2": "B1"}}
    p = _Canned(json.dumps(answer))
    assert match_weaknesses(p, groups) == [[0], [None, 0]]
    assert len(p.prompts) == 1 and "Reviewer G2" in p.prompts[0]
    # a reviewer whose answer is incomplete or names a missing item: None, the rest kept
    partial = {"G1": {"A1": "B7"}, "G2": {"A2": "B1"}}
    assert match_weaknesses(_Canned(json.dumps(partial)), groups) == [None, None]
    odd = {"G1": {"A1": "B²"}, "G2": {"A1": None, "A2": "B1"}}
    assert match_weaknesses(_Canned(json.dumps(odd)), groups) == [None, [None, 0]]
    assert match_weaknesses(_Canned(ProviderError("down")), groups) is None


def _two_runs(latex_project, fake_config, monkeypatch):
    monkeypatch.chdir(fake_config.parent)
    for _ in range(2):
        assert cli.main(["run", str(latex_project), "--config", str(fake_config)]) == 0
    return load_history()


def test_cli_diff_matches_by_meaning_by_default(
    latex_project, fake_statuses, fake_config, model_diff, monkeypatch, capsys
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
    rc = cli.main(["diff"])
    captured = capsys.readouterr()
    out = captured.out
    assert rc == cli.EXIT_OK
    assert "by meaning via" in captured.err
    assert "matched by canned / m1" in out
    assert out.count("- still raised:") == 1
    assert f"{n - 1} of {n} plan items were not re-detected" in out
    assert "Matching is by wording" not in out


def test_cli_diff_falls_back_to_word_overlap(
    latex_project, fake_statuses, fake_config, model_diff, monkeypatch, capsys
):
    _two_runs(latex_project, fake_config, monkeypatch)
    # the fake backend answers with a review, not a plan match
    register_backend("fake", lambda m, cfg, t: PersonaFakeProvider(model="fake-m"))
    capsys.readouterr()
    monkeypatch.setenv("PREBUTTAL_BACKEND", "fake")
    rc = cli.main(["diff", "--llm"])  # the 0.6 flag still works, and says it is not needed
    captured = capsys.readouterr()
    assert rc == cli.EXIT_OK
    assert "model matching failed — fell back to word overlap" in captured.out
    assert "--llm is no longer needed" in captured.err


def test_cli_diff_without_a_usable_backend_says_why(
    latex_project, fake_statuses, fake_config, model_diff, monkeypatch, capsys
):
    _two_runs(latex_project, fake_config, monkeypatch)
    capsys.readouterr()
    monkeypatch.setenv("PREBUTTAL_BACKEND", "relay")
    assert cli.main(["diff"]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert "matching by word overlap: the AC's backend is relay" in captured.err
    assert "heuristic: ≥35% word overlap" in captured.out
