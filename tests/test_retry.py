"""`prebuttal retry`: only the failed reviewers (and the AC) run again."""

import json

import pytest
from conftest import FAKE_TOML, PersonaFakeProvider

from prebuttal import cli
from prebuttal.providers import register_backend
from prebuttal.providers.base import ProviderError
from prebuttal.runs import load_history


class _Flaky(PersonaFakeProvider):
    """Fails while ``down`` is set, like an overloaded backend."""

    down = True

    def _complete(self, **kw):
        if _Flaky.down:
            raise ProviderError("HTTP 503: overloaded")
        return super()._complete(**kw)


@pytest.fixture
def flaky_config(tmp_path, monkeypatch):
    calls: list[dict] = []
    _Flaky.down = True
    register_backend("flaky", lambda m, cfg, t: _Flaky(backend="flaky", calls=calls))
    register_backend("fake", lambda m, cfg, t: PersonaFakeProvider(model="fake-m", calls=calls))
    toml = FAKE_TOML.replace(
        'id = "R2"\npersona = "adversarial"\nbackend = "fake"',
        'id = "R2"\npersona = "adversarial"\nbackend = "flaky"',
    )
    p = tmp_path / "prebuttal.toml"
    p.write_text(toml, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return p, calls


def test_retry_reruns_only_the_failed_reviewer(latex_project, fake_statuses, flaky_config, capsys):
    cfg_path, calls = flaky_config
    rc = cli.main(["run", str(latex_project), "--config", str(cfg_path), "--out-dir", "r"])
    assert rc == cli.EXIT_PARTIAL
    assert "prebuttal retry" in capsys.readouterr().err  # the hint names the command
    first = load_history()[0]
    assert (first.dir_path / "pack.md").is_file()

    _Flaky.down = False
    calls.clear()
    assert cli.main(["retry"]) == cli.EXIT_OK

    # one reviewer call + one AC call, nothing else re-paid
    reviewer_calls = [c for c in calls if "estimated_rating" not in c["system"]]
    assert len(reviewer_calls) == 1 and "Reviewer 2" in reviewer_calls[0]["system"]
    assert len(calls) == 2

    hist = load_history()
    assert len(hist) == 2 and hist[0].project == first.project
    assert hist[0].note == f"retry of {first.label}"
    new = json.loads((hist[0].dir_path / "report.json").read_text(encoding="utf-8"))
    old = json.loads((first.dir_path / "report.json").read_text(encoding="utf-8"))
    assert all(r["parse_ok"] for r in new["reviewers"])
    # R1/R3 are reused verbatim; R2 kept its seed; the pack is byte-identical
    assert new["reviewers"][0]["raw_output"] == old["reviewers"][0]["raw_output"]
    assert new["reviewers"][1]["seed"] == old["reviewers"][1]["seed"]
    assert new["run"]["pack_sha256"] == old["run"]["pack_sha256"]
    assert new["paper"]["sections"] == old["paper"]["sections"] > 0


def test_retry_with_nothing_failed(latex_project, fake_statuses, fake_config, monkeypatch, capsys):
    monkeypatch.chdir(fake_config.parent)
    assert cli.main(["run", str(latex_project), "--config", str(fake_config)]) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(["retry"]) == cli.EXIT_OK
    assert "nothing to retry" in capsys.readouterr().out
    assert len(load_history()) == 1


def test_retry_of_a_run_without_archived_text_is_refused(
    latex_project, fake_statuses, flaky_config, capsys
):
    cfg_path, _calls = flaky_config
    cli.main(["run", str(latex_project), "--config", str(cfg_path), "--out-dir", "r"])
    rec = load_history()[0]
    (rec.dir_path / "pack.md").unlink()  # as archived by 0.3.1 and earlier
    _Flaky.down = False
    capsys.readouterr()
    assert cli.main(["retry", rec.id]) == cli.EXIT_USAGE
    assert "start a new run" in capsys.readouterr().err


def test_ctrl_c_saves_finished_reviews_for_retry(
    latex_project, fake_statuses, flaky_config, capsys
):
    """Ctrl-C mid-run keeps the (paid) reviews that finished; retry completes it."""
    import _thread
    import threading

    cfg_path, calls = flaky_config
    release = threading.Event()

    class _Hung(PersonaFakeProvider):
        def _complete(self, **kw):
            # the two other reviewers are done: the user presses Ctrl-C now
            threading.Timer(0.2, _thread.interrupt_main).start()
            release.wait(10)
            return super()._complete(**kw)

    register_backend("hung", lambda m, cfg, t: _Hung(backend="hung", calls=calls))
    _Flaky.down = False
    toml = cfg_path.read_text(encoding="utf-8").replace(
        'persona = "detail_obsessive"\nbackend = "fake"',
        'persona = "detail_obsessive"\nbackend = "hung"',
    )
    cfg_path.write_text(toml, encoding="utf-8")
    try:
        rc = cli.main(["run", str(latex_project), "--config", str(cfg_path), "--out-dir", "r"])
    finally:
        release.set()
    assert rc == 130
    err = capsys.readouterr().err
    assert "saving the reviews that finished" in err and "prebuttal retry" in err

    rec = load_history()[0]
    assert rec.note == "interrupted"
    data = json.loads((rec.dir_path / "report.json").read_text(encoding="utf-8"))
    assert [r["parse_ok"] for r in data["reviewers"]] == [True, True, False]
    assert "interrupted" in data["reviewers"][2]["error"]

    # the backend recovers; retry re-runs R3 on it as archived
    register_backend("hung", lambda m, cfg, t: PersonaFakeProvider(backend="hung", calls=calls))
    assert cli.main(["retry"]) == cli.EXIT_OK
