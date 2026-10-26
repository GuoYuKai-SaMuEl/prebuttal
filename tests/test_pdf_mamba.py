"""Regression on real two-column ML-paper pages: Mamba v1 / v2 (CC BY 4.0,
see tests/fixtures/README.md).  Before the rule-band rewrite 8 of these 13
tables came out empty and a ghost "t7" table appeared."""

from pathlib import Path

import pytest

from prebuttal.ingestion.pdf import ingest_pdf_bytes
from prebuttal.pack import render_pack

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def v1():
    return ingest_pdf_bytes((FIX / "mamba-v1-tables.pdf").read_bytes())


@pytest.fixture(scope="module")
def v2():
    return ingest_pdf_bytes((FIX / "mamba-v2-tables.pdf").read_bytes())


def _t(paper, number):
    t = next((t for t in paper.tables if t.number == number), None)
    assert t is not None, f"Table {number} missing"
    return t


def test_every_table_has_cells_and_none_is_unnamed(v1, v2):
    assert sorted(int(t.number) for t in v1.tables) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert sorted(int(t.number) for t in v2.tables) == [1, 2, 13, 14]
    for t in [*v1.tables, *v2.tables]:
        assert t.source == "pdf-table" and t.rows, f"Table {t.number}"
    assert not v1.warnings and not v2.warnings


def test_big_table_stays_cell_accurate(v1):
    t = _t(v1, "3")
    assert len(t.rows) == 25 and len(t.header) == 11
    row = next(r for r in t.rows if r[0] == "Mamba-1.4B")
    assert row == ["Mamba-1.4B", "NeoX", "6.80", "5.04", "64.9", "59.1", "74.2", "65.5",
                   "32.8", "61.5", "59.7"]  # fmt: skip


def test_left_column_table_between_right_column_rules(v1):
    t = _t(v1, "4")  # SC09: its rules interleave with Table 5's
    assert t.header == ["Model", "Params", "NLL↓", "FID↓", "IS↑", "mIS↑", "AM↓"]
    assert ["Mamba", "24.3M", "1.860", "0.67", "7.33", "144.9", "0.36"] in t.rows


def test_four_ablation_tables_on_one_page(v1):
    six = _t(v1, "6")  # two side-by-side panels under one caption
    assert ["H3", "H3", "S4(complex)", "10.30"] in six.rows
    assert ["Mamba", "Mamba", "S6", "8.69"] in six.rows
    assert _t(v1, "7").rows[-1] == ["✓", "✓", "✓", "8.71"]  # pifont check marks
    assert any(r[1:] == ["Real", "8.71"] for r in _t(v1, "8").rows)
    assert ["64", "371.5", "8.71"] in _t(v1, "9").rows
    assert len(_t(v1, "10").rows) == 10


def test_caption_below_table_is_not_taken_by_the_plot_under_it(v2):
    # v2 p.11 puts Table 1/2 captions below the tables, right above a boxed plot
    assert ["Mamba", "Mamba", "S6", "99.8"] in _t(v2, "1").rows
    assert _t(v2, "13").rows[-1][:2] == ["Mamba", "7M"]


def test_pack_has_no_extraction_caveat_when_all_tables_parsed(v1):
    assert "[numbers not extracted]" not in render_pack(v1)
