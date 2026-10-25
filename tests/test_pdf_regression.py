"""Regression fixture: a REAL LaTeX-produced PDF (examples/demo-paper compiled
with pdflatex + MiKTeX). Locks the ingestion moat — sections, cell-accurate
numbers — against PDF-parser behavior drift and our own regressions.

To regenerate: cd examples/demo-paper && pdflatex main.tex (twice) and copy
main.pdf to tests/fixtures/demo-paper.pdf.
"""

from pathlib import Path

import pytest

from prebuttal.ingestion.pdf import ingest_pdf_bytes
from prebuttal.pack import render_pack

FIXTURE = Path(__file__).parent / "fixtures" / "demo-paper.pdf"


@pytest.fixture(scope="module")
def paper():
    return ingest_pdf_bytes(FIXTURE.read_bytes(), source_path=str(FIXTURE))


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture PDF not built")
def test_title_is_joined_across_wrapped_lines(paper):
    # the title wraps to two 17pt lines in the PDF; naive pick truncates it
    assert paper.title == "Latent Bottleneck Transformers for Efficient Long-Context Modeling"


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture PDF not built")
def test_latex_sections_with_separate_number_lines(paper):
    got = [(s.number, s.title) for s in paper.sections]
    # pdflatex emits "1" and "Introduction" as separate lines that must merge
    assert ("1", "Introduction") in got
    assert ("2", "Method") in got
    assert ("2.1", "Latent routing") in got
    assert ("3", "Experiments") in got
    assert ("3.2", "Ablations") in got
    assert ("4", "Related work") in got
    assert ("5", "Conclusion") in got
    assert ("", "References") in got
    # table cells must not masquerade as sections (bold numbers in the table)
    assert all(s.number not in {"47.5", "16.1"} for s in paper.sections)


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture PDF not built")
def test_cell_accurate_numbers_survive_kerning(paper):
    """The moat: tab.extract() mangles 47.9 into '479 .' — word-geometry
    assembly must restore every experimental number, signs included."""
    assert len(paper.tables) == 1
    t = paper.tables[0]
    assert t.source == "pdf-table"
    assert t.header[0] == "Model"
    rows = {r[0]: r[1:] for r in t.rows}
    assert rows["Full attention"] == ["47.9", "41.2", "–"]
    assert rows["Linear-attn"] == ["43.1", "12.6", "−4.8"]
    assert rows["Pool-attn"] == ["45.0", "15.9", "−2.9"]
    assert rows["LBT (ours)"] == ["47.5", "16.1", "−0.4"]
    assert "LongBench" in t.caption


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture PDF not built")
def test_abstract_and_figure_caption(paper):
    assert "Transformers scale quadratically" in paper.abstract
    assert "61% less memory" in paper.abstract
    assert len(paper.figures) == 1
    assert paper.figures[0].number == "1"
    assert "Quality vs. context length" in paper.figures[0].caption


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture PDF not built")
def test_reviewer_pack_contains_the_numbers(paper):
    pack = render_pack(paper, budget_chars=40_000)
    # acceptance criterion (plan §7): a reviewer can point at Table 1 numbers
    assert "47.5" in pack and "−0.4" in pack and "Full attention" in pack
