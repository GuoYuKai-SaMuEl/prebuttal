"""How much a run's predicted score moves by chance (run-to-run noise).

sigma_run is the standard deviation of the panel mean between runs of the same
paper with the same settings. It is kept as a fraction of the rating scale so
that it carries across venues (0.035 of a 10-point scale = 0.35 points).

A single run cannot measure it, so the default below stands in, and reports
call it "estimated". A run with `repeats` measures it for its own paper.

Where the default comes from (prebuttal's E measurements, ICLR form):

- 2026-11-14, Mamba v1/v2, 5 runs each:
  agent-codex 0.026, agent-claude 0.021, api-gemini (flash-lite) 0.000
  (it gave 8 every time: a strong paper stuck on one anchor).
- 2026-11-14, examples/demo-paper (a weak-to-borderline paper), 2 runs x
  `repeats = 5`: api-gemini (flash-lite) 0.032, agent-codex 0.010 (3 nearly
  every time: again stuck on an anchor).

A measured 0 or 0.01 is the scale's coarse anchors (ICLR: 1, 3, 5, 6, 8, 10),
not a steady reviewer: a paper nearer a boundary moves a whole step. So one
default for every backend, a little above the largest measured value.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

DEFAULT_SIGMA_RUN = 0.035  # fraction of the rating scale
# a measured spread is trusted down to half the default: three rounds that
# happen to agree must not make the band implausibly narrow
MEASURED_FLOOR = 0.5


def default_sigma(scale: float) -> float:
    """The estimated sigma_run of one run, in rating points, on a ``scale``-point scale."""
    return DEFAULT_SIGMA_RUN * scale


def single_run_threshold(scale: float) -> float:
    """A difference below this between two single runs can't be told from chance (~95%):
    the difference of two runs has SD sqrt(2)*sigma_run; 2 SD cover about 95%."""
    return 2 * math.sqrt(2) * default_sigma(scale)


@dataclass(frozen=True)
class NoiseCheck:
    """Whether the change of the predicted score between two runs (A -> B)
    can be told from run-to-run noise.

    ``rounds_a`` / ``rounds_b``: rounds that measured the noise on each side
    (0 = a single run, which uses the default)."""

    delta: float
    band: float  # |delta| below this can't be told from chance (~95%)
    rounds_a: int
    rounds_b: int

    @property
    def within(self) -> bool:
        return abs(self.delta) < self.band

    @property
    def measured(self) -> bool:
        """Measured on both sides (`repeats` in both runs)."""
        return bool(self.rounds_a and self.rounds_b)

    @property
    def estimated(self) -> bool:
        """Measured on neither side: the default alone."""
        return not (self.rounds_a or self.rounds_b)


def _side(round_means: Sequence[float], scale: float) -> tuple[float, int]:
    """(variance of this side's mean, rounds that measured it)."""
    default = default_sigma(scale)
    if len(round_means) < 2:
        return default**2, 0
    s = max(statistics.stdev(round_means), MEASURED_FLOOR * default)
    k = len(round_means)
    return s**2 / k, k


def check_noise(
    mean_a: float, mean_b: float, round_means_a: Sequence[float],
    round_means_b: Sequence[float], scale: float,
) -> NoiseCheck:  # fmt: skip
    """Compare two predicted scores on one ``scale``-point scale.

    A side with two or more rounds uses the spread of its round means (its
    mean's standard error); a single run uses the default. The band is two
    standard errors of the difference."""
    var_a, ra = _side(round_means_a, scale)
    var_b, rb = _side(round_means_b, scale)
    return NoiseCheck(
        delta=round(mean_b - mean_a, 2),
        band=round(2 * math.sqrt(var_a + var_b), 2),
        rounds_a=ra,
        rounds_b=rb,
    )
