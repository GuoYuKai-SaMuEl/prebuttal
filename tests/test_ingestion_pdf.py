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
