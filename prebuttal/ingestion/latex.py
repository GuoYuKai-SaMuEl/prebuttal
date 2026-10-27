"""LaTeX ingestion: sections, cell-accurate tables, figures, references.

Deterministic (no LLM calls): a ``tabular`` environment becomes a real grid of
cells, ``\\ref``/``\\label`` are resolved to display numbers, and the resulting
reviewer pack lets a reviewer point at "Table 3, column 4".
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Figure, Section, StructuredPaper, Table
from .figures import latex_figure_images
from .hidden import find_hidden_latex_text, hidden_text_warning


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


def _merge_inputs(
    tex: str,
    root_dir: Path,
    seen: set[Path],
    missing: list[str],
    cur_dir: Path | None = None,
    *,
    allowed: Path | None = None,
    blocked: list[str] | None = None,
) -> str:
    """Inline ``\\input``/``\\include`` recursively (braced or ``\\input file``).

    Like LaTeX, paths resolve against the root file's directory at every
    nesting level; the including file's own directory is only a fallback.
    Unresolvable inputs are recorded in ``missing`` instead of vanishing.

    The source may come from someone else (an arXiv tarball, a co-author's
    repo) and the merged text is sent to a model provider, so files outside
    ``allowed`` (the project folder; symlinks resolved) are never read — they
    are recorded in ``blocked`` instead.
    """
    allowed = (allowed or root_dir).resolve()
    blocked = [] if blocked is None else blocked

    def repl(m: re.Match) -> str:
        name = (m.group(1) or m.group(2)).strip()
        dirs = [root_dir] if cur_dir in (None, root_dir) else [root_dir, cur_dir]
        found = False
        for d in dirs:
            for cand in (d / name, d / (name + ".tex")):
                cand = cand.resolve()
                if not cand.is_file():
                    continue
                found = True
                if not cand.is_relative_to(allowed):
                    if name not in blocked:
                        blocked.append(name)
                    return ""
                if cand not in seen:
                    seen.add(cand)
                    sub = _strip_comments(_read_text(cand))
                    return _merge_inputs(
                        sub, root_dir, seen, missing, cand.parent, allowed=allowed, blocked=blocked
                    )
        if not found:
            missing.append(name)
        return ""

    return _INPUT_RE.sub(repl, tex)


# \input{file} / \include{file}, and TeX's primitive form `\input file`
# (braces or whitespace required, so \includegraphics and \inputencoding never match)
_INPUT_RE = re.compile(r"\\(?:input|include)(?:\s*\{([^{}]+)\}|\s+([^\s{}\\%]+))")


_GRAPHIC = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}")


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


# inline/display math, kept as LaTeX: reviewers read it, stripping it loses symbols
_MATH_SPAN = re.compile(r"\$\$.+?\$\$|\$(?:\\.|[^$\\])+?\$|\\\(.+?\\\)|\\\[.+?\\\]", re.S)
_ESC_DOLLAR = "\x00"


def _clean_math(m: str, resolve_ref=None) -> str:
    m = re.sub(r"\\label\s*\{[^{}]*\}", " ", m)
    if resolve_ref is not None:
        m = re.sub(r"\\(?:ref|eqref)\s*\{([^{}]*)\}", lambda r: resolve_ref(r.group(1)), m)
    return re.sub(r"\s+", " ", m).strip()


def _clean_inline(s: str, resolve_ref=None) -> str:
    s = s.replace("\\$", _ESC_DOLLAR)
    maths: list[str] = []
    tag = f"\x01{id(maths)}:"  # unique per call: footnotes recurse

    def keep(m: re.Match) -> str:
        maths.append(_clean_math(m.group(0), resolve_ref))
        return f"{tag}{len(maths) - 1}\x01"

    s = _MATH_SPAN.sub(keep, s)
    for _ in range(4):
        if not re.search(r"\\(?:" + _WRAPPERS + r")\*?\s*\{", s):
            break
        s = re.sub(r"\\(?:" + _WRAPPERS + r")\*?\s*\{", "{", s)

    s = re.sub(r"\\label\s*\{[^{}]*\}", " ", s)
    while m := re.search(r"\\footnote\s*(?=\{)", s):
        g = _group_after(s, m.end())
        if g is None:
            s = s[: m.start()] + s[m.end() :]
            continue
        s = f"{s[: m.start()]} [note: {_clean_inline(g[0], resolve_ref)}] {s[g[1] :]}"
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
    for a, b in (("\\%", "%"), ("\\_", "_"), ("\\#", "#"), ("\\&", "&")):
        s = s.replace(a, b)
    s = s.replace("``", '"').replace("''", '"')
    s = s.replace("~", " ").replace("\\~", " ")
    s = re.sub(r"\\[a-zA-Z]+\*?", "", s)
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(re.escape(tag) + "(\\d+)\x01", lambda m: maths[int(m.group(1))], s)
    return s.replace(_ESC_DOLLAR, "$").strip()


def _clean_block(text: str, resolve_ref=None) -> str:
    paragraphs = re.split(r"\n\s*\n", text)
    cleaned = []
    for para in paragraphs:
        # list environments: drop the \begin/\end markers, one item per line
        para = re.sub(r"\\(?:begin|end)\s*\{(?:itemize|enumerate|description)\}", " ", para)
        para = re.sub(r"\\item\b\s*(?:\[([^\]]*)\])?", lambda m: f"\x02- {m.group(1) or ''} ", para)
        para = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}", " ", para)
        para = _clean_inline(para, resolve_ref)
        para = re.sub(r"\s*\n\s*", " ", para)
        para = re.sub(r"\s*\x02", "\n", para).strip()
        if para:
            cleaned.append(para)
    return "\n\n".join(cleaned)


# ------------------------------------------------------------------- tabular

_TABULAR_VARIANTS = (("tabularx", 2), ("tabular*", 2), ("tabular", 1), ("longtable", 1))


def _tabular_body(block: str) -> str | None:
    """Rows text of the largest tabular-like environment inside ``block``."""
    best: str | None = None
    for name, nargs in _TABULAR_VARIANTS:
        # exact names: `tabular*` takes an extra width arg, so `tabular` must
        # not also match it (the column spec would leak into the first cell)
        begin_re = re.compile(r"\\begin\{" + re.escape(name) + r"\}")
        end_re = re.compile(r"\\end\{" + re.escape(name) + r"\}")
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
_MULTIROW_MATH = ("align", "gather", "eqnarray")
_NONUMBER = re.compile(r"\\(?:nonumber|notag)\b")


def _math_spans(text: str) -> list[tuple[int, int, str, bool, str]]:
    """(start, end, env, starred, body) of display-math environments, in order."""
    spans = []
    for env in _MATH_ENVS:
        for s, e, blk in _env_spans(text, env):
            starred = text.startswith(f"\\begin{{{env}*}}", s)
            spans.append((s, e, env, starred, blk))
    return sorted(spans)


def _math_rows(env: str, body: str) -> list[str]:
    """One entry per equation number the environment produces."""
    if env not in _MULTIROW_MATH:
        return [body]
    rows = re.split(r"\\\\", body)
    return [r for r in rows if r.strip()] or [body]


def ingest_latex_source(path: Path, *, figure_images: int = 0) -> StructuredPaper:
    """``figure_images``: render up to that many figures for vision reviewers."""
    path = Path(path)
    root = find_root_tex(path) if path.is_dir() else path
    base = root.parent
    allowed = (path if path.is_dir() else base).resolve()
    if path.is_dir() and not root.resolve().is_relative_to(allowed):
        # a symlinked main.tex in an unpacked tarball must not pull in e.g. ~/.ssh
        raise LatexError(f"{root} links outside the paper's folder — not read")

    tex = _strip_comments(_read_text(root))
    missing_inputs: list[str] = []
    blocked_inputs: list[str] = []
    tex = _merge_inputs(
        tex,
        base,
        {root.resolve()},
        missing_inputs,
        allowed=allowed,
        blocked=blocked_inputs,
    )

    warnings: list[str] = [
        f"\\input{{{name}}} not found relative to {base.name}/ — its content is missing"
        for name in missing_inputs
    ]
    warnings += [
        f"\\input{{{name}}} points outside the paper's folder — not read (copy the file "
        "into the project if it belongs to the paper)"
        for name in blocked_inputs
    ]
    hidden = find_hidden_latex_text(tex)  # comments are already stripped: those never render
    if hidden:
        warnings.insert(0, hidden_text_warning(hidden, ["LaTeX source"] * len(hidden)))

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

    # --- tables & figures (numbered by order of appearance; _env_spans already
    # matches the starred variants, so `table` covers `table*` in document order)
    tables: list[Table] = []
    table_spans: list[tuple[int, int]] = []
    label_map: dict[str, str] = {}
    for s, e, blk in _env_spans(body, "table"):
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
    for s, e, blk in _env_spans(body, "figure"):
        fig_spans.append((s, e))
        cap, label = _caption_label(blk)
        number = str(len(figures) + 1)
        if label:
            label_map[label] = number
        gm = _GRAPHIC.search(blk)
        figures.append(
            Figure(
                number=number,
                caption=" ".join(_clean_inline(cap).split()),
                graphic=gm.group(1).strip() if gm else "",
            )
        )

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
        if "*" in m.group(0):  # \section*: unnumbered, and the counters don't move
            marks.append((m.start(), level, after, "", plain, in_appendix))
            continue
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
    for _s, _e, _env, _starred, blk in _math_spans(body):
        if _starred:
            continue
        for row in _math_rows(_env, blk):
            if _NONUMBER.search(row):
                continue
            eq_counter += 1
            for lm in re.finditer(r"\\label\s*\{([^{}]+)\}", row):
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
    eq_shown = 0  # numbers display equations in the same order as the labels above
    for i, (_start, sec_level, after, num, title_text, is_app) in enumerate(marks):
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

        shown = []
        for s, e, env, starred, blk in _math_spans(chunk):
            nums = []
            if not starred:
                for row in _math_rows(env, blk):
                    if not _NONUMBER.search(row):
                        eq_shown += 1
                        nums.append(f"({eq_shown})")
            math = _clean_math(_NONUMBER.sub(" ", blk), resolve_ref)
            shown.append((s, e, f" $${math}$$ {' '.join(nums)} "))
        for s, e, display in reversed(shown):
            chunk = chunk[:s] + display + chunk[e:]
        for env in ("abstract", "thebibliography"):
            for s, e, blk in reversed(_env_spans(chunk, env)):
                inner = _clean_inline(re.sub(r"\\label\s*\{[^{}]*\}", " ", blk), resolve_ref)
                chunk = chunk[:s] + " " + inner + " " + chunk[e:]

        text = _clean_block(chunk, resolve_ref)
        sections.append(
            Section(level=sec_level, number=num, title=title_text, text=text, appendix=is_app)
        )

    # --- references
    refs = _collect_references(body, root, resolve_ref, allowed)
    if refs:
        sections.append(Section(level=1, number="", title="References", text=refs))
    else:
        warnings.append("no .bbl / thebibliography found — references not included")

    # attach each table to the section it appears in
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
        hidden_text=hidden,
        figure_images=(
            latex_figure_images(figures, base, allowed, figure_images) if figure_images else []
        ),
    )


def _collect_references(body: str, root: Path, resolve_ref, allowed: Path) -> str:
    entries: list[str] = []
    bib_spans = _env_spans(body, "thebibliography")
    source = ""
    if bib_spans:
        source = bib_spans[0][2]
    else:
        bbl = root.with_suffix(".bbl")
        if bbl.is_file() and bbl.resolve().is_relative_to(allowed):
            source = _strip_comments(_read_text(bbl))
    if source:
        source = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}(?:\s*\{[^{}]*\})?", " ", source)
        parts = re.split(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}", source)
        entries = [_clean_inline(" ".join(p.split()), resolve_ref) for p in parts[1:]]
    entries = [e for e in entries if e][:60]
    return "\n".join(f"[{i}] {e[:240]}" for i, e in enumerate(entries, 1))
