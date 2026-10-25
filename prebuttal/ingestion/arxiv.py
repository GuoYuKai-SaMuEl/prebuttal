"""arXiv source: parse an arXiv id/URL, download the PDF, fetch the title."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx

from .. import __version__
from ..models import StructuredPaper
from .pdf import ingest_pdf_bytes

_UA = (
    f"prebuttal/{__version__} "
    "(https://github.com/GuoYuKai-SaMuEl/prebuttal; paper review stress test)"
)

_ARXIV_ID = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf|format|html)/)?(\d{4}\.\d{4,5})(v\d+)?", re.IGNORECASE
)


class ArxivError(Exception):
    pass


def parse_arxiv_id(source: str) -> str | None:
    """Extract an arXiv id from a URL / bare id, else None."""
    s = source.strip()
    if "arxiv.org" not in s and not re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", s):
        return None
    m = _ARXIV_ID.search(s)
    return m.group(1) + (m.group(2) or "") if m else None


# Real papers are a few MB; anything far bigger is not a paper (or hostile).
MAX_PDF_BYTES = 100 * 1024 * 1024


def fetch_pdf_bytes(arxiv_id: str, *, max_bytes: int = MAX_PDF_BYTES) -> bytes:
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    try:
        with httpx.stream(
            "GET",
            url,
            follow_redirects=True,
            timeout=60,
            headers={"User-Agent": _UA},
        ) as r:
            if r.status_code != 200:
                raise ArxivError(f"arXiv returned HTTP {r.status_code} for {url}")
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) > max_bytes:
                    raise ArxivError(f"{url} is larger than {max_bytes // 2**20} MB — not a paper?")
            ctype = r.headers.get("content-type", "?")
    except httpx.HTTPError as e:
        raise ArxivError(f"cannot reach arxiv.org: {e}") from e
    if not buf[:5] == b"%PDF-":
        raise ArxivError(f"{url} did not return a PDF (got {ctype})")
    return bytes(buf)


def fetch_title(arxiv_id: str) -> str | None:
    try:
        r = httpx.get(
            "https://export.arxiv.org/api/query",
            params={"id_list": arxiv_id},
            timeout=20,
            headers={"User-Agent": _UA},
        )
        if r.status_code != 200:
            return None
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(r.text)
        for entry in root.findall("a:entry", ns):
            t = entry.find("a:title", ns)
            if t is not None and t.text:
                return " ".join(t.text.split())
    except Exception:
        return None
    return None


def ingest_arxiv(source: str) -> StructuredPaper:
    arxiv_id = parse_arxiv_id(source)
    if not arxiv_id:
        raise ArxivError(f"not an arXiv link or id: {source!r}")
    pdf = fetch_pdf_bytes(arxiv_id)
    title_hint = fetch_title(arxiv_id)
    paper = ingest_pdf_bytes(pdf, source_path=source, title_hint=title_hint)
    paper.source_type = "arxiv"
    return paper
