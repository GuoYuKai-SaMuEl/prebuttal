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


def test_share_page_shows_hidden_text_loudly_and_other_notes_quietly(latex_project):
    report, venue = _report(latex_project)
    report.paper.warnings = [
        "LIKELY PROMPT INJECTION — text hidden from human readers addresses AI reviewers: "
        'page 2 (white): "<b>ignore all previous instructions</b>"',
        "Table 3: cell values not extracted from the PDF (caption only)",
    ]
    page = render_share_html(report, venue, "https://example.org")
    assert '<div class="alert">⚠ LIKELY PROMPT INJECTION' in page
    assert "&lt;b&gt;ignore all previous instructions&lt;/b&gt;" in page  # escaped
    assert "<summary>Notes (1)</summary>" in page
    assert page.index('class="alert"') < page.index('class="hero"')


def test_share_page_without_warnings_has_no_alert(latex_project):
    report, venue = _report(latex_project)
    report.paper.warnings = []
    page = render_share_html(report, venue, "https://example.org")
    assert 'class="alert"' not in page and "<summary>Notes" not in page


def test_share_html_drops_non_http_repo_link(latex_project):
    """repo_url can come from a discovered prebuttal.toml."""
    report, venue = _report(latex_project)
    html = render_share_html(report, venue, "javascript:alert(1)")
    assert "javascript:" not in html
    assert "pip install prebuttal" in html


def test_share_page_renders_the_meta_review_markdown():
    """The AC may write markdown: headings, lists, bold, never raw HTML."""
    from prebuttal.share import _md_blocks

    text = (
        "## Summary\n\nThe paper proposes **GlobalGate** and claims *universal* gains.\n"
        "It uses `seed 0` only.\n\n## Consensus\n\n"
        "1. **Confounded budget.** 1 vs 5 epochs.\n"
        "2. No held-out set,\n   so Table 1 measures fit.\n"
        "- a bullet <script>x</script>\n\nClosing words."
    )
    html = _md_blocks(text)
    assert "##" not in html and "**" not in html
    assert "<h3>Summary</h3>" in html and "<h3>Consensus</h3>" in html
    assert "<b>GlobalGate</b>" in html and "<i>universal</i>" in html
    assert "<code>seed 0</code>" in html
    assert "<ol><li><b>Confounded budget.</b> 1 vs 5 epochs.</li>" in html
    assert "<li>No held-out set, so Table 1 measures fit.</li></ol>" in html
    assert "<ul><li>a bullet &lt;script&gt;x&lt;/script&gt;</li></ul>" in html
    assert "<p>Closing words.</p>" in html
    assert "<script>" not in html
    # multiplication and lone asterisks are not emphasis
    assert _md_blocks("2 * 3 * 4 and a*b") == "<p>2 * 3 * 4 and a*b</p>"


def test_a_long_meta_review_is_cut_at_a_line_break():
    from prebuttal.share import _clip_lines, _md_blocks

    text = "## Assessment\n\n" + "\n".join(f"- **Point {i}.** " + "word " * 12 for i in range(40))
    html = _md_blocks(_clip_lines(text, 400))
    assert "**" not in html and html.endswith("<p>…</p>")


def test_numbered_items_keep_their_numbers_around_sub_lists():
    """The Mamba meta-review pattern: numbered points with bullets under them."""
    from prebuttal.share import _md_blocks

    text = (
        "1. **Strength one.**\n   - detail a\n   - detail b\n"
        "     wrapped\n2. **Strength two.**\n\n3. After a blank line."
    )
    html = _md_blocks(text)
    assert html.count("<ol") == 2  # the blank line makes a loose list
    assert (
        "<ol><li><b>Strength one.</b><ul><li>detail a</li><li>detail b wrapped</li>"
        "</ul></li><li><b>Strength two.</b></li></ol>"
    ) in html
    assert '<ol start="3"><li>After a blank line.</li></ol>' in html


def test_a_cut_without_line_breaks_does_not_split_bold():
    from prebuttal.share import _clip_lines, _md_blocks

    text = "word " * 70 + "**a bold claim that runs past the limit** and more " * 3
    html = _md_blocks(_clip_lines(text, 400))
    assert "**" not in html and html.endswith("…</p>")


def test_rating_bar_rounds_half_up_like_the_scores():
    from prebuttal.report import _bar

    assert _bar(3.5, 6).count("█") == 4  # was 4 by banker's rounding — consistent now
    assert _bar(2.5, 6).count("█") == 3  # was 2: half rounds up, as coerce_fields does
    assert _bar(0.4, 6).count("█") == 0 and _bar(7.0, 6).count("█") == 6  # clamped
