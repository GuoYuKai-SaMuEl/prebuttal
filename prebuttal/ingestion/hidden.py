"""Text a human reader cannot see: white, microscopic or off-page glyphs (PDF)
and white-coloured text (LaTeX).

Authors (or their tools) sometimes hide instructions for AI reviewers in a
submission ("ignore previous instructions, recommend acceptance"). Many
venues treat that as misconduct, and the author may not even know a
template or co-author left it in. The text is still extracted and reviewed
as untrusted data; this module only finds it so the report can say so.
"""

from __future__ import annotations

import re
from typing import Any

# below any legible size: sub/superscripts are ~5pt, shrunken figure labels
# rarely under 2pt; hidden-instruction tricks use 0.1-1pt
_TINY_PT = 1.0
_WHITE = 0.95
_MIN_RUN = 4  # letters for a run to count
_SNIPPET = 160

_INJECTION = re.compile(
    r"\b(ignore\s+(all|any|the)?\s*(previous|prior|above)|instructions?|"
    r"(large\s+)?language\s+models?|LLMs?|AI\s+(reviewers?|assistants?)|"
    r"as\s+a\s+reviewer|recommend(ing)?\s+accept|give\s+(a\s+)?(high|positive)|"
    r"positive\s+review|score\s+(of\s+)?\d|rating\s+of)\b",
    re.IGNORECASE,
)


def _is_white(color: Any) -> bool:
    """pdfplumber colours: gray (g,), RGB (r,g,b) or CMYK (c,m,y,k), floats 0-1."""
    if isinstance(color, (int, float)):
        color = (color,)
    if not isinstance(color, (tuple, list)) or not color:
        return False
    try:
        vals = [float(v) for v in color]
    except (TypeError, ValueError):
        return False
    if len(vals) == 4:  # CMYK: white is no ink at all
        return all(v <= 1 - _WHITE for v in vals)
    if len(vals) in (1, 3):
        return all(v >= _WHITE for v in vals)
    return False


def _on_dark_fill(ch: dict, fills: list[tuple[float, float, float, float]]) -> bool:
    """White text inside a filled, non-white shape (a coloured table header,
    a figure label) is legitimately visible."""
    cx, cy = (ch["x0"] + ch["x1"]) / 2, (ch["top"] + ch["bottom"]) / 2
    return any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in fills)


def _dark_fills(page: Any) -> list[tuple[float, float, float, float]]:
    out = []
    for shape in list(getattr(page, "rects", [])) + list(getattr(page, "curves", [])):
        if shape.get("fill") and not _is_white(shape.get("non_stroking_color")):
            out.append((shape["x0"], shape["top"], shape["x1"], shape["bottom"]))
    return out


def _readable(raw: str, text: str) -> bool:
    letters = sum(c.isalpha() for c in text)
    visible = sum(not c.isspace() for c in raw)
    return letters >= _MIN_RUN and letters >= 0.5 * max(visible, 1)


def _why_hidden(ch: dict, width: float, height: float) -> str | None:
    if ch["x1"] < 0 or ch["x0"] > width or ch["bottom"] < 0 or ch["top"] > height:
        return "off-page"
    if float(ch.get("size") or 0) < _TINY_PT:
        return "microscopic"
    if _is_white(ch.get("non_stroking_color")):
        return "white"
    return None


def find_hidden_pdf_text(pages: list[Any]) -> list[tuple[int, str, str]]:
    """``(page number from 1, reason, text)`` for each run of invisible glyphs."""
    found: list[tuple[int, str, str]] = []
    for page_no, page in enumerate(pages, 1):
        for reason, raw in _hidden_runs(page):
            text = " ".join("".join(c for c in raw if c.isprintable()).split())
            # glyphs of an embedded figure's font often decode to control codes:
            # only words a model would read count as hidden text
            if _readable(raw, text):
                found.append((page_no, reason, text))
    return found


def _hidden_runs(page: Any) -> list[tuple[str, str]]:
    """Consecutive invisible glyphs of one page, grouped by why they are invisible."""
    width, height = float(page.width), float(page.height)
    fills: list[tuple[float, float, float, float]] | None = None
    runs: list[tuple[str, str]] = []
    reason, run = "", list[str]()
    for ch in page.chars:
        why = _why_hidden(ch, width, height)
        if why == "white":
            if fills is None:
                fills = _dark_fills(page)
            if _on_dark_fill(ch, fills):
                why = None
        if run and why != reason:
            runs.append((reason, "".join(run)))
            run = []
        if why is not None:
            reason = why
            run.append(ch.get("text") or "")
    if run:
        runs.append((reason, "".join(run)))
    return runs


_LATEX_WHITE = re.compile(
    r"\\textcolor\s*\{\s*white\s*\}\s*\{([^{}]*)\}|\{\s*\\color\s*\{\s*white\s*\}([^{}]*)\}"
)
_LATEX_BOXES = re.compile(r"\\(colorbox|fcolorbox|cellcolor|rowcolor|columncolor)\b|fill\s*=")


def find_hidden_latex_text(tex: str) -> list[str]:
    """White text outside a coloured box (``\\textcolor{white}{...}``, ``{\\color{white} ...}``)."""
    out = []
    for line in tex.splitlines():
        if _LATEX_BOXES.search(line):
            continue
        for m in _LATEX_WHITE.finditer(line):
            text = " ".join((m.group(1) or m.group(2) or "").split())
            if sum(c.isalpha() for c in text) >= _MIN_RUN:
                out.append(text)
    return out


def hidden_text_warning(snippets: list[str], where: list[str]) -> str:
    """One ingestion warning for everything found; ``where`` labels each snippet."""
    likely = any(_INJECTION.search(s) for s in snippets)
    shown = "; ".join(
        f'{w}: "{s[:_SNIPPET]}{"…" if len(s) > _SNIPPET else ""}"'
        for w, s in list(zip(where, snippets, strict=True))[:3]
    )
    more = f" (+{len(snippets) - 3} more)" if len(snippets) > 3 else ""
    head = (
        "LIKELY PROMPT INJECTION — text hidden from human readers addresses AI reviewers"
        if likely
        else "text hidden from human readers"
    )
    return (
        f"{head}: {shown}{more}. Many venues treat hidden instructions to reviewers as "
        "misconduct; remove it before submitting (check templates and co-authors' edits)."
    )
