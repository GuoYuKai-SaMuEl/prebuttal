"""BibTeX, just enough for the paper's own bibliography: which files a main
.tex loads, which keys it cites, and the cited entries as reference lines —
for a LaTeX source shipped without its .bbl (an Overleaf download)."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

# natbib and biblatex citation commands (not \citestyle and other settings)
CITE = re.compile(
    r"\\(?:[Cc]ite(?:t|p|alt|alp|author|year|yearpar|num)?|nocite|[Pp]arencite|[Tt]extcite|"
    r"[Aa]utocite|[Ff]ootcite|fullcite)\*?\s*(?:\[[^\]]*\]\s*){0,2}\{([^{}]*)\}"
)
# where the bibliography comes from: BibTeX's \bibliography{a,b} (no
# extension) and biblatex's \addbibresource{a.bib}
BIBLIOGRAPHY = re.compile(r"\\bibliography\s*\{([^{}]+)\}")
BIBRESOURCE = re.compile(r"\\add(?:bibresource|globalbib)\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}")

_ENTRY = re.compile(r"@\s*([a-zA-Z]+)\s*([{(])")
_FIELD = re.compile(r"\s*,?\s*([a-zA-Z][\w:-]*)\s*=\s*")
_SKIP = {"comment", "preamble"}


def declared_bibs(tex: str, root: Path, allowed: Path) -> tuple[list[str], list[Path]]:
    """(the .bib files ``tex`` loads, those found next to ``root`` inside ``allowed``)."""
    names = [n.strip() for m in BIBLIOGRAPHY.findall(tex) for n in m.split(",")]
    declared = [n if n.lower().endswith(".bib") else f"{n}.bib" for n in names if n]
    declared += [n.strip() for n in BIBRESOURCE.findall(tex) if n.strip()]
    found = [p for p in (root.parent / f for f in declared) if inside(p, allowed)]
    return declared, found


def inside(p: Path, allowed: Path) -> bool:
    return p.is_file() and p.resolve().is_relative_to(allowed)


def cited_keys(tex: str) -> list[str]:
    """Keys in order of first citation; ``*`` (\\nocite{*}: all) kept, a
    macro's ``#1`` dropped."""
    out: list[str] = []
    for m in CITE.findall(tex):
        for k in (k.strip() for k in m.split(",")):
            if k and "#" not in k and k not in out:
                out.append(k)
    return out


def _balanced(text: str, i: int, close: str) -> int:
    """Index of the ``close`` ending the group opened just before ``i``."""
    depth = 0
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}" and depth:
            depth -= 1
        elif c == close and depth == 0:
            return i
        i += 1
    return len(text)


def _value(body: str, i: int, macros: dict[str, str]) -> tuple[str, int]:
    """One field value (``{…}``, ``"…"``, a number or ``@string`` macro,
    joined by ``#``)."""
    parts = []
    while i < len(body):
        while i < len(body) and body[i].isspace():
            i += 1
        if i >= len(body):
            break
        c = body[i]
        if c == "{":
            j = _balanced(body, i + 1, "}")
            parts.append(body[i + 1 : j])
            i = j + 1
        elif c == '"':
            j = i + 1
            depth = 0
            while j < len(body) and not (body[j] == '"' and depth == 0):
                depth += {"{": 1, "}": -1}.get(body[j], 0)
                j += 1
            parts.append(body[i + 1 : j])
            i = j + 1
        else:
            m = re.match(r"[^,#\s}]+", body[i:])
            if not m:
                break
            parts.append(macros.get(m.group(0).lower(), m.group(0)))
            i += m.end()
        while i < len(body) and body[i].isspace():
            i += 1
        if i < len(body) and body[i] == "#":
            i += 1
            continue
        break
    return "".join(parts), i


def parse_bib(text: str) -> dict[str, dict[str, str]]:
    """``{key: {field: value}}`` of every entry, in file order (first one
    of a key wins, as BibTeX keeps it)."""
    out: dict[str, dict[str, str]] = {}
    macros: dict[str, str] = {}
    pos = 0
    while m := _ENTRY.search(text, pos):
        end = _balanced(text, m.end(), "}" if m.group(2) == "{" else ")")
        pos = end + 1
        if m.group(1).lower() in _SKIP:
            continue
        body = text[m.end() : end]
        if m.group(1).lower() == "string":  # @string{nips = "..."}
            if fm := _FIELD.match(body):
                macros[fm.group(1).lower()] = _value(body, fm.end(), macros)[0]
            continue
        key, _sep, rest = body.partition(",")
        key = key.strip()
        if not key or key in out:
            continue
        fields: dict[str, str] = {}
        i = 0
        while fm := _FIELD.match(rest, i):
            value, i = _value(rest, fm.end(), macros)
            fields.setdefault(fm.group(1).lower(), value)
        out[key] = fields
    return out


def _authors(raw: str, clean: Callable[[str], str]) -> str:
    names = [clean(n) for n in re.split(r"\s+and\s+", raw.strip()) if n.strip()]
    names = [
        " ".join(reversed([p.strip() for p in n.split(",", 1)])) if "," in n else n for n in names
    ]
    if len(names) > 3:
        return f"{names[0]} et al."
    return ", ".join(names)


def reference_lines(
    tex: str, bibs: list[Path], clean: Callable[[str], str], read: Callable[[Path], str]
) -> list[str]:
    """The cited entries of ``bibs`` (all of them with \\nocite{*}) as
    ``Authors. Title. Venue, Year.``, in order of first citation."""
    entries: dict[str, dict[str, str]] = {}
    for p in bibs:
        for k, v in parse_bib(read(p)).items():
            entries.setdefault(k, v)
    keys = cited_keys(tex)
    order = [k for k in keys if k in entries]
    if "*" in keys:
        order += [k for k in entries if k not in order]
    lines = []
    for k in order:
        f = entries[k]
        venue = (
            f.get("booktitle") or f.get("journal") or f.get("publisher") or f.get("howpublished")
        )
        parts = [
            _authors(f.get("author") or f.get("editor") or "", clean),
            clean(f.get("title") or ""),
            ", ".join(x for x in (clean(venue or ""), clean(f.get("year") or "")) if x),
        ]
        line = ". ".join(p.rstrip(".") for p in parts if p)
        if line:
            lines.append(line + ".")
    return lines
