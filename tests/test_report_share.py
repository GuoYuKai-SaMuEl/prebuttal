import json

from conftest import PersonaFakeProvider

from prebuttal.config import load_config
from prebuttal.ingestion import ingest
from prebuttal.orchestrator import run_report
from prebuttal.pack import render_pack
from prebuttal.report import dumps_json, render_markdown
from prebuttal.share import render_share_html
from prebuttal.venues import get_venue


def _report(latex_project):
    cfg = load_config(None)
    venue = get_venue("iclr")
    paper = ingest(str(latex_project))
    render_pack(paper, budget_chars=60_000)
    providers = {r.id: PersonaFakeProvider() for r in cfg.reviewers}
    ac = PersonaFakeProvider()
    return run_report(paper, cfg, venue, providers, ac, log=lambda m: None), venue


def test_markdown_report(latex_project):
    report, venue = _report(latex_project)
    md = render_markdown(report, venue)

    assert report.paper.title in md
    assert "Predicted outcome" in md
    assert "6 / 10" in md
    assert "Questions to the Authors" in md  # venue-form fidelity
    assert "Limitations" in md  # ICLR-specific field
    assert "Backend transparency" in md
    assert "stress test, not a score predictor" in md
    # per-reviewer backend annotation (honesty requirement)
    for rev in report.reviews:
        assert rev.backend in md
    assert report.meta.backend in md  # AC backend listed too


def test_json_report_round_trip(latex_project):
    report, venue = _report(latex_project)
    data = json.loads(dumps_json(report, venue))
    assert data["venue"]["key"] == "iclr"
    assert data["aggregate"]["mean"] == 6.0
    assert data["aggregate"]["rating_scale"] == 10
    assert len(data["reviewers"]) == 3
    assert data["reviewers"][0]["rating_label"]  # anchor label attached
    assert data["meta"]["estimated_rating"] == 5.5
    assert "not a prediction" in data["notice"] or "not a score predictor" in data["notice"]
    assert data["run"]["pack_sha256"]


def test_share_html(latex_project):
    report, venue = _report(latex_project)
    html = render_share_html(report, venue, "https://github.com/x/prebuttal")

    assert report.paper.title in html
    assert "pip install prebuttal" in html
    assert "https://github.com/x/prebuttal" in html
    assert "6/10" in html  # per-reviewer chips
    assert "Meta-review" in html
    assert "goatcounter" not in html.lower()  # analytics belong to the site only


def test_params_not_applied_are_not_shown(latex_project):
    report, venue = _report(latex_project)
    for rev in report.reviews:
        rev.backend = "agent-claude"
    report.meta.backend = "api-anthropic"
    md = render_markdown(report, venue)
    assert "temp n/a · seed n/a" in md
    assert "| `api-anthropic` | `fake-1` | default | n/a | n/a |" in md
    assert "does not take this parameter" in md

    data = json.loads(dumps_json(report, venue))
    assert data["reviewers"][0]["temperature_applied"] is False
    assert data["meta"]["temperature_applied"] is False
    assert data["meta"]["seed_applied"] is False
    assert "· seed" not in render_share_html(report, venue, "https://x")


def test_params_applied_are_shown(latex_project):
    report, venue = _report(latex_project)
    md = render_markdown(report, venue)
    assert "n/a = the backend" not in md
    assert "· seed 42" in render_share_html(report, venue, "https://x")


def test_share_html_escapes_malicious_title():
    from prebuttal.models import (
        MetaReview,
        ReviewReport,
        RunInfo,
        StructuredPaper,
        make_aggregate,
    )

    paper = StructuredPaper(
        title='<script>alert("x")</script>',
        abstract="",
        source_type="latex",
        source_path="x",
    )
    reviews = []
    report = ReviewReport(
        paper=paper,
        venue_key="iclr",
        reviews=reviews,
        meta=MetaReview(
            backend="b", model="m", temperature=0.3, parse_ok=True, meta_review="meta & <b>text</b>"
        ),
        aggregate=make_aggregate(reviews),
        run=RunInfo(venue="iclr", seed=1),
    )
    html = render_share_html(report, get_venue("iclr"), "https://x")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;" in html
