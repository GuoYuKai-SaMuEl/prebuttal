"""Ingestion dispatch: PDF file / LaTeX project / arXiv link -> StructuredPaper."""

from __future__ import annotations

from pathlib import Path

from ..models import StructuredPaper
from .arxiv import ingest_arxiv, parse_arxiv_id
from .latex import LatexError, ingest_latex_source
from .pdf import PDFError, ingest_pdf_bytes


class IngestError(Exception):
    pass


def ingest(source: str) -> StructuredPaper:
    """Route ``source`` (path or arXiv URL/id) to the right parser."""
    s = source.strip()

    if s.startswith(("http://", "https://")) or parse_arxiv_id(s):
        try:
            return ingest_arxiv(s)
        except Exception as e:
            raise IngestError(f"arXiv ingestion failed: {e}") from e

    p = Path(s)
    if not p.exists():
        raise IngestError(f"paper source not found: {s}")

    if p.is_dir():
        try:
            return ingest_latex_source(p)
        except LatexError as e:
            raise IngestError(f"LaTeX ingestion failed: {e}") from e

    if p.suffix.lower() == ".pdf":
        try:
            return ingest_pdf_bytes(p.read_bytes(), source_path=str(p))
        except PDFError as e:
            raise IngestError(f"PDF ingestion failed: {e}") from e

    if p.suffix.lower() == ".tex":
        try:
            return ingest_latex_source(p)
        except LatexError as e:
            raise IngestError(f"LaTeX ingestion failed: {e}") from e

    raise IngestError(
        f"unsupported source {s!r} — expected a .pdf file, a LaTeX project directory, "
        "or an arXiv link/id"
    )
