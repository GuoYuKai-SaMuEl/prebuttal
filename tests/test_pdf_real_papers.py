"""Table extraction on real ML papers, downloaded on demand (see
tests/fixtures/README.md).  Skipped unless PREBUTTAL_REAL_PAPERS=1 or the PDFs
are already cached.

Mamba v1/v2 (arXiv:2312.00752, CC BY 4.0): two-column ablation pages, rules
of neighbouring columns interleaving, side-by-side panels, captions below a
table right above a boxed plot.  Before the rule-band rewrite 7 / 8 of their
15 tables came out empty and an unnamed ghost table appeared.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from prebuttal.ingestion.pdf import ingest_pdf_bytes
from prebuttal.pack import render_pack


def _cache_dir() -> Path:
    env = os.environ.get("PREBUTTAL_PAPER_CACHE")
    return Path(env) if env else Path.home() / ".cache" / "prebuttal" / "test-papers"


def _paper_pdf(arxiv_id: str) -> bytes:
    path = _cache_dir() / f"{arxiv_id}.pdf"
    if path.is_file():
        return path.read_bytes()
    if os.environ.get("PREBUTTAL_REAL_PAPERS") != "1":
        pytest.skip("set PREBUTTAL_REAL_PAPERS=1 to download real-paper fixtures")
    import httpx

    r = httpx.get(
        f"https://arxiv.org/pdf/{arxiv_id}",
        follow_redirects=True,
        timeout=60,
        headers={"User-Agent": "prebuttal-tests (https://github.com/GuoYuKai-SaMuEl/prebuttal)"},
    )
    r.raise_for_status()
    assert r.content.startswith(b"%PDF"), f"arXiv returned no PDF for {arxiv_id}"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(r.content)
    tmp.replace(path)
    return r.content


@pytest.fixture(scope="module")
def v1():
    return ingest_pdf_bytes(_paper_pdf("2312.00752v1"))


@pytest.fixture(scope="module")
def v2():
    return ingest_pdf_bytes(_paper_pdf("2312.00752v2"))


def _t(paper, number):
    t = next((t for t in paper.tables if t.number == number), None)
    assert t is not None, f"Table {number} missing"
    return t


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_every_table_has_cells_and_none_is_unnamed(version, request):
    paper = request.getfixturevalue(version)
    assert [t.number for t in paper.tables] == [str(n) for n in range(1, 16)]
    for t in paper.tables:
        assert t.source == "pdf-table" and t.rows, f"Table {t.number}"
    assert not paper.warnings
    assert "[numbers not extracted]" not in render_pack(paper)


def test_big_table_stays_cell_accurate(v1):
    t = _t(v1, "3")
    assert len(t.rows) == 25 and len(t.header) == 11
    row = next(r for r in t.rows if r[0] == "Mamba-1.4B")
    assert row == ["Mamba-1.4B", "NeoX", "6.80", "5.04", "64.9", "59.1", "74.2", "65.5",
                   "32.8", "61.5", "59.7"]  # fmt: skip


def test_left_column_table_between_right_column_rules(v1):
    t = _t(v1, "4")  # SC09: its rules interleave with Table 5's
    assert t.header == ["Model", "Params", "NLL ↓", "FID ↓", "IS ↑", "mIS ↑", "AM ↓"]
    assert ["Mamba", "24.3M", "1.860", "0.67", "7.33", "144.9", "0.36"] in t.rows


def test_four_ablation_tables_on_one_page(v1):
    six = _t(v1, "6")  # two side-by-side panels under one caption
    assert ["H3", "H3", "S4 (complex)", "10.30"] in six.rows
    assert ["Mamba", "Mamba", "S6", "8.69"] in six.rows
    assert _t(v1, "7").rows[-1] == ["✓", "✓", "✓", "8.71"]  # pifont check marks
    assert any(r[1:] == ["Real", "8.71"] for r in _t(v1, "8").rows)
    assert ["64", "371.5", "8.71"] in _t(v1, "9").rows
    assert len(_t(v1, "10").rows) == 10


def test_caption_below_table_is_not_taken_by_the_plot_under_it(v2):
    # v2 p.11 puts Table 1/2 captions below the tables, right above a boxed plot
    assert ["Mamba", "Mamba", "S6", "99.8"] in _t(v2, "1").rows
    assert _t(v2, "13").rows[-1][:2] == ["Mamba", "7M"]
