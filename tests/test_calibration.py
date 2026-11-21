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


class _Note:
    def __init__(self, nid, content, replies):
        self.id, self.content, self.details = nid, content, {"replies": replies}


class _Client:
    """openreview-py's API v2 client, as far as the script uses it."""

    def __init__(self):
        self.attachments = []

    def get_all_notes(self, invitation, details):
        review = {"content": {"rating": {"value": "6: Marginally above"}}}
        return [
            _Note("p1", {"title": {"value": "A"}, "pdf": {"value": "/pdf/abc.pdf"}}, [review] * 2),
            _Note("p2", {"title": {"value": "No PDF"}}, [review] * 2),  # skipped
        ]

    def get_attachment(self, field_name, id=None, group_id=None, invitation_id=None):
        self.attachments.append((field_name, id))
        return b"%PDF-1.4"


def test_openreview_v2_notes_and_attachments():
    from calibrate import fetch_calibration_set, fetch_pdf

    client = _Client()
    (entry,) = fetch_calibration_set("ICLR.cc/2024/Conference", 5, client=client)
    assert entry["id"] == "p1" and entry["pdf"] == "/pdf/abc.pdf" and entry["true_mean"] == 6.0
    assert fetch_pdf(client, "ICLR.cc/2024/Conference", entry) == b"%PDF-1.4"
    assert client.attachments == [("pdf", "p1")]
