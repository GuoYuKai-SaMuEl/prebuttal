"""LaTeX ingestion: sections, cell-accurate tables, figures, references.

Deterministic (no LLM calls): a ``tabular`` environment becomes a real grid of
cells, ``\\ref``/``\\label`` are resolved to display numbers, and the resulting
reviewer pack lets a reviewer point at "Table 3, column 4".
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Figure, Section, StructuredPaper, Table


class LatexError(Exception):
    pass


# ---------------------------------------------------------------- low-level IO


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:  # pragma: no cover
        raise LatexError(f"cannot read {p}: {e}") from e


def _strip_comments(tex: str) -> str:
    out = []
    for line in tex.splitlines():
        m = re.search(r"(?<!\\)%", line)
        out.append(line[: m.start()] if m else line)
    return "\n".join(out)


def _merge_inputs(tex: str, base: Path, seen: set[Path]) -> str:
    def repl(m: re.Match) -> str:
        name = m.group(1).strip()
        for cand in (base / name, base / (name + ".tex")):
            cand = cand.resolve()
            if cand.is_file() and cand not in seen:
                seen.add(cand)
                sub = _strip_comments(_read_text(cand))
                return _merge_inputs(sub, cand.parent, seen)
        return ""

    return re.sub(r"\\(?:input|include)\{([^{}]+)\}", repl, tex)


def find_root_tex(directory: Path) -> Path:
    texs = sorted(directory.rglob("*.tex"))
    if not texs:
        raise LatexError(f"no .tex files found under {directory}")
    by_name = {t.name.lower(): t for t in texs}
    for preferred in ("main.tex", "paper.tex", "ms.tex", "article.tex", "root.tex"):
        if preferred in by_name:
            return by_name[preferred]
    cands = [t for t in texs if "\\documentclass" in _read_text(t)]
    if cands:
        return min(cands, key=lambda p: (len(p.parts), str(p).lower()))
    return texs[0]


# ------------------------------------------------------------------ brace tools


def _find_closing(text: str, open_idx: int) -> int:
    """Index of the ``}`` matching the ``{`` at ``open_idx``; -1 if unbalanced."""
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _group_after(text: str, idx: int) -> tuple[str, int] | None:
    """Read the brace group whose ``{`` is the first non-space at/after idx."""
    n = len(text)
    while idx < n and text[idx] in " \t\r\n":
        idx += 1
    if idx >= n or text[idx] != "{":
        return None
    end = _find_closing(text, idx)
    if end < 0:
        return None
    return text[idx + 1 : end], end + 1


def _env_spans(text: str, name: str) -> list[tuple[int, int, str]]:
    """(start, end, body) spans of ``\\begin{name}\\*? ... \\end{name}\\*?``."""
    begin_re = re.compile(r"\\begin\{" + re.escape(name) + r"\*?\}")
    end_re = re.compile(r"\\end\{" + re.escape(name) + r"\*?\}")
    spans: list[tuple[int, int, str]] = []
    pos = 0
    while True:
        m = begin_re.search(text, pos)
        if not m:
            break
        e = end_re.search(text, m.end())
        if not e:
            break
        spans.append((m.start(), e.end(), text[m.end() : e.start()]))
        pos = e.end()
    return spans


# ------------------------------------------------------------------- cleaning

_WRAPPERS = (
    "textbf|textit|emph|texttt|textrm|textsf|textsc|text|underline|mbox|"
    "mathrm|mathit|mathbf|mathsf|mathtt|mathcal|mathbb|operatorname"
)
_DROP_WITH_ARGS = (
    "newcommand|renewcommand|providecommand|DeclareMathOperator|includegraphics|"
    "graphicspath|setlength|addtolength|settowidth|hspace|vspace|phantom|hphantom|vphantom"
)
_NOARG_DROP = (
    "label|index|bibliographystyle|nolinebreak|linebreak|smallskip|medskip|bigskip|"
    "quad|qquad|centering|raggedright|raggedleft|hfill|vfill|noindent|indent|"
    "clearpage|newpage|protect|displaybreak|footnotemark| thanks"
)


def _expand_multicolumn(body: str) -> str:
    out: list[str] = []
    i = 0
    mc = re.compile(r"\\multicolumn\s*\{(\d+)\}")
    while True:
        m = mc.search(body, i)
        if not m:
            out.append(body[i:])
            break
        out.append(body[i : m.start()])
        n = int(m.group(1))
        spec = _group_after(body, m.end())
        if spec is None:
            i = m.end()
            continue
        content = _group_after(body, spec[1])
        if content is None:
            i = spec[1]
            continue
        out.append(content[0] + " & " * (n - 1))
        i = content[1]
    return "".join(out)


def _expand_multirow(body: str) -> str:
    out: list[str] = []
    i = 0
    mr = re.compile(r"\\multirow\s*\{\d+\}\s*\{[^{}]*\}")
    while True:
        m = mr.search(body, i)
        if not m:
            out.append(body[i:])
            break
        out.append(body[i : m.start()])
        content = _group_after(body, m.end())
        if content is None:
            i = m.end()
            continue
        out.append(content[0])
        i = content[1]
    return "".join(out)


def _split_cells(row: str) -> list[str]:
    cells: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    n = len(row)
    while i < n:
        c = row[i]
        if c == "\\" and i + 1 < n:
            buf.append(row[i : i + 2])
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        elif c == "&" and depth == 0:
            cells.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    cells.append("".join(buf))
    return cells


def _drop_args(m: re.Match, text: str) -> str:
    idx = m.end()
    for _ in range(2):
        g = _group_after(text, idx)
        if g is None:
            break
        idx = g[1]
    return " "


def _clean_inline(s: str, resolve_ref=None) -> str:
    for _ in range(4):
        if not re.search(r"\\(?:" + _WRAPPERS + r")\*?\s*\{", s):
            break
        s = re.sub(r"\\(?:" + _WRAPPERS + r")\*?\s*\{", "{", s)

    def footnote(m: re.Match) -> str:
        g = _group_after(m.string, m.end() - 1)
        return "" if g is None else f" [note: {_clean_inline(g[0], resolve_ref)}] "

    s = re.sub(r"\\label\s*\{[^{}]*\}", " ", s)
    s = re.sub(r"\\footnote\s*\{", footnote, s)
    s = re.sub(
        r"\\(?:cite|citep|citet|citealp|citeauthor|parencite|autocite)"
        r"\s*(?:\[[^\]]*\]\s*)*\{[^{}]*\}",
        "[cite]",
        s,
    )
    if resolve_ref is not None:
        s = re.sub(
            r"\\(?:ref|eqref|autoref|Cref|cref)\s*\{([^{}]*)\}",
            lambda m: resolve_ref(m.group(1)),
            s,
        )
    else:
        s = re.sub(r"\\(?:ref|eqref|autoref|Cref|cref)\s*\{[^{}]*\}", "[ref]", s)
    s = re.sub(r"\\url\s*\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\href\s*\{[^{}]*\}\s*\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\(?:" + _DROP_WITH_ARGS + r")\*?", lambda m: _drop_args(m, m.string), s)
    s = re.sub(r"\\(?:" + _NOARG_DROP + r")\b", " ", s)
    s = re.sub(r"\\left\b|\\right\b|\\limits\b", " ", s)
    s = re.sub(r"\\[,;:!]", " ", s)
    s = re.sub(r"\\[\[\]{}]", " ", s)
    for a, b in (("\\%", "%"), ("\\_", "_"), ("\\#", "#"), ("\\$", "$"), ("\\&", "&")):
        s = s.replace(a, b)
    s = s.replace("``", '"').replace("''", '"')
    s = s.replace("~", " ").replace("\\~", " ")
    s = re.sub(r"\\[a-zA-Z]+\*?", "", s)
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _clean_block(text: str, resolve_ref=None) -> str:
    paragraphs = re.split(r"\n\s*\n", text)
    cleaned = []
    for para in paragraphs:
        para = re.sub(r"\\item\b", "- ", para)
        para = _clean_inline(para, resolve_ref)
        para = re.sub(r"\s*\n\s*", " ", para)
        if para:
            cleaned.append(para)
    return "\n\n".join(cleaned)


# ------------------------------------------------------------------- tabular

_TABULAR_VARIANTS = (("tabularx", 2), ("tabular*", 2), ("tabular", 1), ("longtable", 1))


def _tabular_body(block: str) -> str | None:
    """Rows text of the largest tabular-like environment inside ``block``."""
    best: str | None = None
    for name, nargs in _TABULAR_VARIANTS:
        begin_re = re.compile(r"\\begin\{" + re.escape(name) + r"\*?\}")
        end_re = re.compile(r"\\end\{" + re.escape(name) + r"\*?\}")
        pos = 0
        while True:
            m = begin_re.search(block, pos)
            if not m:
                break
            idx = m.end()
            ok = True
            for _ in range(nargs):
                g = _group_after(block, idx)
                if g is None:
                    ok = False
                    break
                idx = g[1]
            search_from = idx if ok else m.end()
            e = end_re.search(block, search_from)
            if not e:
                break
            if ok:
                candidate = block[idx : e.start()]
                if best is None or len(candidate) > len(best):
                    best = candidate
            pos = max(e.end(), m.end() + 1)
    return best


def _tabular_to_rows(body: str) -> list[list[str]]:
    body = re.sub(
        r"\\(?:toprule|midrule|bottomrule|hdashline|hline|endhead|endfirsthead|"
        r"endfoot|endlastfoot|caption|label)\b"
        r"|\\cline\s*\{[^{}]*\}|\\noalign\s*\{[^{}]*\}",
        " ",
        body,
    )
    body = _expand_multicolumn(body)
    body = _expand_multirow(body)
    raw_rows = re.split(r"(?:\\\\(?:\[[^\]]*\])?|\\tabularnewline|\\cr(?![a-zA-Z]))", body)
    rows: list[list[str]] = []
    for r in raw_rows:
        cells = [_clean_inline(c) for c in _split_cells(r)]
        if any(c.strip() for c in cells):
            rows.append([" ".join(c.split()) for c in cells])
    return rows


def _caption_label(block: str) -> tuple[str, str]:
    cap = ""
    m = re.search(r"\\caption\b\s*(?:\[[^\]]*\])?", block)
    if m:
        g = _group_after(block, m.end())
        if g is not None:
            cap = " ".join(_clean_inline(g[0]).split())
    label_m = re.search(r"\\label\s*\{([^{}]+)\}", block)
    return cap, (label_m.group(1) if label_m else "")


# ------------------------------------------------------------------- ingestion

_SEC_CMD = re.compile(r"\\(section|subsection|subsubsection)\*?\s*(?:\[[^\]]*\])?")
_LEVELS = {"section": 1, "subsection": 2, "subsubsection": 3}
_MATH_ENVS = ("equation", "align", "gather", "eqnarray", "multline")


def ingest_latex_source(path: Path) -> StructuredPaper:
    path = Path(path)
    root = find_root_tex(path) if path.is_dir() else path
    base = root.parent

    tex = _strip_comments(_read_text(root))
    tex = _merge_inputs(tex, base, {root.resolve()})

    warnings: list[str] = []

    doc_m = re.search(r"\\begin\{document\}", tex)
    if doc_m:
        end_m = re.search(r"\\end\{document\}", tex)
        body = tex[doc_m.end() : (end_m.start() if end_m else len(tex))]
    else:
        body = tex
        warnings.append("no \\begin{document} found; treating whole file as body")

    # --- title & abstract (\title may live in the preamble, so search all of tex)
    title = ""
    tm = re.search(r"\\title\s*(?:\[[^\]]*\])?", tex)
    if tm:
        g = _group_after(tex, tm.end())
        if g is not None:
            title = " ".join(_clean_inline(g[0]).split())
    abstract = ""
    abs_spans = _env_spans(body, "abstract")
    if abs_spans:
        abstract = " ".join(_clean_block(abs_spans[0][2]).split())

    # --- tables & figures (numbered by order of appearance)
    tables: list[Table] = []
    table_spans: list[tuple[int, int]] = []
    label_map: dict[str, str] = {}
    for env in ("table", "table*"):
        for s, e, blk in _env_spans(body, env):
            table_spans.append((s, e))
            cap, label = _caption_label(blk)
            tab_text = _tabular_body(blk)
            rows = _tabular_to_rows(tab_text) if tab_text else []
            number = str(len(tables) + 1)
            if label:
                label_map[label] = number
            raw = (
                "\n".join(" & ".join(r) for r in rows)
                if rows
                else " ".join(_clean_inline(re.sub(r"\\includegraphics\S*", " ", blk)).split())
            )
            tables.append(
                Table(
                    number=number,
                    caption=cap,
                    header=rows[0] if rows else [],
                    rows=rows[1:] if rows else [],
                    raw=raw,
                    source="latex-tabular",
                )
            )

    figures: list[Figure] = []
    fig_spans: list[tuple[int, int]] = []
    for env in ("figure", "figure*"):
        for s, e, blk in _env_spans(body, env):
            fig_spans.append((s, e))
            cap, label = _caption_label(blk)
            number = str(len(figures) + 1)
            if label:
                label_map[label] = number
            figures.append(Figure(number=number, caption=" ".join(_clean_inline(cap).split())))

    # --- sections
    appendix_at = None
    app_m = re.search(r"\\appendix\b", body)
    if app_m:
        appendix_at = app_m.start()

    marks: list[
        tuple[int, int, int, str, str, bool]
    ] = []  # start, level, after, num, title, appendix
    counters = [0, 0, 0]
    in_appendix = False
    for m in _SEC_CMD.finditer(body):
        if appendix_at is not None and m.start() >= appendix_at and not in_appendix:
            in_appendix = True
            counters = [0, 0, 0]  # appendix restarts numbering at A
        g = _group_after(body, m.end())
        if g is None:
            continue
        content, after = g
        level = _LEVELS[m.group(1)]
        plain = " ".join(_clean_inline(content).split())
        counters[level - 1] += 1
        for deeper in range(level, 3):
            counters[deeper] = 0
        if in_appendix:
            num = ".".join(
                (chr(64 + counters[i]) if i == 0 else str(counters[i])) for i in range(level)
            )
        else:
            num = ".".join(str(counters[i]) for i in range(level))
        marks.append((m.start(), level, after, num, plain, in_appendix))
        lm = re.search(r"\\label\s*\{([^{}]+)\}", body[after : after + 250])
        if lm and lm.group(1) not in label_map:
            label_map[lm.group(1)] = num

    # --- equation labels (numbered by appearance)
    eq_counter = 0
    for env in _MATH_ENVS:
        for _s, _e, blk in _env_spans(body, env):
            eq_counter += 1
            lm = re.search(r"\\label\s*\{([^{}]+)\}", blk)
            if lm:
                label_map[lm.group(1)] = f"({eq_counter})"

    def resolve_ref(key: str) -> str:
        for part in key.split(","):
            if part.strip() in label_map:
                return label_map[part.strip()]
        return "[?]"

    # --- float slots: positions of table/figure envs, for inline markers
    float_spans: dict[int, tuple[int, str]] = {}
    for s, e in table_spans:
        float_spans[s] = (e, "table")
    for s, e in fig_spans:
        float_spans[s] = (e, "figure")

    sections: list[Section] = []
    for i, (_start, _level, after, num, title_text, is_app) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(body)
        pieces: list[str] = []
        cur = after
        for s in sorted(float_spans):
            e, kind = float_spans[s]
            if s < after or s >= end:
                continue
            pieces.append(body[cur:s])
            pieces.append(
                "\n[float: table appears here — see Complete Tables below]\n"
                if kind == "table"
                else "\n[float: figure appears here — caption listed below]\n"
            )
            cur = max(cur, e)
        pieces.append(body[cur:end])
        chunk = "".join(pieces)

        for env in (*_MATH_ENVS, "abstract", "thebibliography"):
            for s, e, blk in _env_spans(chunk, env):
                inner = _clean_inline(re.sub(r"\\label\s*\{[^{}]*\}", " ", blk), resolve_ref)
                chunk = chunk[:s] + " " + inner + " " + chunk[e:]

        text = _clean_block(chunk, resolve_ref)
        sections.append(
            Section(level=level, number=num, title=title_text, text=text, appendix=is_app)
        )

    # --- references
    refs = _collect_references(body, root, resolve_ref)
    if refs:
        sections.append(Section(level=1, number="", title="References", text=refs))
    else:
        warnings.append("no .bbl / thebibliography found — references not included")

    # attach each table to the section it appears in
    sorted(float_spans)
    for t in tables:
        idx = int(t.number) - 1
        if 0 <= idx < len(table_spans):
            pos = table_spans[idx][0]
            best = ""
            for start, _level, _after, num, title_text, _ap in marks:
                if start <= pos:
                    best = f"{num} {title_text}".strip()
                else:
                    break
            t.section = best

    return StructuredPaper(
        title=title or root.stem,
        abstract=abstract,
        sections=sections,
        tables=tables,
        figures=figures,
        source_type="latex",
        source_path=str(path),
        warnings=warnings,
    )


def _collect_references(body: str, root: Path, resolve_ref) -> str:
    entries: list[str] = []
    bib_spans = _env_spans(body, "thebibliography")
    source = ""
    if bib_spans:
        source = bib_spans[0][2]
    else:
        bbl = root.with_suffix(".bbl")
        if bbl.is_file():
            source = _strip_comments(_read_text(bbl))
    if source:
        source = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}(?:\s*\{[^{}]*\})?", " ", source)
        parts = re.split(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}", source)
        entries = [_clean_inline(" ".join(p.split()), resolve_ref) for p in parts[1:]]
    entries = [e for e in entries if e][:60]
    return "\n".join(f"[{i}] {e[:240]}" for i, e in enumerate(entries, 1))
