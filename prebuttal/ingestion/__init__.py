"""Ingestion dispatch: PDF file / LaTeX project / arXiv link -> StructuredPaper."""

from __future__ import annotations

from pathlib import Path

from ..models import StructuredPaper
from .arxiv import ingest_arxiv, parse_arxiv_id
from .latex import LatexError, ingest_latex_source
from .pdf import PDFError, ingest_pdf_bytes


class IngestError(Exception):
    pass


def display_path(p: Path) -> str:
    """How a local source appears in reports, JSON and run history.

    Reports get shared; an absolute path leaks the user name and directory
    layout (``C:\\Users\\<name>\\...``).  Keep it relative to the working
    directory, else to ``~``, else just the file/directory name.
    """
    full = p.resolve()
    try:
        rel = full.relative_to(Path.cwd().resolve())
        return str(rel) if str(rel) != "." else full.name
    except ValueError:
        pass
    try:
        return "~/" + full.relative_to(Path.home().resolve()).as_posix()
    except (ValueError, RuntimeError):  # RuntimeError: no resolvable home
        return full.name


def ingest(source: str, *, figure_images: int = 0) -> StructuredPaper:
    """Route ``source`` (path or arXiv URL/id) to the right parser.

    ``figure_images``: also render up to that many figures as images."""
    paper = _ingest(source, figure_images)
    if paper.source_type != "arxiv":
        paper.source_path = display_path(Path(source.strip()))
    return paper


def _ingest(source: str, figure_images: int) -> StructuredPaper:
    s = source.strip()

    # a local folder named after an arXiv id (an unpacked source tarball) is
    # the user's own copy, maybe revised: never swap it for the public version
    if s.startswith(("http://", "https://")) or (parse_arxiv_id(s) and not Path(s).exists()):
        try:
            return ingest_arxiv(s, figure_images=figure_images)
        except Exception as e:
            raise IngestError(f"arXiv ingestion failed: {e}") from e

    p = Path(s)
    if not p.exists():
        raise IngestError(f"paper source not found: {s}")

    if p.is_dir():
        try:
            return ingest_latex_source(p, figure_images=figure_images)
        except LatexError as e:
            raise IngestError(f"LaTeX ingestion failed: {e}") from e

    if p.suffix.lower() == ".pdf":
        try:
            return ingest_pdf_bytes(p.read_bytes(), source_path=str(p), figure_images=figure_images)
        except PDFError as e:
            raise IngestError(f"PDF ingestion failed: {e}") from e

    if p.suffix.lower() == ".tex":
        try:
            return ingest_latex_source(p, figure_images=figure_images)
        except LatexError as e:
            raise IngestError(f"LaTeX ingestion failed: {e}") from e

    raise IngestError(
        f"unsupported source {s!r} — expected a .pdf file, a LaTeX project directory, "
        "or an arXiv link/id"
    )
