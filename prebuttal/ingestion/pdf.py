"""PDF ingestion via pdfminer.six + pdfplumber: sections, cell-level tables,
figure captions.

Both libraries are MIT-licensed, which keeps the package's dependency tree
compatible with its own MIT license (PyMuPDF, used before 0.1.1, is AGPL).

Table strategy: fully ruled grids via ``page.find_tables`` and booktabs-style
tables (horizontal rules only — the ML-paper default) via rule clustering +
column whitespace; captions matched by proximity; any numbered "Table N"
caption without a detected grid falls back to a verbatim caption-block so
experimental numbers survive.
"""

from __future__ import annotations

import io
import re
import statistics
from itertools import pairwise

from ..models import Figure, Section, StructuredPaper, Table


class PDFError(Exception):
    pass


_HEADING_WORDS = {
    "abstract",
    "introduction",
    "references",
    "acknowledgments",
    "acknowledgements",
    "appendix",
    "conclusion",
    "conclusions",
    "bibliography",
}
_NUMBERED = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(\S.*)$")
# A real caption has punctuation right after the number ("Table 3: ...", "Fig. 2.");
# in-prose references like "Table 1 confirms that ..." must NOT match.
_TABLE_CAP = re.compile(r"^\s*(?:table|tab\.)\s*(\d{1,3})(?:[a-z])?\s*[:.)]\s+(\S.*)$", re.I)
_FIG_CAP = re.compile(r"^\s*(?:figure|fig\.)\s*(\d{1,3})(?:[a-z])?\s*[:.)]\s+(\S.*)$", re.I)


def _norm(s: str) -> str:
    return " ".join(s.split())


def _cluster(vals: list[float], tol: float = 2.5) -> list[float]:
    groups: list[list[float]] = []
    for v in sorted(vals):
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


_CID = re.compile(r"\(cid:\d+\)")


def _nearest(vals: list[float], v: float) -> int:
    return min(range(len(vals)), key=lambda k: abs(vals[k] - v))


def _grid_from_cells(cells: list[tuple], words: list[dict]) -> list[list[str]] | None:
    """Rebuild table cells from word coordinates.

    Words keep their spelling (kerned LaTeX decimals stay "47.9"); assigning
    them to cell boxes by center point and sorting by x gives the cell text.
    """
    if not cells:
        return None
    row_y = _cluster([c[1] for c in cells])
    col_x = _cluster([c[0] for c in cells])
    if not row_y or not col_x:
        return None
    grid = [["" for _ in col_x] for _ in row_y]
    cell_words: dict[tuple[int, int], list[tuple[float, str]]] = {}
    for w in words:
        cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
        for x0, y0, x1, y1 in cells:
            if x0 - 0.5 <= cx <= x1 + 0.5 and y0 - 0.5 <= cy <= y1 + 0.5:
                key = (_nearest(row_y, y0), _nearest(col_x, x0))
                cell_words.setdefault(key, []).append((w["x0"], w["text"]))
                break
    for (r, c), ws in cell_words.items():
        grid[r][c] = " ".join(text for _x, text in sorted(ws))
    return grid


def _rule_regions(page) -> list[tuple[float, float, float, float]]:
    """Bounding boxes of booktabs-style tables: stacks of >= 2 horizontal
    rules spanning (nearly) the same x-range, close together vertically."""
    rules = sorted(
        (e for e in page.horizontal_edges if e["x1"] - e["x0"] >= 40),
        key=lambda e: e["top"],
    )
    regions: list[tuple[float, float, float, float]] = []
    group: list[dict] = []

    def _flush() -> None:
        if len(group) >= 2:
            regions.append(
                (
                    min(e["x0"] for e in group),
                    group[0]["top"],
                    max(e["x1"] for e in group),
                    group[-1]["bottom"],
                )
            )

    for e in rules:
        if group:
            gx0, gx1 = min(g["x0"] for g in group), max(g["x1"] for g in group)
            overlap = min(gx1, e["x1"]) - max(gx0, e["x0"])
            span = min(gx1 - gx0, e["x1"] - e["x0"])
            if overlap >= 0.8 * span and e["top"] - group[-1]["top"] <= 300:
                group.append(e)
                continue
            _flush()
        group = [e]
    _flush()
    return regions


def _grid_from_region(bbox: tuple, words: list[dict]) -> list[list[str]] | None:
    """Rows by baseline, columns by whitespace shared across every row."""
    x0, top, x1, bottom = bbox
    inside = [
        w
        for w in words
        if x0 - 2 <= (w["x0"] + w["x1"]) / 2 <= x1 + 2
        and top < (w["top"] + w["bottom"]) / 2 < bottom
    ]
    if not inside:
        return None
    rows: list[list[dict]] = []
    for w in sorted(inside, key=lambda w: w["top"]):
        if rows and w["top"] - rows[-1][0]["top"] <= 3:
            rows[-1].append(w)
        else:
            rows.append([w])
    spans: list[list[float]] = []
    for w in sorted(inside, key=lambda w: w["x0"]):
        if spans and w["x0"] - spans[-1][1] < 6:  # 6pt < LaTeX's 2*tabcolsep gap
            spans[-1][1] = max(spans[-1][1], w["x1"])
        else:
            spans.append([w["x0"], w["x1"]])
    if len(rows) < 2 or len(spans) < 2:
        return None
    grid = [["" for _ in spans] for _ in rows]
    for r, row in enumerate(rows):
        for w in sorted(row, key=lambda w: w["x0"]):
            cx = (w["x0"] + w["x1"]) / 2
            c = next((k for k, (a, b) in enumerate(spans) if a <= cx <= b), None)
            if c is not None:
                grid[r][c] = f"{grid[r][c]} {w['text']}".strip()
    return grid


def _text_lines(page, page_no: int) -> list[dict]:
    """Layout-analysed text lines (column-aware) with font size + boldness."""
    from pdfminer.layout import LTChar, LTTextBoxHorizontal

    out: list[dict] = []
    for box in page.layout:
        if not isinstance(box, LTTextBoxHorizontal):
            continue
        for line in box:
            chars = [c for c in line if isinstance(c, LTChar)]
            text = _norm(_CID.sub("", line.get_text()))
            if not chars or not text:
                continue
            fonts = {(c.fontname or "").lower() for c in chars}
            out.append(
                {
                    "page": page_no,
                    "x": line.x0,
                    "y": page.height - line.y1,
                    "text": text,
                    "size": max(c.size for c in chars),
                    "bold": any("bold" in f or "bx" in f for f in fonts),  # CMR vs CMBX
                }
            )
    return out


def _text_blocks(page) -> list[tuple[float, float, str]]:
    """(top, bottom, text) per layout text box — caption candidates."""
    from pdfminer.layout import LTTextBoxHorizontal

    return [
        (page.height - b.y1, page.height - b.y0, _norm(_CID.sub("", b.get_text())))
        for b in page.layout
        if isinstance(b, LTTextBoxHorizontal)
    ]


def ingest_pdf_bytes(
    data: bytes, *, source_path: str = "", title_hint: str | None = None
) -> StructuredPaper:
    import pdfplumber  # local import keeps `prebuttal backends` startup light

    try:
        doc = pdfplumber.open(io.BytesIO(data), laparams={})
        pages = doc.pages
    except Exception as e:
        raise PDFError(f"cannot open PDF: {e}") from e
    try:
        return _ingest(doc, pages, source_path=source_path, title_hint=title_hint)
    finally:
        doc.close()


def _ingest(doc, pages, *, source_path: str, title_hint: str | None) -> StructuredPaper:
    warnings: list[str] = []

    # --- font-size statistics over the whole document (body text baseline)
    lines_all: list[dict] = []  # {page, x, y, text, size, bold}
    for i, page in enumerate(pages):
        lines_all.extend(_text_lines(page, i))
    sizes: list[float] = []
    for ln in lines_all:
        sizes.extend([ln["size"]] * min(len(ln["text"]), 40))
    body_size = statistics.median(sizes) if sizes else 10.0

    # LaTeX emits section numbers and titles as separate lines ("1" then
    # "Introduction"); merge them, then drop leftover bare numbers (page numbers).
    merged: list[dict] = []
    i = 0
    while i < len(lines_all):
        cur = lines_all[i]
        nxt = lines_all[i + 1] if i + 1 < len(lines_all) else None
        if (
            re.fullmatch(r"\d{1,2}(?:\.\d{1,2}){0,3}", cur["text"])
            and cur["size"] >= body_size * 1.05  # heading-level, not bold table cells
            and nxt is not None
            and nxt["page"] == cur["page"]
            and (
                (abs(nxt["y"] - cur["y"]) < 3 and nxt["x"] > cur["x"])  # side by side
                or 3 <= nxt["y"] - cur["y"] < 30  # stacked (wrapped heading)
            )
            and (nxt["size"] >= body_size * 1.05 or nxt["bold"])
            and len(nxt["text"]) < 90
            and not _NUMBERED.match(nxt["text"])
        ):
            merged.append(
                {**cur, "text": f"{cur['text']} {nxt['text']}", "y": (cur["y"] + nxt["y"]) / 2}
            )
            i += 2
            continue
        merged.append(cur)
        i += 1
    lines_all = [ln for ln in merged if not re.fullmatch(r"\d{1,4}", ln["text"])]

    # --- title
    title = ""
    if title_hint and len(title_hint) > 8:
        title = title_hint
    meta_title = _norm(str((doc.metadata or {}).get("Title") or ""))
    if not title and len(meta_title) > 8 and "untitled" not in meta_title.lower():
        title = meta_title
    if not title and lines_all:
        page0 = [ln for ln in lines_all if ln["page"] == 0]
        if page0:
            top = [ln for ln in page0 if ln["y"] < 300] or page0
            biggest = max(ln["size"] for ln in top)
            cands = sorted(
                (ln for ln in top if ln["size"] >= biggest - 0.1), key=lambda ln: ln["y"]
            )
            parts = [cands[0]["text"]]
            for prev, nxt in pairwise(cands):  # join wrapped title lines
                if 0 < nxt["y"] - prev["y"] < biggest * 1.6:
                    parts.append(nxt["text"])
            title = " ".join(parts)
    if not title:
        title = "Untitled submission"

    # --- abstract (text before the first heading, after an Abstract marker)
    abstract = ""
    for i, ln in enumerate(lines_all[:60]):
        if re.fullmatch(r"(?i)abstract\b.*", ln["text"]) or ln["text"].lower() == "abstract":
            first = ln["text"][8:] if ln["text"].lower().startswith("abstract") else ""
            buf = [first]
            for nxt in lines_all[i + 1 : i + 25]:
                if _NUMBERED.match(nxt["text"]) or nxt["size"] > body_size * 1.13:
                    break
                buf.append(nxt["text"])
            abstract = _norm(" ".join(buf))[:3000]
            break

    # --- headings & sections
    sections: list[Section] = []
    current: dict | None = None

    def _is_heading(ln: dict) -> tuple[bool, int, str, str]:
        m = _NUMBERED.match(ln["text"])
        if m:
            num, rest = m.group(1), m.group(2)
            if (ln["size"] >= body_size * 1.08 or ln["bold"]) and len(ln["text"]) < 90:
                return True, num.count(".") + 1, num, rest
        low = ln["text"].strip().strip(".").lower()
        if (
            low in _HEADING_WORDS
            and len(ln["text"]) < 40
            and (ln["size"] >= body_size * 1.05 or ln["bold"])
        ):
            # 0 = recognized word but not a section start (e.g. Abstract)
            special = {
                "abstract": 0,
                "references": 1,
                "bibliography": 1,
                "acknowledgments": 1,
                "acknowledgements": 1,
                "introduction": 1,
                "conclusion": 1,
                "conclusions": 1,
            }
            if low == "appendix":
                return True, 1, "A", ln["text"]
            if low in special:
                return (True, 1, "", ln["text"]) if special[low] else (False, 0, "", "")
        return False, 0, "", ""

    for ln in lines_all:
        hit, level, num, ttl = _is_heading(ln)
        if hit and level > 0:
            if current:
                sections.append(Section(**current))
            current = {
                "level": level,
                "number": num,
                "title": ttl,
                "text": "",
                "appendix": num == "A" or num.startswith("A"),
            }
        elif current is not None:
            cur_text = current["text"]
            current["text"] = (cur_text + " " + ln["text"]).strip()
        # text before the first heading is dropped (title block / abstract)
    if current:
        sections.append(Section(**current))

    # --- tables
    tables: list[Table] = []
    seen_numbers: set[str] = set()
    for page in pages:
        words = page.extract_words()
        found: list[tuple[tuple, list[list[str]]]] = []
        try:
            grids = page.find_tables()  # fully ruled grids (vertical + horizontal lines)
        except Exception:  # pragma: no cover - malformed page geometry
            grids = []
        for tab in grids:
            grid = _grid_from_cells([tuple(c) for c in tab.cells], words)
            if grid is None:
                grid = tab.extract()
            found.append((tab.bbox, grid))
        for bbox in _rule_regions(page):
            overlaps = any(
                bbox[1] < fb[3] and fb[1] < bbox[3] and bbox[0] < fb[2] and fb[0] < bbox[2]
                for fb, _g in found
            )
            if not overlaps:
                grid = _grid_from_region(bbox, words)
                if grid is not None:
                    found.append((bbox, grid))
        caps = []
        for y0, y1, t in _text_blocks(page):
            cm = _TABLE_CAP.match(t)
            if cm:
                caps.append((y0, y1, cm.group(1), t[:400]))
        for tab_bbox, grid in found:
            grid = [[_norm(str(c)) if c is not None else "" for c in row] for row in grid]
            grid = [row for row in grid if any(c for c in row)]
            if len(grid) < 2:
                continue
            bbox_y = (tab_bbox[1] + tab_bbox[3]) / 2
            number = ""
            caption = ""
            best_d = None
            for y0, y1, num, text in caps:
                cy = (y0 + y1) / 2
                d = abs(cy - bbox_y)
                if d < 260 and (best_d is None or d < best_d):
                    best_d, number, caption = d, num, text
            if not number:
                number = f"t{len(tables) + 1}"
            if number in seen_numbers:
                continue
            seen_numbers.add(number)
            tables.append(
                Table(
                    number=number,
                    caption=caption[:400],
                    header=grid[0],
                    rows=grid[1:],
                    raw="\n".join(" | ".join(r) for r in grid),
                    source="pdf-table",
                )
            )

    # --- fallback: caption blocks without a detected grid
    cap_blocks: dict[str, str] = {}
    order: list[str] = []
    for ln in lines_all:
        cm = _TABLE_CAP.match(ln["text"])
        if cm and cm.group(2):
            num = cm.group(1)
            if num not in cap_blocks:
                cap_blocks[num] = ln["text"][:400]
                order.append(num)
    for num in order:
        if num in seen_numbers:
            continue
        tables.append(
            Table(
                number=num,
                caption=cap_blocks[num],
                header=[],
                rows=[],
                raw=cap_blocks[num],
                source="pdf-caption-block",
            )
        )
        seen_numbers.add(num)
    if not any(t.source == "pdf-table" for t in tables):
        warnings.append(
            "no ruled tables detected via PDF table detection; "
            "some tables may be caption-block fallbacks (numbers preserved as text)"
        )

    # --- figure captions
    figures: list[Figure] = []
    fig_seen: set[str] = set()
    for ln in lines_all:
        fm = _FIG_CAP.match(ln["text"])
        if fm and fm.group(2) and fm.group(1) not in fig_seen:
            fig_seen.add(fm.group(1))
            figures.append(Figure(number=fm.group(1), caption=ln["text"][:400]))

    if not sections:
        warnings.append("no section headings detected; paper text may be image-based")

    return StructuredPaper(
        title=title,
        abstract=abstract,
        sections=sections,
        tables=sorted(tables, key=lambda t: (len(t.number), t.number)),
        figures=figures,
        source_type="pdf",
        source_path=source_path,
        warnings=warnings,
    )
