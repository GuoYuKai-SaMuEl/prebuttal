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
