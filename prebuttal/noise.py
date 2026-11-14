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

DEFAULT_SIGMA_RUN = 0.035  # fraction of the rating scale


def default_sigma(scale: float) -> float:
    """The estimated sigma_run of one run, in rating points, on a ``scale``-point scale."""
    return DEFAULT_SIGMA_RUN * scale


def single_run_threshold(scale: float) -> float:
    """A difference below this between two single runs can't be told from chance (~95%):
    the difference of two runs has SD sqrt(2)*sigma_run; 2 SD cover about 95%."""
    return 2 * math.sqrt(2) * default_sigma(scale)
