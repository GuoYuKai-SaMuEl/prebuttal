"""Offline unit tests for the calibration script's pure helpers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "calibration"))

from calibrate import parse_rating


def test_parse_rating_openreview_strings():
    # OpenReview v2 ratings arrive as anchored strings
    assert parse_rating("6: Marginally above acceptance threshold") == 6.0
    assert parse_rating("  3: Reject — not good enough ") == 3.0
    assert parse_rating("10: Award quality") == 10.0


def test_parse_rating_numbers_and_garbage():
    assert parse_rating(4.5) == 4.5
    assert parse_rating(2) == 2.0
    assert parse_rating(None) is None
    assert parse_rating("no leading number") is None
    assert parse_rating("") is None
