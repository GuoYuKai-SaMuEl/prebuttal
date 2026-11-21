"""Figures as images, for reviewers on vision-capable backends (``figures = true``).

Captions alone hide what most "the results don't support the claim"
criticism is about.  PDFs: every page holding a figure caption is rendered
whole (robust, and the figure keeps its context).  LaTeX: the first
``\\includegraphics`` of each figure environment, from inside the project
folder only (the image is sent to the model provider).
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..models import Figure, FigureImage

DEFAULT_MAX_IMAGES = 6
_PAGE_DPI = 90  # a US-letter page ≈ 765 x 990 px: legible plots, ~1.5k image tokens
_MAX_SIDE = 1400
_GRAPHIC_EXTS = ("", ".pdf", ".png", ".jpg", ".jpeg")


def _png(image: Any) -> bytes:
    """Pillow image -> PNG bytes, longest side capped (token cost scales with pixels)."""
    image = image.convert("RGB")
    image.thumbnail((_MAX_SIDE, _MAX_SIDE))
    buf = io.BytesIO()
    image.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def pdf_figure_images(
    pages: Sequence[Any], figures: list[Figure], max_images: int = DEFAULT_MAX_IMAGES
) -> list[FigureImage]:
    by_page: dict[int, list[str]] = {}
    for f in figures:
        if f.page:
            by_page.setdefault(f.page, []).append(f.number)
    out: list[FigureImage] = []
    for page_no in sorted(by_page)[:max_images]:
        if not 1 <= page_no <= len(pages):
            continue
        try:
            image = pages[page_no - 1].to_image(resolution=_PAGE_DPI).original
        except Exception:  # pragma: no cover - a page pdfium cannot render
            continue
        nums = by_page[page_no]
        label = f"page {page_no} (Figure{'s' if len(nums) > 1 else ''} {', '.join(nums)})"
        out.append(FigureImage(label=label, png=_png(image)))
    return out


def _render_graphic(path: Path) -> bytes | None:
    try:
        if path.suffix.lower() == ".pdf":
            import pdfplumber

            with pdfplumber.open(path) as doc:
                return _png(doc.pages[0].to_image(resolution=110).original)
        from PIL import Image

        with Image.open(path) as image:
            return _png(image)
    except Exception:  # unreadable or unsupported (eps, svg...): caption only
        return None


def latex_figure_images(
    figures: list[Figure],
    base: Path,
    allowed: Path,
    max_images: int = DEFAULT_MAX_IMAGES,
    graphics_dirs: list[str] | None = None,
) -> list[FigureImage]:
    """``graphics_dirs``: the paper's graphicspath, searched after ``base``
    as LaTeX does (relative to it); never outside ``allowed``."""
    allowed = allowed.resolve()
    dirs = [base] + [base / d for d in graphics_dirs or []]
    out: list[FigureImage] = []
    for f in figures:
        if len(out) >= max_images:
            break
        if not f.graphic:
            continue
        cand = next(
            (
                c
                for d in dirs
                for ext in _GRAPHIC_EXTS
                if (c := (d / (f.graphic + ext)).resolve()).is_file() and c.is_relative_to(allowed)
            ),
            None,
        )
        if cand is not None and (png := _render_graphic(cand)):
            out.append(FigureImage(label=f"Figure {f.number}", png=png))
    return out
