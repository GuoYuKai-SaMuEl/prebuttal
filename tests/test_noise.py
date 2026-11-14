"""The default run-to-run noise (prebuttal/noise.py)."""

import json

import pytest

from prebuttal.noise import DEFAULT_SIGMA_RUN, check_noise, default_sigma, single_run_threshold
from prebuttal.revdiff import compute_diff, render_diff
from prebuttal.runs import RunRecord


def test_default_noise_scales_with_the_venue():
    assert default_sigma(10) == pytest.approx(0.35)
    assert default_sigma(5) == pytest.approx(0.175)
    assert single_run_threshold(10) == pytest.approx(0.99, abs=0.01)


def test_default_is_above_every_measured_value():
    """E measured at most 0.032 of the scale (gemini, demo paper): stay above it."""
    assert DEFAULT_SIGMA_RUN >= 0.032


# ------------------------------------------------------------------ the check


def test_two_single_runs_use_the_default():
    n = check_noise(5.33, 5.67, [], [5.67], 10)  # a single run: one round mean or none
    assert n.delta == 0.34 and n.band == pytest.approx(single_run_threshold(10), abs=0.01)
    assert n.within and n.estimated and not n.measured
    assert not check_noise(4.0, 5.33, [], [], 10).within


def test_measured_rounds_narrow_the_band():
    a = [5.33, 5.67, 5.33, 5.0, 5.67]
    b = [6.0, 5.67, 6.0, 6.33, 6.0]
    n = check_noise(5.4, 6.0, a, b, 10)
    assert n.measured and (n.rounds_a, n.rounds_b) == (5, 5)
    assert n.band < single_run_threshold(10) and not n.within  # +0.6 is real here
    # rounds that happen to agree exactly still leave half the default
    tight = check_noise(5.0, 5.0, [5.0, 5.0, 5.0], [5.0, 5.0, 5.0], 10)
    floor = 2 * (2 * (0.5 * default_sigma(10)) ** 2 / 3) ** 0.5
    assert tight.band == pytest.approx(floor, abs=0.01)


def test_one_side_measured_uses_the_default_for_the_other():
    n = check_noise(5.0, 5.5, [5.0, 5.33, 4.67], [], 10)
    assert (n.rounds_a, n.rounds_b) == (3, 0) and not n.measured and not n.estimated


# ------------------------------------------------------------------ in the diff


def _run(tmp_path, name, mean, round_means=None, scale=10):
    agg = {"mean": mean, "std": 0.5, "rating_scale": scale}
    if round_means is not None:
        agg["round_means"] = round_means
    d = tmp_path / name
    d.mkdir()
    data = {"aggregate": agg, "meta": {"estimated_rating": mean}, "reviewers": []}
    (d / "report.json").write_text(json.dumps(data), encoding="utf-8")
    return RunRecord(
        id=name, ts="2026-11-14T10:00:00", paper_title="P", source="p.pdf", venue="iclr",
        seed=42, mean=mean, std=0.5, n=3, dir=str(d), scale=scale,
    )  # fmt: skip


def test_diff_of_single_runs_says_within_noise_and_how_to_measure(tmp_path):
    a, b = _run(tmp_path, "a", 5.33), _run(tmp_path, "b", 5.67, [5.67])
    out = render_diff(a, b)
    assert "within run-to-run noise (±0.99, estimated — not measured on this paper)" in out
    assert "`repeats = 3` in prebuttal.toml" in out
    assert "not noise-checked" in out and "single reviews — treat as anecdotes" in out


def test_diff_with_repeats_on_both_sides(tmp_path):
    a = _run(tmp_path, "a", 5.4, [5.33, 5.67, 5.33, 5.0, 5.67])
    b = _run(tmp_path, "b", 6.0, [6.0, 5.67, 6.0, 6.33, 6.0])
    out = render_diff(a, b)
    assert "larger than run-to-run noise" in out and "measured: 5 and 5 rounds" in out
    assert "repeats = 3" not in out


def test_no_noise_check_across_scales(tmp_path):
    a, b = _run(tmp_path, "a", 5.0, scale=10), _run(tmp_path, "b", 3.0, scale=5)
    assert compute_diff(a, b).noise is None
    assert "run-to-run noise" not in render_diff(a, b)


def test_the_change_line_after_a_run_gives_the_verdict(
    latex_project, fake_statuses, fake_config, monkeypatch, capsys
):
    from prebuttal import cli

    monkeypatch.chdir(fake_config.parent)
    for _ in range(2):
        assert cli.main(["run", str(latex_project), "--config", str(fake_config)]) == 0
    out = capsys.readouterr().out
    assert "Change:   +0 vs" in out and "— within run-to-run noise (±0.99)" in out
