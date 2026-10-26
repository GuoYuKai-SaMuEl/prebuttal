"""Reviewer pack: the single structured rendering every reviewer receives.

Budget policy (deterministic, seed-reproducible):
- the abstract and all tables are NEVER truncated (tables are the moat);
- method/experiment sections keep full text while budget allows;
- other sections degrade progressively: 1500 chars -> 600 chars -> elided;
- appendices are sacrificed first, in reverse order.

If a ``summarizer`` callback is supplied (``compress = true``), sections that
would be truncated are LLM-summarized instead of hard-cut.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .models import StructuredPaper

IMPORTANT = re.compile(
    r"(intro|method|approach|model|architecture|experiment|result|evaluat|"
    r"ablation|analysis|discussion|conclusion|limitation)",
    re.IGNORECASE,
)

FULL, REDUCED, MINIMAL = 1500, 600, 0

NOT_EXTRACTED = "[numbers not extracted]"


def estimate_tokens(chars: int) -> int:
    """Rough chars->tokens estimate (~4 chars/token for English + LaTeX)."""
    return chars // 4


def _tables_md(paper: StructuredPaper) -> str:
    if not paper.tables:
        return "\n## Tables\n\n(no tables detected in this submission)\n"
    parts = ["\n## Complete tables (verbatim, cell by cell)\n"]
    if any(t.source == "pdf-caption-block" for t in paper.tables):
        parts.append(
            f"{NOT_EXTRACTED} marks a table whose cell values the PDF parser could "
            "not recover; only its caption is shown. This is a limitation of the "
            "review tool, not a flaw of the paper: do not criticise the submission "
            "for missing numbers in such a table.\n"
        )
    for t in paper.tables:
        cap = re.sub(
            rf"^(?:table|tab\.)\s*{re.escape(t.number)}\s*[:.]\s*", "", t.caption, flags=re.I
        )
        cap = f": {cap}" if cap else ""
        parts.append(f"\n### Table {t.number}{cap}\n")
        if t.source == "pdf-caption-block":
            parts.append(NOT_EXTRACTED)
        else:
            parts.append(t.to_markdown())
        parts.append("")
    return "\n".join(parts)


def _figures_md(paper: StructuredPaper) -> str:
    if not paper.figures:
        return ""
    lines = ["\n## Figure captions\n"]
    for f in paper.figures:
        lines.append(f"- Figure {f.number}: {f.caption}")
    return "\n".join(lines) + "\n"


def render_pack(
    paper: StructuredPaper,
    *,
    budget_chars: int = 120_000,
    summarizer: Callable[[str, str], str | None] | None = None,
) -> str:
    """Render the reviewer pack for ``paper`` within ``budget_chars``."""
    head = [f"# Submission under review — {paper.title}", ""]
    if paper.abstract:
        head += ["## Abstract", "", paper.abstract, ""]

    sections = list(paper.sections)
    fixed_len = len("\n".join(head)) + len(_tables_md(paper)) + len(_figures_md(paper))

    # sacrifice priority: unimportant before important, appendices first,
    # and among equals the later section goes first.
    def sacrifice_key(i: int) -> tuple[int, int, int]:
        sec = sections[i]
        return (0 if IMPORTANT.search(sec.heading) else 1, 1 if sec.appendix else 0, -i)

    order = sorted(range(len(sections)), key=sacrifice_key, reverse=True)

    allowances: dict[int, int | None] = {i: None for i in range(len(sections))}

    def _render(i: int) -> str:
        sec = sections[i]
        body = sec.text
        allow = allowances[i]
        if allow is not None and len(body) > allow:
            summarized = summarizer(sec.heading, body) if (summarizer and allow > 0) else None
            if summarized:
                body = summarized
            else:
                elided = len(body) - allow
                cut = body[:allow].rsplit(" ", 1)[0]
                body = f"{cut} [... {elided} chars elided ...]"
        indent = "  " * max(0, sec.level - 1)
        return f"\n## {indent}{sec.heading}\n\n{body}\n"

    def _total() -> int:
        return fixed_len + sum(len(_render(i)) for i in range(len(sections)))

    for step in (FULL, REDUCED, MINIMAL):
        for i in order:
            if _total() <= budget_chars:
                break
            current = allowances[i]
            if current is None or current > step:
                allowances[i] = step

    body_parts = ["".join(head)]
    body_parts += [_render(i) for i in range(len(sections))]
    body_parts.append(_tables_md(paper))
    body_parts.append(_figures_md(paper))
    return "\n".join(body_parts)
