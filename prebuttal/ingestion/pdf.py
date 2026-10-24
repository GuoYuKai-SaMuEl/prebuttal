"""PDF ingestion via PyMuPDF: sections, cell-level tables, figure captions.

Table strategy: ruled-table detection first (``page.find_tables``), captions
matched by proximity; any numbered "Table N" caption without a detected grid
falls back to a verbatim caption-block so experimental numbers survive.
"""

from __future__ import annotations

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


def _grid_from_geometry(page, tab) -> list[list[str]] | None:
    """Rebuild table cells from word coordinates.

    ``tab.extract()`` assembles text from character spans and mangles kerned
    LaTeX decimals ("47.9" comes out as "479 ."); words from ``get_text``
    keep their spelling, so assigning them to cell boxes by center point and
    sorting by x reconstructs the true cell text.
    """
    try:
        cells = [tuple(c) for c in tab.cells]
    except Exception:  # pragma: no cover - older PyMuPDF without .cells
        return None
    if not cells:
        return None
    row_y = _cluster([c[1] for c in cells])
    col_x = _cluster([c[0] for c in cells])
    if not row_y or not col_x:
        return None
    grid = [["" for _ in col_x] for _ in row_y]

    def _nearest(vals: list[float], v: float) -> int:
        return min(range(len(vals)), key=lambda k: abs(vals[k] - v))

    cell_words: dict[tuple[int, int], list[tuple[float, str]]] = {}
    for w in page.get_text("words"):
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        for x0, y0, x1, y1 in cells:
            if x0 - 0.5 <= cx <= x1 + 0.5 and y0 - 0.5 <= cy <= y1 + 0.5:
                key = (_nearest(row_y, y0), _nearest(col_x, x0))
                cell_words.setdefault(key, []).append((w[0], w[4]))
                break
    for (r, c), ws in cell_words.items():
        grid[r][c] = " ".join(text for _x, text in sorted(ws))
    return grid


def ingest_pdf_bytes(
    data: bytes, *, source_path: str = "", title_hint: str | None = None
) -> StructuredPaper:
    import pymupdf  # local import keeps `prebuttal.backends` startup light

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # pragma: no cover
        raise PDFError(f"cannot open PDF: {e}") from e

    warnings: list[str] = []
    pages = [doc[i] for i in range(doc.page_count)]  # stubs have no __iter__

    # --- font-size statistics over the whole document (body text baseline)
    sizes: list[float] = []
    lines_all: list[dict] = []  # {page, y, text, size, bold}
    for page in pages:
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = _norm("".join(sp.get("text", "") for sp in spans))
                if not text:
                    continue
                size = max(sp.get("size", 10.0) for sp in spans)
                font_bits = {(sp.get("font") or "").lower() for sp in spans}
                bold = any("bold" in f or "bx" in f for f in font_bits)  # CMR vs CMBX
                lines_all.append(
                    {
                        "page": page.number,
                        "x": line["bbox"][0],
                        "y": line["bbox"][1],
                        "text": text,
                        "size": size,
                        "bold": bold,
                    }
                )
                sizes.extend([size] * min(len(text), 40))
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
    meta_title = _norm((doc.metadata or {}).get("title") or "")
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
        try:
            finder = page.find_tables()
        except Exception:  # pragma: no cover - PyMuPDF build without table support
            finder = None
        if finder is None:
            continue
        blocks = page.get_text("blocks")
        caps = []
        for b in blocks:
            if b[6] != 0:
                continue
            t = _norm(b[4])
            cm = _TABLE_CAP.match(t)
            if cm:
                caps.append((b[1], b[3], cm.group(1), t[:400]))
        for tab in finder.tables:
            grid = _grid_from_geometry(page, tab)
            if grid is None:
                try:
                    grid = tab.extract()  # fallback for non-ruled/odd tables
                except Exception:  # pragma: no cover
                    continue
            grid = [[_norm(str(c)) if c is not None else "" for c in row] for row in grid]
            grid = [row for row in grid if any(c for c in row)]
            if len(grid) < 2:
                continue
            bbox_y = (tab.bbox[1] + tab.bbox[3]) / 2
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
