import pytest

from prebuttal.ingestion.arxiv import parse_arxiv_id
from prebuttal.ingestion.pdf import ingest_pdf_bytes


def test_pdf_basic_structure(sample_pdf_bytes):
    paper = ingest_pdf_bytes(sample_pdf_bytes, source_path="synthetic.pdf")
    assert "Deep Widgets" in paper.title
    assert "widgets" in paper.abstract.lower()
    assert "2.1 points" in paper.abstract

    headings = [s.heading for s in paper.sections]
    assert any(h.startswith("1 Introduction") for h in headings)
    assert any(h.startswith("2 Experiments") for h in headings)
    # abstract must NOT be duplicated as its own section
    assert not any(s.title.lower() == "abstract" for s in paper.sections)

    exp = next(s for s in paper.sections if "Experiments" in s.heading)
    assert "3 seeds" in exp.text


def test_pdf_table_numbers_survive(sample_pdf_bytes):
    paper = ingest_pdf_bytes(sample_pdf_bytes)
    assert len(paper.tables) >= 1
    t = paper.tables[0]
    # grid detection or caption fallback — numbers must survive either way
    blob = t.cell_text + t.raw + t.caption
    assert "97.3" in blob
    assert "Baseline" in blob


def test_pdf_figure_caption(sample_pdf_bytes):
    paper = ingest_pdf_bytes(sample_pdf_bytes)
    assert paper.figures and paper.figures[0].number == "1"
    assert "Accuracy vs" in paper.figures[0].caption


def test_prose_references_are_not_tables_or_figures(sample_pdf_bytes):
    """'Table 9 confirms that ...' is an in-text reference, not a caption."""
    paper = ingest_pdf_bytes(sample_pdf_bytes)
    assert all(t.number != "9" for t in paper.tables)
    assert all(f.number != "2" for f in paper.figures)


def test_parse_arxiv_id():
    assert parse_arxiv_id("https://arxiv.org/abs/2510.12345") == "2510.12345"
    assert parse_arxiv_id("https://arxiv.org/pdf/2510.12345v2") == "2510.12345v2"
    assert parse_arxiv_id("arxiv.org/pdf/2401.12345") == "2401.12345"
    assert parse_arxiv_id("2510.12345") == "2510.12345"
    assert parse_arxiv_id("https://openreview.net/forum?id=xyz") is None
    assert parse_arxiv_id("./local-paper.pdf") is None


def test_arxiv_ingest_offline(tmp_path, sample_pdf_bytes, monkeypatch):
    import prebuttal.ingestion.arxiv as ax

    monkeypatch.setattr(ax, "fetch_pdf_bytes", lambda aid: sample_pdf_bytes)
    monkeypatch.setattr(ax, "fetch_title", lambda aid: "Deep Widgets (arXiv edition)")

    paper = ax.ingest_arxiv("https://arxiv.org/abs/2510.99999")
    assert paper.source_type == "arxiv"
    assert "arXiv edition" in paper.title
    assert paper.tables  # pdf pipeline ran


def test_pdf_ruled_grid_is_cell_accurate(sample_pdf_bytes):
    t = ingest_pdf_bytes(sample_pdf_bytes).tables[0]
    assert t.source == "pdf-table"
    assert t.header == ["Model", "Acc.", "F1"]
    assert t.rows == [["WidgetNet", "97.3", "96.1"], ["Baseline", "95.2", "93.8"]]


def _two_column_booktabs_pdf() -> bytes:
    """Two-column page + a booktabs table (horizontal rules only, the ML default)."""
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    h = A4[1]

    def text(x, y, s, size=9, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x, h - y, s)

    text(50, 60, "Two Column Widgets for Testing", 18, bold=True)
    left = ["1 Introduction"] + [f"Left column sentence {i} about widgets." for i in range(10)]
    right = ["2 Experiments"] + [f"Right column result line {i} here." for i in range(10)]
    for i, s in enumerate(left):
        text(50, 100 + i * 13, s, 12 if i == 0 else 9, bold=i == 0)
    for i, s in enumerate(right):
        text(310, 100 + i * 13, s, 12 if i == 0 else 9, bold=i == 0)

    x0, y0 = 310, 300
    text(x0, y0 - 8, "Table 2: Ablation results on the bench.")
    c.setLineWidth(0.6)
    for yy in (y0, y0 + 16, y0 + 64):
        c.line(x0, h - yy, x0 + 230, h - yy)
    rows = [["Variant", "Acc", "F1"], ["Full model", "91.2", "88.0"], ["No router", "89.5", "86.1"]]
    for r, row in enumerate(rows):
        for col, cell in enumerate(row):
            text(x0 + 3 + (0, 110, 170)[col], y0 + 12 + r * 15 + (2 if r else 0), cell)
    c.showPage()
    c.save()
    return buf.getvalue()


def test_pdf_two_columns_and_booktabs_table():
    paper = ingest_pdf_bytes(_two_column_booktabs_pdf())
    intro = next(s for s in paper.sections if s.title == "Introduction")
    exp = next(s for s in paper.sections if s.title == "Experiments")
    # column-aware layout: the right column must not bleed into the left one
    assert "Left column sentence 9" in intro.text and "Right column" not in intro.text
    assert "Right column result line 9" in exp.text
    t = next(t for t in paper.tables if t.number == "2")
    assert t.source == "pdf-table"
    assert t.header == ["Variant", "Acc", "F1"]
    assert t.rows == [["Full model", "91.2", "88.0"], ["No router", "89.5", "86.1"]]
    assert "Ablation" in t.caption


def _mock_arxiv(monkeypatch, body: bytes, status: int = 200):
    import contextlib

    import httpx

    import prebuttal.ingestion.arxiv as ax

    def handler(request):
        return httpx.Response(status, content=body, headers={"content-type": "application/pdf"})

    @contextlib.contextmanager
    def fake_stream(method, url, **kw):
        kw.pop("timeout", None)
        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            client.stream(method, url, **kw) as r,
        ):
            yield r

    monkeypatch.setattr(ax.httpx, "stream", fake_stream)
    return ax


def test_arxiv_download_is_size_capped(monkeypatch):
    ax = _mock_arxiv(monkeypatch, b"%PDF-" + b"0" * 5000)
    assert ax.fetch_pdf_bytes("2510.12345", max_bytes=10_000).startswith(b"%PDF-")
    with pytest.raises(ax.ArxivError, match="larger than"):
        ax.fetch_pdf_bytes("2510.12345", max_bytes=1000)


def test_arxiv_rejects_non_pdf_and_http_errors(monkeypatch):
    ax = _mock_arxiv(monkeypatch, b"<html>captcha</html>")
    with pytest.raises(ax.ArxivError, match="did not return a PDF"):
        ax.fetch_pdf_bytes("2510.12345")
    ax = _mock_arxiv(monkeypatch, b"", status=404)
    with pytest.raises(ax.ArxivError, match="HTTP 404"):
        ax.fetch_pdf_bytes("2510.12345")


def test_stray_big_glyph_is_not_the_title():
    """Regression (Mamba, 2312.00752): a lone 'M' set larger than the title."""
    from conftest import make_pdf_bytes

    def draw(c, h):
        c.setFont("Helvetica", 22)
        c.drawString(300, h - 250, "M")

    paper = ingest_pdf_bytes(make_pdf_bytes(draw_extra=draw))
    assert paper.title == "Deep Widgets for Structured Prediction"


def test_long_abstract_is_read_whole_without_footnotes():
    """A two-column abstract runs past 24 lines, a footnote can sit between
    its lines, and the rotated arXiv stamp leaves stray glyphs before it."""
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    h = A4[1]

    def text(y: float, s: str, size: float, x: float = 72) -> None:
        c.setFont("Helvetica", size)
        c.drawString(x, h - y, s)

    text(60, "A Paper With a Long Abstract", 18)
    text(90, "Abstract", 12)
    text(100, "v", 14, x=20)  # a letter of the arXiv stamp
    for i in range(30):
        text(110 + i * 12, f"Abstract line {i} says something.", 10)
        if i == 14:
            text(116 + i * 12, "*Equal contribution. first@lab.org", 8)
    text(500, "1 Introduction", 12)
    for i in range(20):
        text(515 + i * 12, f"Body line {i} of the introduction.", 10)
    c.showPage()
    c.save()

    paper = ingest_pdf_bytes(buf.getvalue(), source_path="long.pdf")
    assert paper.abstract.startswith("Abstract line 0 says")
    assert paper.abstract.endswith("Abstract line 29 says something.")
    assert "Equal contribution" not in paper.abstract
    assert "Body line" not in paper.abstract


def _unnumbered_pdf(headings: list[str]) -> bytes:
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    h = A4[1]
    y = 60

    def text(s: str, size: float, font: str = "Helvetica") -> None:
        nonlocal y
        if y > 780:
            c.showPage()
            y = 60
        c.setFont(font, size)
        c.drawString(72, h - y, s)
        y += size + 4

    text("A Journal Paper Without Numbers", 18)
    for name in headings:
        text(name, 12, "Helvetica-Bold")
        for i in range(14):
            text(f"{name} sentence {i} carries the paper's actual argument.", 10)
    c.showPage()
    c.save()
    return buf.getvalue()


def test_unnumbered_journal_headings_keep_the_body():
    names = ["Background", "Methods", "Results", "Discussion", "References"]
    paper = ingest_pdf_bytes(_unnumbered_pdf(names), source_path="journal.pdf")
    assert [s.title for s in paper.sections] == names
    assert "Methods sentence 3" in next(s for s in paper.sections if s.title == "Methods").text


def test_text_before_the_first_recognized_heading_is_kept():
    names = ["Overview", "Our Proposal", "Findings", "References"]  # none recognized but the last
    paper = ingest_pdf_bytes(_unnumbered_pdf(names), source_path="odd.pdf")
    lead = paper.sections[0]
    assert lead.title == "Text before the first detected heading"
    assert "Our Proposal sentence 5" in lead.text and "Findings sentence 13" in lead.text
    assert any("headings may not have been recognized" in w for w in paper.warnings)


def test_roman_numbered_sections_are_not_swallowed_by_the_abstract():
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    h = A4[1]
    y = 60

    def text(s: str) -> None:  # one size throughout, as IEEE sets the body
        nonlocal y
        if y > 780:
            c.showPage()
            y = 60
        c.setFont("Helvetica", 10)
        c.drawString(72, h - y, s)
        y += 13

    text("An IEEE Style Paper With Roman Numerals")
    text("Abstract—We study widgets in the field.")
    for name in ["I. INTRODUCTION", "II. METHODS", "III. RESULTS", "IV. CONCLUSION"]:
        text(name)
        for i in range(20):
            text(f"{name[name.index(' ') + 1 :].title()} line {i} with the real content here.")
    c.showPage()
    c.save()
    paper = ingest_pdf_bytes(buf.getvalue(), source_path="ieee.pdf")
    assert [(s.number, s.title) for s in paper.sections] == [
        ("I", "INTRODUCTION"),
        ("II", "METHODS"),
        ("III", "RESULTS"),
        ("IV", "CONCLUSION"),
    ]
    assert "Methods line" not in paper.abstract
    assert "Conclusion line 19" in paper.sections[-1].text


def test_an_overlong_abstract_hands_the_rest_to_the_body():
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    h = A4[1]
    c.setFont("Helvetica", 10)
    c.drawString(72, h - 60, "A Paper Whose Headings Are Not Found")
    c.drawString(72, h - 80, "Abstract")
    for i in range(55):
        c.drawString(
            72, h - 95 - i * 12, f"Line {i:02d} of a long text that never meets a heading we know."
        )
    c.showPage()
    c.save()
    paper = ingest_pdf_bytes(buf.getvalue(), source_path="long.pdf")
    assert len(paper.abstract) <= 3000
    kept = " ".join(s.text for s in paper.sections)
    assert "Line 54" in kept  # past the abstract's cut: kept, not dropped
