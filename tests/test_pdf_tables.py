"""Booktabs table detection on hard page layouts (synthetic PDFs, reportlab).

Each case reproduces a failure seen on a real two-column ML paper (Mamba v1):
rules of neighbouring columns interleaving, tables stacked in one column,
captions far from a tall table's centre, rule pairs without a caption.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import pytest

from prebuttal.ingestion.pdf import _TABLE_CAP, _number_key, ingest_pdf_bytes
from prebuttal.pack import render_pack

ROW_H = 13


@pytest.mark.parametrize(
    ("line", "number"),
    [
        ("Table 3: Results.", "3"),
        ("Table 3.1: Results on LAMBADA.", "3.1"),  # GPT-3 style
        ("Table A.2: More ablations.", "A.2"),
        ("Table S1: Supplementary.", "S1"),
        ("Table 1. We report", "1"),
        ("Table 1 confirms that", None),  # in-prose reference
        ("Table 1.5 shows", None),
    ],
)
def test_caption_numbers(line, number):
    m = _TABLE_CAP.match(line)
    assert (m.group(1) if m else None) == number


def test_table_numbers_sort_naturally():
    nums = ["10", "A.1", "3.1", "2", "S1", "3"]
    assert sorted(nums, key=_number_key) == ["2", "3", "3.1", "10", "A.1", "S1"]


@dataclass
class Tab:
    x: float  # left edge
    y: float  # top rule, in points from the top of the page
    width: float
    rows: list[list[str]]
    cols: tuple[float, ...]  # column offsets from x
    caption: str = ""
    below: bool = False  # caption under the table instead of above
    extra_rules: list[tuple[float, float, float]] = field(default_factory=list)

    @property
    def bottom(self) -> float:
        return self.y + 4 + len(self.rows) * ROW_H + 4


def _pdf(pages: list[list[Tab]], captions: list[list[tuple[float, float, str]]] | None = None):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    h = A4[1]

    def text(x, y, s, size=8):
        c.setFont("Helvetica", size)
        c.drawString(x, h - y, s)

    for p, tabs in enumerate(pages):
        if p == 0:
            text(50, 50, "Synthetic Tables Paper", 16)
            text(50, 80, "1 Introduction", 11)
            text(50, 94, "Some prose so the page has a body.")
        for t in tabs:
            c.setLineWidth(0.6)
            mid = t.y + 4 + ROW_H
            for yy in (t.y, mid, t.bottom):
                c.line(t.x, h - yy, t.x + t.width, h - yy)
            for x0, x1, yy in t.extra_rules:
                c.line(x0, h - yy, x1, h - yy)
            for r, row in enumerate(t.rows):
                base = t.y + 4 + r * ROW_H + 9 + (3 if r else 0)
                for col, cell in enumerate(row):
                    text(t.x + 2 + t.cols[col], base, cell)
            if t.caption:
                cy = t.bottom + 12 if t.below else t.y - 6
                text(t.x, cy, t.caption)
        for x, y, s in (captions or [[]] * len(pages))[p] if captions else []:
            text(x, y, s)
        c.showPage()
    c.save()
    return buf.getvalue()


def _table(paper, number):
    return next((t for t in paper.tables if t.number == number), None)


def _rows(n, cols, tag):
    return [[f"{tag}{r}"] + [f"{r}.{k}" for k in range(1, cols)] for r in range(n)]


def test_interleaved_column_rules_do_not_split_tables():
    # the right-column table's rules fall between the left table's rules
    left = Tab(
        50,
        400,
        230,
        [["Model", "FID", "IS"], *_rows(6, 3, "L")],
        (0, 120, 180),
        "Table 4: Left column results.",
    )
    right = Tab(
        310,
        420,
        230,
        [["Variant", "Acc"], *_rows(2, 2, "R")],
        (0, 150),
        "Table 5: Right column results.",
    )
    paper = ingest_pdf_bytes(_pdf([[left, right]]))
    t4, t5 = _table(paper, "4"), _table(paper, "5")
    assert t4 is not None and t4.source == "pdf-table"
    assert t4.header == ["Model", "FID", "IS"]
    assert len(t4.rows) == 6 and t4.rows[-1] == ["L5", "5.1", "5.2"]
    assert t5 is not None and t5.source == "pdf-table"
    assert t5.rows == [["R0", "0.1"], ["R1", "1.1"]]


def test_stacked_tables_in_one_column_are_separated_by_captions():
    a = Tab(
        50,
        140,
        230,
        [["A", "x", "y"], *_rows(2, 3, "a")],
        (0, 100, 170),
        "Table 6: First ablation.",
    )
    b = Tab(
        50,
        230,
        230,
        [["B", "p", "q", "r"], *_rows(3, 4, "b")],
        (0, 60, 120, 180),
        "Table 7: Second ablation.",
    )
    c = Tab(50, 330, 230, [["C", "u"], *_rows(2, 2, "c")], (0, 140), "Table 8: Third.", below=True)
    d = Tab(
        50,
        430,
        230,
        [["D", "v", "w"], *_rows(2, 3, "d")],
        (0, 90, 160),
        "Table 10: Fourth.",
        below=True,
    )
    paper = ingest_pdf_bytes(_pdf([[a, b, c, d]]))
    for num, header, n in (
        ("6", ["A", "x", "y"], 2),
        ("7", ["B", "p", "q", "r"], 3),
        ("8", ["C", "u"], 2),
        ("10", ["D", "v", "w"], 2),
    ):
        t = _table(paper, num)
        assert t is not None and t.source == "pdf-table", num
        assert t.header == header, num
        assert len(t.rows) == n, num


def test_full_width_table_does_not_swallow_column_tables():
    wide = Tab(
        50,
        120,
        495,
        [["Model", "a", "b", "c", "d"], *_rows(3, 5, "w")],
        (0, 150, 250, 350, 430),
        "Table 1: Full-width table.",
    )
    left = Tab(50, 300, 230, [["L", "m"], *_rows(2, 2, "l")], (0, 150), "Table 2: Left.")
    right = Tab(310, 300, 230, [["R", "n"], *_rows(2, 2, "r")], (0, 150), "Table 3: Right.")
    paper = ingest_pdf_bytes(_pdf([[wide, left, right]]))
    t1, t2, t3 = (_table(paper, n) for n in "123")
    assert t1 is not None and t1.header == ["Model", "a", "b", "c", "d"] and len(t1.rows) == 3
    assert t2 is not None and t2.rows == [["l0", "0.1"], ["l1", "1.1"]]
    assert t3 is not None and t3.rows == [["r0", "0.1"], ["r1", "1.1"]]


def test_tall_table_keeps_its_caption():
    tall = Tab(
        50,
        120,
        495,
        [["Model", "ppl", "acc"], *_rows(24, 3, "m")],
        (0, 250, 400),
        "Table 3: A tall results table.",
    )
    paper = ingest_pdf_bytes(_pdf([[tall]]))
    t = _table(paper, "3")
    assert t is not None and t.source == "pdf-table" and len(t.rows) == 24
    assert "tall results" in t.caption


def test_cmidrule_inside_a_table_does_not_break_it():
    t = Tab(
        50,
        200,
        300,
        [["Model", "acc", "f1"], *_rows(3, 3, "k")],
        (0, 150, 230),
        "Table 2: With a partial rule.",
    )
    t.extra_rules.append((200, 350, t.y + 4 + 2 * ROW_H + 1))  # \cmidrule-like
    paper = ingest_pdf_bytes(_pdf([[t]]))
    got = _table(paper, "2")
    assert got is not None and got.header == ["Model", "acc", "f1"] and len(got.rows) == 3


def test_ruled_block_without_caption_is_not_a_table():
    ghost = Tab(50, 200, 300, [["Some", "boxed", "text"], *_rows(2, 3, "g")], (0, 120, 220))
    paper = ingest_pdf_bytes(_pdf([[ghost]]))
    assert paper.tables == []


def test_caption_only_table_is_flagged_for_reviewers():
    paper = ingest_pdf_bytes(
        _pdf([[]], captions=[[(50, 300, "Table 9: Numbers drawn as an image.")]])
    )
    t = _table(paper, "9")
    assert t is not None and t.source == "pdf-caption-block"
    assert any("Table 9" in w and "not extracted" in w for w in paper.warnings)
    pack = render_pack(paper)
    assert "[numbers not extracted" in pack
    assert "not a flaw of the paper" in pack
