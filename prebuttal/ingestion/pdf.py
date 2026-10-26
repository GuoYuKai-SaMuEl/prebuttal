"""PDF ingestion via pdfminer.six + pdfplumber: sections, cell-level tables,
figure captions.

Both libraries are MIT-licensed, which keeps the package's dependency tree
compatible with its own MIT license (PyMuPDF, used before 0.1.1, is AGPL).

Table strategy: fully ruled grids via ``page.find_tables`` and booktabs-style
tables (horizontal rules only — the ML-paper default) via rule clustering +
column whitespace (rules grouped by width first, so two-column pages and
stacked tables separate cleanly); each grid is paired with its nearest caption
and dropped if it has none; any numbered "Table N" caption without a detected
grid falls back to a caption-only block that the reviewer pack flags as
"numbers not extracted".
"""

from __future__ import annotations

import io
import re
import statistics
from collections.abc import Sequence
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
# Numbers: "3", "3.1" (GPT-3 style), "A.1" / "A1" / "S2" (appendix, supplement).
_CAP_NUM = r"((?:[A-Z]\.?)?\d{1,3}(?:\.\d{1,2})?)"
_TABLE_CAP = re.compile(
    r"^\s*(?:table|tab\.)\s*" + _CAP_NUM + r"(?:[a-z])?\s*[:.)]\s+(\S.*)$", re.I
)
# max vertical gap between a table's rules and its caption, in points
_CAPTION_GAP = 120
# max vertical gap between consecutive rules of one table (a 25-row table body)
_RULE_GAP = 450
# caption on the side the document does not use counts as this much farther:
# a tie-breaker only, since papers mix conventions (Mamba does)
_WRONG_SIDE = 8
# a ruled block of prose (e.g. prompt examples) is kept as text up to this size
_TEXT_TABLE_CHARS = 2000
# a gap wider than this fraction of the font size separates words; pdfplumber's
# fixed 3pt default glues tightly set LaTeX text ("Winratevs.groundtruth")
_WORD_GAP = 0.15
_FIG_CAP = re.compile(r"^\s*(?:figure|fig\.)\s*" + _CAP_NUM + r"(?:[a-z])?\s*[:.)]\s+(\S.*)$", re.I)


def _number_key(num: str) -> tuple:
    """Natural order: 2 < 3.1 < 10 < A.1 < S1 (appendix/supplement last)."""
    letter = num[0].upper() if num[:1].isalpha() else ""
    return (letter, *(int(n) for n in re.findall(r"\d+", num)))


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
_DINGBATS = {"(cid:51)": "✓", "(cid:52)": "✓", "(cid:55)": "✗", "(cid:56)": "✗"}


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


def _same_span(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Two rules span the same x-range, as a table's top, mid and bottom rules
    do; a full-width rule and a column-wide one do not, however much they
    overlap."""
    tol = max(4.0, 0.03 * (a[1] - a[0]))
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _rule_regions(
    page,
    captions: Sequence[tuple[float, float, float, float]] = (),
    words: Sequence[dict] = (),
) -> list[tuple[float, float, float, float]]:
    """Bounding boxes of booktabs-style tables: >= 2 horizontal rules of the
    same width, close together vertically.

    Rules are first grouped into x-bands (one per column / table width) and only
    then split vertically, so a two-column page whose left and right rules
    interleave in y still yields whole tables.  A band is also split at every
    caption (``(x0, top, x1, bottom)``) lying between two of its rules, and at
    every empty gap: the space between one table's bottom rule and the next
    one's top rule holds no cells.
    """
    rules = sorted(
        (e for e in page.horizontal_edges if e["x1"] - e["x0"] >= 40),
        key=lambda e: e["top"],
    )
    bands: list[list[dict]] = []
    for e in rules:
        for band in bands:
            if _same_span((band[0]["x0"], band[0]["x1"]), (e["x0"], e["x1"])):
                band.append(e)
                break
        else:
            bands.append([e])

    regions: list[tuple[float, float, float, float]] = []
    for band in bands:
        bx0, bx1 = band[0]["x0"], band[0]["x1"]
        cuts = [
            (top + bottom) / 2
            for x0, top, x1, bottom in captions
            if min(x1, bx1) - max(x0, bx0) > 0.5 * min(x1 - x0, bx1 - bx0)
        ]
        group: list[dict] = []
        for e in band:
            if group:
                prev = group[-1]["bottom"]
                empty = e["top"] - prev > 15 and not any(
                    bx0 <= (w["x0"] + w["x1"]) / 2 <= bx1
                    and prev < (w["top"] + w["bottom"]) / 2 < e["top"]
                    for w in words
                )
                if empty or e["top"] - prev > _RULE_GAP or any(prev < c < e["top"] for c in cuts):
                    if len(group) >= 2:
                        regions.append(_box(group))
                    group = []
            group.append(e)
        if len(group) >= 2:
            regions.append(_box(group))
    # larger tables first, so a stray rule pair inside one never pre-empts it
    regions.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
    return regions


def _box(group: list[dict]) -> tuple[float, float, float, float]:
    return (
        min(e["x0"] for e in group),
        group[0]["top"],
        max(e["x1"] for e in group),
        group[-1]["bottom"],
    )


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
    rows = _merge_subscripts(rows)
    if len(rows) < 2:
        return None
    spans = _column_spans(rows)
    if len(spans) < 2:
        return None
    grid = [["" for _ in spans] for _ in rows]
    for r, row in enumerate(rows):
        for w in sorted(row, key=lambda w: w["x0"]):
            cx = (w["x0"] + w["x1"]) / 2
            c = min(
                range(len(spans)),
                key=lambda k: max(spans[k][0] - cx, cx - spans[k][1], 0.0),
            )
            grid[r][c] = f"{grid[r][c]} {w['text']}".strip()
    return grid


def _merge_subscripts(rows: list[list[dict]]) -> list[list[dict]]:
    """``BERT`` + a lowered ``BASE`` starting where it ends -> ``BERT_BASE``.

    pdfplumber puts a subscript on its own line, which would otherwise become
    an extra, nearly empty table row."""
    out: list[list[dict]] = []
    for row in rows:
        prev = out[-1] if out else []
        hosts = [
            next(
                (
                    i
                    for i, p in enumerate(prev)
                    if abs(w["x0"] - p["x1"]) <= 1.5 and 0 < w["top"] - p["top"] < 7
                ),
                None,
            )
            for w in row
        ]
        if prev and None not in hosts and len(set(hosts)) == len(hosts):
            for w, i in zip(row, hosts, strict=True):
                assert i is not None
                prev[i] = {**prev[i], "text": f"{prev[i]['text']}_{w['text']}", "x1": w["x1"]}
            continue
        out.append(list(row))
    return out


def _column_spans(rows: list[list[dict]]) -> list[tuple[float, float]]:
    """Columns = x-ranges filled in (nearly) every row.

    A gap between columns may be crossed by a few rows (a ``\\multicolumn``
    header, one long model name) and still separate them; words closer than
    6pt (< LaTeX's 2*tabcolsep) always belong to one cell.
    """
    events: list[tuple[float, int]] = []
    for row in rows:
        cell: list[float] = []
        for w in sorted(row, key=lambda w: w["x0"]):
            if cell and w["x0"] - cell[1] < 6:
                cell[1] = max(cell[1], w["x1"])
                continue
            if cell:
                events += [(cell[0], 1), (cell[1], -1)]
            cell = [w["x0"], w["x1"]]
        if cell:
            events += [(cell[0], 1), (cell[1], -1)]
    n = len(rows)
    allowed = max(1 if n >= 4 else 0, n // 8)
    spans: list[list[float]] = []
    depth = 0
    for x, d in sorted(events, key=lambda e: (e[0], -e[1])):
        before = depth
        depth += d
        if before <= allowed < depth:  # a column starts
            if spans and x - spans[-1][1] < 1.0:
                pass  # too thin to be a real gap: the last column continues
            else:
                spans.append([x, x])
        elif depth <= allowed < before:  # a column ends
            spans[-1][1] = x
    return [(sp[0], sp[1]) for sp in spans]


def _figure_like(tb: tuple, caps: list[tuple], fig_caps: list[tuple]) -> bool:
    """A ruled block nearer a figure caption than any table caption (a boxed plot)."""
    if not fig_caps:
        return False
    fig = min((d for d, _a, _c in _caption_gaps(tb, fig_caps)), default=_CAPTION_GAP)
    tab = min((d for d, _a, _c in _caption_gaps(tb, caps)), default=_CAPTION_GAP)
    return fig < tab


def _region_text(bbox: tuple, words: list[dict]) -> str:
    """The words inside ``bbox`` as lines of text."""
    x0, top, x1, bottom = bbox
    inside = sorted(
        (
            w
            for w in words
            if x0 - 2 <= (w["x0"] + w["x1"]) / 2 <= x1 + 2
            and top < (w["top"] + w["bottom"]) / 2 < bottom
        ),
        key=lambda w: (round(w["top"]), w["x0"]),
    )
    lines: list[list[dict]] = []
    for w in inside:
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= 3:
            lines[-1].append(w)
        else:
            lines.append([w])
    return "\n".join(
        " ".join(w["text"] for w in sorted(ln, key=lambda w: w["x0"])) for ln in lines
    ).strip()


def _caption_gaps(tb: tuple, caps: list[tuple]) -> list[tuple[float, bool, int]]:
    """(gap, caption_is_above, caption index) for captions near table bbox ``tb``."""
    out = []
    for ci, (cx0, ctop, cx1, cbot, _n, _t) in enumerate(caps):
        if min(cx1, tb[2]) - max(cx0, tb[0]) <= 0:
            continue  # caption of another column
        is_above = (ctop + cbot) / 2 < (tb[1] + tb[3]) / 2
        gap = max(0.0, tb[1] - cbot) if is_above else max(0.0, ctop - tb[3])
        if gap < _CAPTION_GAP:
            out.append((gap, is_above, ci))
    return out


def _captions_above(page_finds: list) -> bool:
    """The document's caption convention, voted by tables with a caption on one
    side only.  ML venues put table captions above (the default); ACL below."""
    votes = 0
    for found, caps in page_finds:
        for tb, _g in found:
            sides = {is_above for _d, is_above, _c in _caption_gaps(tb, caps)}
            if len(sides) == 1:
                votes += 1 if sides.pop() else -1
    return votes >= 0


def _match_captions(found: list, caps: list, above: bool) -> list[tuple[int, list[int]]]:
    """Pair grids with captions one-to-one, closest first, on the document's
    caption side unless only the other side fits.  A grid left over beside a
    matched one (same top, same caption in reach) is another panel of that
    table.  Grids with no caption cannot be cited as "Table N" and are dropped
    rather than numbered by guesswork.  Returns [(caption, [grid, ...])]."""
    pairs = [
        (gap + (0 if is_above == above else _WRONG_SIDE), gi, ci)
        for gi, (tb, _g) in enumerate(found)
        for gap, is_above, ci in _caption_gaps(tb, caps)
    ]
    by_caption: dict[int, list[int]] = {}
    taken: set[int] = set()
    for _d, gi, ci in sorted(pairs):
        if gi not in taken and ci not in by_caption:
            taken.add(gi)
            by_caption[ci] = [gi]
    for _d, gi, ci in sorted(pairs):
        if gi in taken or ci not in by_caption:
            continue
        first = found[by_caption[ci][0]][0]
        if abs(found[gi][0][1] - first[1]) <= 3:  # side-by-side panel
            taken.add(gi)
            by_caption[ci].append(gi)
    out = []
    for ci, gis in by_caption.items():
        gis.sort(key=lambda g: found[g][0][0])  # panels left to right
        out.append((ci, gis))
    out.sort(key=lambda m: (found[m[1][0]][0][1], found[m[1][0]][0][0]))
    return out


def _join_panels(grids: list[list[list]]) -> list[list[str]]:
    """Clean grid(s); side-by-side panels are stacked, each keeping its header row."""
    rows: list[list[str]] = []
    for grid in grids:
        clean = [[_norm(str(c)) if c is not None else "" for c in row] for row in grid]
        rows.extend(row for row in clean if any(c for c in row))
    width = max((len(r) for r in rows), default=0)
    return [r + [""] * (width - len(r)) for r in rows]


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


def _text_blocks(page) -> list[tuple[float, float, float, float, str]]:
    """(x0, top, x1, bottom, text) per layout text box — caption candidates."""
    from pdfminer.layout import LTTextBoxHorizontal

    return [
        (b.x0, page.height - b.y1, b.x1, page.height - b.y0, _norm(_CID.sub("", b.get_text())))
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
    page_finds = []
    for page in pages:
        for ch in page.chars:  # pifont \cmark / \xmark: ablation tables are full of them
            if "dingbat" in (ch.get("fontname") or "").lower():
                ch["text"] = _DINGBATS.get(ch["text"], ch["text"])
        words = page.extract_words(x_tolerance_ratio=_WORD_GAP)
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
        blocks = _text_blocks(page)
        caps = [
            (x0, top, x1, bottom, cm.group(1), t[:400])
            for x0, top, x1, bottom, t in blocks
            if (cm := _TABLE_CAP.match(t))
        ]
        fig_caps = [
            (x0, top, x1, bottom, "", "") for x0, top, x1, bottom, t in blocks if _FIG_CAP.match(t)
        ]
        texts: list[tuple[tuple, str]] = []  # ruled blocks of prose (prompt examples)
        for bbox in _rule_regions(page, [c[:4] for c in caps], words):
            overlaps = any(
                bbox[1] < fb[3] and fb[1] < bbox[3] and bbox[0] < fb[2] and fb[0] < bbox[2]
                for fb, _g in found
            )
            if not overlaps:
                grid = _grid_from_region(bbox, words)
                if grid is not None:
                    found.append((bbox, grid))
                elif text := _region_text(bbox, words):
                    texts.append((bbox, text))
        # a boxed plot is ruled too: drop blocks nearer a figure caption than a table one
        found = [f for f in found if not _figure_like(f[0], caps, fig_caps)]
        texts = [t for t in texts if not _figure_like(t[0], caps, fig_caps)]
        page_finds.append((found, caps, texts))

    above = _captions_above([(f, c) for f, c, _t in page_finds])
    tables: list[Table] = []
    seen_numbers: set[str] = set()

    def _add(number: str, caption: str, **kw) -> None:
        seen_numbers.add(number)
        tables.append(Table(number=number, caption=caption[:400], **kw))

    for found, caps, texts in page_finds:
        matched = set()
        for ci, panels in _match_captions(found, caps, above):
            grid = _join_panels([found[gi][1] for gi in panels])
            number, caption = caps[ci][4], caps[ci][5]
            if len(grid) < 2 or number in seen_numbers:
                continue
            matched.add(ci)
            _add(
                number,
                caption,
                header=grid[0],
                rows=grid[1:],
                raw="\n".join(" | ".join(r) for r in grid),
                source="pdf-table",
            )
        # captions left over may own a ruled block of plain text: keep its words
        rest = [ci for ci in range(len(caps)) if ci not in matched]
        for k, panels in _match_captions(texts, [caps[ci] for ci in rest], above):
            number, caption = caps[rest[k]][4], caps[rest[k]][5]
            if number in seen_numbers:
                continue
            text = "\n\n".join(texts[ti][1] for ti in panels)
            if len(text) > _TEXT_TABLE_CHARS:
                text = text[:_TEXT_TABLE_CHARS].rsplit(" ", 1)[0] + " […]"
            _add(number, caption, raw=text, source="pdf-text")

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
    caption_only = [t.number for t in tables if t.source == "pdf-caption-block"]
    if caption_only:
        names = ", ".join(f"Table {n}" for n in caption_only)
        warnings.append(
            f"{names}: cell values not extracted from the PDF (caption only) — "
            "reviewers are told this is a tool limitation"
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
        tables=sorted(tables, key=lambda t: _number_key(t.number)),
        figures=figures,
        source_type="pdf",
        source_path=source_path,
        warnings=warnings,
    )
