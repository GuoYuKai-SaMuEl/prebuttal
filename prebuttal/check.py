"""`prebuttal check`: a deterministic desk-reject pre-flight — no model, no cost.

What gets submissions rejected before any reviewer reads them, checked
against the venue's rules (:class:`prebuttal.venues.CheckRules`):

- anonymity (double-blind venues): author names in the PDF metadata, e-mail
  addresses on page 1, a camera-ready / preprint build, a visible
  acknowledgements section, links to the authors' own repositories,
  self-revealing citations ("our previous work [12]");
- format: main-text pages over the limit, required sections missing (the
  NeurIPS checklist, ICML's impact statement, ARR's limitations);
- leftovers: unresolved ``??`` references and ``[?]`` citations, TODO
  markers, and text hidden from human readers.

PDFs are checked as they will be submitted.  A LaTeX project is checked
without compiling: labels and citation keys stand in for ``??``, and the page
limit needs the PDF.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from .venues import CheckRules, Venue

ERROR = "error"  # can get the paper desk-rejected
WARNING = "warning"  # worth a look before submitting


@dataclass(frozen=True)
class Finding:
    level: str
    area: str  # anonymity | format | leftovers
    message: str


@dataclass
class CheckResult:
    source: str
    kind: str  # pdf | latex
    findings: list[Finding] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == WARNING]

    def add(self, level: str, area: str, message: str) -> None:
        self.findings.append(Finding(level, area, message))


class CheckError(Exception):
    pass


# ------------------------------------------------------------------ patterns

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_SELF_CITE = re.compile(
    r"\b(?:our (?:previous|prior|earlier|recent) (?:work|paper|study|studies|method)s?"
    r"|we (?:previously|earlier) (?:showed|proposed|introduced|developed|presented))\b",
    re.I,
)
_REPO = re.compile(
    r"(?:https?://)?(?:www\.)?(?:github\.com|gitlab\.com|bitbucket\.org|huggingface\.co)"
    r"/[\w.-]+(?:/[\w.-]+)?|https?://[^\s{}]*/~[\w.-]+[^\s{}]*",
    re.I,
)
# what makes a link the authors' own: "our code is available at ..."
_OWN = re.compile(
    r"\b(?:our|we)\b[^.]{0,80}\b(?:code|implementation|repository|repo|data(?:set)?|models?|"
    r"release|available)\b|\b(?:code|implementation)s? (?:is|are|will be) (?:publicly )?available",
    re.I,
)
_ANON_HOSTS = ("anonymous.4open.science", "anonymous.4open", "anonymized")
_UNRESOLVED_REF = re.compile(
    r"(?:Figure|Fig\.|Table|Tab\.|Section|Sec\.|Appendix|App\.|Eq\.|Equation|Algorithm|"
    r"Theorem|Lemma|Corollary|Definition|Proposition)\s*~?\(?\?\?\)?|\?\?"
)
_UNRESOLVED_CITE = re.compile(r"\[\?(?:,\s*\?)*\]|\(\?\)|\(author\?\)|\(\?, \?\)")
_TODO = re.compile(r"\b(?:TODO|FIXME|TBD)\b")
_NUMBERING = re.compile(r"^(?:[A-Z]|\d+)(?:\.\d+)*\.?\s+")


def _norm_heading(text: str) -> str:
    s = _NUMBERING.sub("", " ".join(text.split())).strip().casefold()
    return s.replace("acknowledgement", "acknowledgment")


def _heading_matches(line: str, name: str) -> bool:
    """``line`` is the heading ``name`` (numbering, plural and spelling aside)."""
    if len(line) > 60:
        return False
    got, want = _norm_heading(line), _norm_heading(name)
    return got in (want, want + "s") or got.rstrip("s") == want.rstrip("s")


def _pages_list(pages: list[int], n: int = 6) -> str:
    uniq = sorted(set(pages))
    shown = ", ".join(str(p) for p in uniq[:n])
    return ("page " if len(uniq) == 1 else "pages ") + shown + ("…" if len(uniq) > n else "")


def _own_links(text: str) -> list[str]:
    out: list[str] = []
    for m in _REPO.finditer(text):
        url = m.group(0).rstrip(".,;:)")
        if any(h in url.lower() for h in _ANON_HOSTS) or url in out:
            continue
        before = text[max(0, m.start() - 160) : m.start()]
        before = re.split(r"[.!?]\s", before)[-1]  # the link's own sentence only
        if _OWN.search(before):
            out.append(url)
    return out


# ------------------------------------------------------------------ PDF


def check_pdf_bytes(data: bytes, rules: CheckRules, *, source: str = "") -> CheckResult:
    import pdfplumber

    from .ingestion.hidden import find_hidden_pdf_text
    from .ingestion.pdf import _text_lines

    result = CheckResult(source=source, kind="pdf")
    try:
        doc = pdfplumber.open(io.BytesIO(data), laparams={})
    except Exception as e:
        raise CheckError(f"cannot open PDF: {e}") from e
    try:
        pages = doc.pages
        lines = [ln for i, p in enumerate(pages) for ln in _text_lines(p, i)]
        # layout-analysed lines keep word spaces that extract_text() can drop
        texts = [
            "\n".join(ln["text"] for ln in lines if ln["page"] == i) for i in range(len(pages))
        ]
        sizes = [(float(p.width), float(p.height)) for p in pages]
        meta = doc.metadata or {}
        hidden = find_hidden_pdf_text(pages)
    finally:
        doc.close()
    full = "\n".join(texts)

    if rules.double_blind:
        _pdf_anonymity(result, rules, meta, texts, lines)
    else:
        result.skipped.append("anonymity (the venue is not double-blind)")
    _pdf_format(result, rules, lines, sizes)
    _leftovers_text(result, texts)
    if hidden:
        where = _pages_list([p for p, _r, _t in hidden])
        sample = hidden[0][2][:80]
        result.add(
            ERROR,
            "leftovers",
            f'text hidden from human readers ({where}): "{sample}" — venues have '
            "desk-rejected papers for hidden instructions to reviewers",
        )
    else:
        result.passed.append("no hidden text")
    if not full.strip():
        result.add(WARNING, "format", "no extractable text — a scanned PDF? nothing was checked")
    return result


def _pdf_anonymity(
    result: CheckResult, rules: CheckRules, meta: dict, texts: list[str], lines: list[dict]
) -> None:
    author = " ".join(str(meta.get("Author") or "").split())
    if author and author.casefold() not in {"anonymous", "anonymous author", "anonymous authors"}:
        result.add(
            ERROR,
            "anonymity",
            f'the PDF metadata names an author: "{author}" — clear it '
            "(LaTeX: \\hypersetup{pdfauthor={}})",
        )
    else:
        result.passed.append("PDF metadata has no author")
    first = texts[0] if texts else ""
    emails = sorted(set(_EMAIL.findall(first)))
    if emails:
        result.add(ERROR, "anonymity", f"page 1 shows e-mail address(es): {', '.join(emails[:3])}")
    for pattern in rules.final_markers:
        m = re.search(pattern, first, re.M)
        if m:
            result.add(
                ERROR,
                "anonymity",
                f'page 1 reads "{m.group(0).strip()[:90]}" — a camera-ready or preprint build, '
                "which shows the author names; build the anonymous submission version",
            )
            break
    acks = sorted(
        {ln["page"] + 1 for ln in lines if _heading_matches(ln["text"], "Acknowledgment")}
    )
    if acks:
        result.add(
            WARNING,
            "anonymity",
            f"an acknowledgements section is visible ({_pages_list(acks)}) — "
            "most double-blind venues want it out of the submission",
        )
    _anonymity_text(result, [(i + 1, t) for i, t in enumerate(texts)])


def _anonymity_text(result: CheckResult, chunks: list[tuple[int | str, str]]) -> None:
    links: list[tuple[int | str, str]] = []
    cites: list[tuple[int | str, str]] = []
    for where, text in chunks:
        flat = " ".join(text.split())
        links += [(where, u) for u in _own_links(flat)]
        cites += [(where, m.group(0)) for m in _SELF_CITE.finditer(flat)]
    for where, url in links[:4]:
        result.add(
            WARNING,
            "anonymity",
            f"{_where(where)}: link to what looks like your own repository: {url} — "
            "use an anonymized one (anonymous.4open.science) for review",
        )
    if cites:
        result.add(
            WARNING,
            "anonymity",
            f'{_where(cites[0][0])}: "{cites[0][1]}" reveals that a cited work is yours — '
            "cite it in the third person"
            + (f" (+{len(cites) - 1} more)" if len(cites) > 1 else ""),
        )
    if not links and not cites:
        result.passed.append("no self-revealing links or citations")


def _where(where: int | str) -> str:
    return f"page {where}" if isinstance(where, int) else str(where)


def _pdf_format(
    result: CheckResult, rules: CheckRules, lines: list[dict], sizes: list[tuple[float, float]]
) -> None:
    for name in rules.required_sections:
        if any(_heading_matches(ln["text"], name) for ln in lines):
            result.passed.append(f'"{name}" section present')
        else:
            result.add(ERROR, "format", f'no "{name}" section — the venue requires one')
    if rules.page_limit is None:
        result.skipped.append("page limit (none set for this venue)")
        return
    ends = [
        ln for ln in lines if any(_heading_matches(ln["text"], name) for name in rules.uncounted)
    ]
    if not ends:
        result.skipped.append("page limit (no References heading found to end the main text)")
        return
    # reading order: page, then column (left before right), then top to bottom
    end = min(ends, key=lambda ln: (ln["page"], ln["x"] > sizes[ln["page"]][0] / 2, ln["y"]))
    page = end["page"] + 1
    # the end page counts if main text comes before the heading on it: above it,
    # or in the column to its left (two-column layouts); running headers aside
    top = 0.07 * sizes[end["page"]][1]
    before = [
        ln
        for ln in lines
        if ln["page"] == end["page"]
        and ln is not end
        and ln["y"] > top
        and (ln["y"] < end["y"] - 2 or ln["x"] < end["x"] - 100)
    ]
    used = page if before else page - 1
    heading = " ".join(end["text"].split())
    if used > rules.page_limit:
        result.add(
            ERROR,
            "format",
            f"the main text runs to page {used} (before '{heading}'); the limit is "
            f"{rules.page_limit} pages",
        )
    else:
        result.passed.append(f"main text {used} of {rules.page_limit} pages")


def _leftovers_text(result: CheckResult, texts: list[str]) -> None:
    refs = [i + 1 for i, t in enumerate(texts) if _UNRESOLVED_REF.search(t)]
    cites = [i + 1 for i, t in enumerate(texts) if _UNRESOLVED_CITE.search(t)]
    todos = [i + 1 for i, t in enumerate(texts) if _TODO.search(t)]
    if refs:
        result.add(ERROR, "leftovers", f"unresolved references (??) on {_pages_list(refs)}")
    if cites:
        result.add(ERROR, "leftovers", f"unresolved citations ([?]) on {_pages_list(cites)}")
    if todos:
        result.add(WARNING, "leftovers", f"TODO / FIXME / TBD left on {_pages_list(todos)}")
    if not (refs or cites or todos):
        result.passed.append("no ??, [?] or TODO left")


# ------------------------------------------------------------------ LaTeX

_SECTION = re.compile(r"\\(?:section|chapter)\*?\s*\{([^{}]*)\}")
_LABEL = re.compile(r"\\label\s*\{([^{}]+)\}")
_REF = re.compile(
    r"\\(?:ref|eqref|autoref|cref|Cref|pageref|vref|nameref|subref)\*?\s*\{([^{}]+)\}"
)
# natbib and biblatex citation commands (not \citestyle and other settings)
_CITE = re.compile(
    r"\\(?:[Cc]ite(?:t|p|alt|alp|author|year|yearpar|num)?|nocite|[Pp]arencite|[Tt]extcite|"
    r"[Aa]utocite|[Ff]ootcite|fullcite)\*?\s*(?:\[[^\]]*\]\s*){0,2}\{([^{}]*)\}"
)


def _keys(found: list[str]) -> set[str]:
    """Keys from comma lists; `#1` (a macro's parameter) and `*` (all) are not keys."""
    keys = {k.strip() for m in found for k in m.split(",")}
    return {k for k in keys if k and k != "*" and "#" not in k}


_BIB_KEY = re.compile(r"@\s*[a-zA-Z]+\s*\{\s*([^,\s]+)\s*,")
_BIBITEM = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}")
_TODO_CMD = re.compile(r"\\(?:todo|TODO|fixme|FIXME)\b")
# venue styles that hide \author in their default (submission) mode; any
# package or class loaded with a review / anonymous / blind option does too
_LOAD = re.compile(
    r"^[^%\n]*\\(?:usepackage|documentclass)\s*(?:\[([^\]]*)\])?\s*\{([^{}]*)\}", re.M
)
_ANON_STYLE = re.compile(r"neurips_?\d*|iclr\d{4}_conference|icml\d{4}")
_AUTHOR = re.compile(r"\\author\s*(?:\[[^\]]*\])?\s*\{")


def _hides_authors(tex: str) -> bool:
    for m in _LOAD.finditer(tex):
        if re.search(r"\b(review|anonymous|blind)\b", (m.group(1) or "").lower()):
            return True
        if any(_ANON_STYLE.fullmatch(n.strip()) for n in m.group(2).split(",")):
            return True
    return False


def _named_authors(tex: str) -> str:
    """The \\author{...} text when it names someone ("" if absent or anonymous)."""
    m = _AUTHOR.search(tex)
    if not m:
        return ""
    depth, i = 1, m.end()
    while i < len(tex) and depth:
        depth += {"{": 1, "}": -1}.get(tex[i], 0)
        i += 1
    text = re.sub(r"\\[a-zA-Z@]+\*?|\\\\|[{}~]", " ", tex[m.end() : i - 1])
    text = " ".join(text.split())
    if not re.search(r"[^\W\d_]", text) or "anonymous" in text.casefold():
        return ""
    return text


def check_latex(path: Path, rules: CheckRules) -> CheckResult:
    from .ingestion.hidden import find_hidden_latex_text
    from .ingestion.latex import LatexError, _merge_inputs, _strip_comments, find_root_tex

    path = Path(path)
    try:
        root = find_root_tex(path) if path.is_dir() else path
        allowed = (path if path.is_dir() else root.parent).resolve()
        if path.is_dir() and not root.resolve().is_relative_to(allowed):
            raise CheckError(f"{root} links outside the paper's folder — not read")
        tex = _strip_comments(root.read_text(encoding="utf-8", errors="replace"))
        tex = _merge_inputs(tex, root.parent, {root.resolve()}, [], allowed=allowed, blocked=[])
    except (LatexError, OSError) as e:
        raise CheckError(str(e)) from e
    result = CheckResult(source=str(path), kind="latex")
    where = root.name

    if rules.double_blind:
        for pattern in rules.final_latex:
            m = re.search(pattern, tex, re.M)
            if m:
                result.add(
                    ERROR,
                    "anonymity",
                    f"{where}: `{m.group(0).strip()[-70:]}` switches the template to its "
                    "camera-ready / preprint mode, which prints the author names",
                )
                break
        else:
            names = _named_authors(tex)
            if names and not _hides_authors(tex):
                result.add(
                    WARNING,
                    "anonymity",
                    f"{where}: \\author{{{names[:60]}}} is printed — no venue style in "
                    "submission mode hides it; use the venue's template or anonymize it",
                )
        heads = [h for h in _SECTION.findall(tex) if _heading_matches(h, "Acknowledgment")]
        if heads:
            result.add(
                WARNING,
                "anonymity",
                f"{where}: a \\section{{{heads[0]}}} — most double-blind venues want the "
                "acknowledgements out of the submission",
            )
        _anonymity_text(result, [(where, tex)])
    else:
        result.skipped.append("anonymity (the venue is not double-blind)")

    titles = _SECTION.findall(tex)
    for name in rules.required_sections:
        if any(_heading_matches(t, name) for t in titles):
            result.passed.append(f'"{name}" section present')
        else:
            result.add(ERROR, "format", f'no "{name}" section — the venue requires one')
    if rules.page_limit is not None:
        result.skipped.append(
            f"page limit ({rules.page_limit} pages): compile the PDF and run "
            "`prebuttal check paper.pdf`"
        )

    labels = set(_LABEL.findall(tex))
    missing = sorted(_keys(_REF.findall(tex)) - labels)
    if missing:
        result.add(
            ERROR,
            "leftovers",
            f"\\ref to undefined label(s) — these print as ??: {', '.join(missing[:5])}"
            + (f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""),
        )
    _latex_citations(result, tex, path if path.is_dir() else root.parent)
    if _TODO_CMD.search(tex) or _TODO.search(tex):
        result.add(WARNING, "leftovers", f"{where}: \\todo / TODO / FIXME in the text")
    if not missing and not any(f.area == "leftovers" for f in result.findings):
        result.passed.append("every \\ref has a \\label; no TODO left")

    hidden = find_hidden_latex_text(tex)
    if hidden:
        result.add(
            ERROR,
            "leftovers",
            f'white text hidden from human readers: "{hidden[0][:80]}" — venues have '
            "desk-rejected papers for hidden instructions to reviewers",
        )
    else:
        result.passed.append("no hidden text")
    return result


def _latex_citations(result: CheckResult, tex: str, folder: Path) -> None:
    cited = _keys(_CITE.findall(tex))
    if not cited:
        return
    known = set(_BIBITEM.findall(tex))
    allowed = folder.resolve()
    sources = 0
    for p in list(folder.rglob("*.bib")) + list(folder.rglob("*.bbl")):
        if not p.resolve().is_relative_to(allowed):
            continue
        sources += 1
        text = p.read_text(encoding="utf-8", errors="replace")
        known |= set(_BIB_KEY.findall(text)) | set(_BIBITEM.findall(text))
    if not known and not sources:
        result.skipped.append("citations (no .bib / .bbl / thebibliography found)")
        return
    missing = sorted(cited - known)
    if missing:
        result.add(
            ERROR,
            "leftovers",
            "\\cite of key(s) missing from the bibliography — these print as [?]: "
            + ", ".join(missing[:5])
            + (f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""),
        )
    else:
        result.passed.append(f"all {len(cited)} cited keys are in the bibliography")


# ------------------------------------------------------------------ entry points


def check_source(source: str, venue: Venue) -> CheckResult:
    """Check a PDF file, a LaTeX project (folder or .tex) or an arXiv paper."""
    from .ingestion.arxiv import fetch_pdf_bytes, parse_arxiv_id

    s = source.strip()
    p = Path(s)
    if p.exists():
        if p.is_dir() or p.suffix.lower() == ".tex":
            return check_latex(p, venue.rules)
        try:
            data = p.read_bytes()
        except OSError as e:
            raise CheckError(f"cannot read {p}: {e}") from e
        return check_pdf_bytes(data, venue.rules, source=s)
    arxiv_id = parse_arxiv_id(s)
    if arxiv_id:
        try:
            return check_pdf_bytes(fetch_pdf_bytes(arxiv_id), venue.rules, source=s)
        except Exception as e:
            raise CheckError(f"arXiv: {e}") from e
    raise CheckError(f"paper source not found: {s}")


_MARK = {ERROR: "[x]", WARNING: "[!]"}


def render_check(result: CheckResult, venue: Venue) -> str:
    r = venue.rules
    facts = [f"{r.page_limit} pages" if r.page_limit else "no page limit set"]
    facts.append("double-blind" if r.double_blind else "not double-blind")
    facts += [f"requires {s}" for s in r.required_sections]
    out = [f"prebuttal check — {result.source} · {venue.name} rules ({', '.join(facts)})", ""]
    order = {"anonymity": 0, "format": 1, "leftovers": 2}
    for f in sorted(result.findings, key=lambda f: (f.level != ERROR, order.get(f.area, 9))):
        out.append(f"  {_MARK[f.level]} {f.area:<9}  {f.message}")
    for p in result.passed:
        out.append(f"  [ok] {p}")
    for s in result.skipped:
        out.append(f"  [-] not checked: {s}")
    out.append("")
    n_err, n_warn = len(result.errors), len(result.warnings)
    if n_err:
        out.append(
            f"{n_err} problem{'s' if n_err != 1 else ''} that can get the paper desk-rejected"
            + (f", {n_warn} warning{'s' if n_warn != 1 else ''}." if n_warn else ".")
        )
    elif n_warn:
        out.append(f"No desk-reject problems found; {n_warn} warning{'s' if n_warn != 1 else ''}.")
    else:
        out.append("No problems found.")
    if r.source:
        out.append(f"Rules taken from {r.source} — confirm against this year's call.")
    return "\n".join(out)


def preflight_warnings(result: CheckResult) -> list[str]:
    """Findings as report warnings, for `run` (errors first)."""
    ordered = result.errors + result.warnings
    return [f"Pre-flight check ({f.level}): {f.message}" for f in ordered]
