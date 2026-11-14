"""The default run-to-run noise (prebuttal/noise.py)."""

import pytest

from prebuttal.noise import DEFAULT_SIGMA_RUN, default_sigma, single_run_threshold


def test_default_noise_scales_with_the_venue():
    assert default_sigma(10) == pytest.approx(0.35)
    assert default_sigma(5) == pytest.approx(0.175)
    assert single_run_threshold(10) == pytest.approx(0.99, abs=0.01)


def test_default_is_above_every_measured_value():
    """E measured at most 0.032 of the scale (gemini, demo paper): stay above it."""
    assert DEFAULT_SIGMA_RUN >= 0.032
