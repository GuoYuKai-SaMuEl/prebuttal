"""Local report files: one folder per paper, one subfolder per run, nothing overwritten.

::

    prebuttal-reports/
    ├── .gitignore                       (keeps reviews of unpublished work out of git)
    └── mamba-linear-time-sequence/      (the project)
        ├── latest.md / latest.html      (copy of the newest run)
        ├── 2026-10-25_1530_iclr/report.md, report.html
        └── 2026-10-26_0910_iclr/report.md, report.html

The complete record (JSON, resolved config) lives in the run archive under
``~/.prebuttal``; these files are the human-facing copies next to the paper.
"""

from __future__ import annotations

import time
from pathlib import Path

FORMATS = ("md", "html", "json")
DEFAULT_FORMATS = ("md", "html")

_GITIGNORE = (
    "# Created by prebuttal: simulated reviews of (possibly unpublished) work\n"
    "# stay out of version control. Delete this file to commit them.\n"
    "*\n"
)


def parse_formats(value: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """``"md,html"`` or ``["md", "html"]`` -> validated, de-duplicated tuple."""
    items = value.split(",") if isinstance(value, str) else list(value)
    out: list[str] = []
    for item in items:
        fmt = item.strip().lower().lstrip(".")
        if fmt == "markdown":
            fmt = "md"
        if not fmt:
            continue
        if fmt not in FORMATS:
            raise ValueError(f"unknown format '{item}' — choose from {', '.join(FORMATS)}")
        if fmt not in out:
            out.append(fmt)
    if not out:
        raise ValueError("no output format selected")
    return tuple(out)


def run_folder_name(venue: str, stamp: float | None = None) -> str:
    t = time.localtime(stamp)
    return time.strftime("%Y-%m-%d_%H%M", t) + f"_{venue}"


def write_local(
    root: Path, project: str, venue: str, files: dict[str, str]
) -> tuple[Path, list[Path]]:
    """Write ``files`` ({fmt: text}) into a fresh run folder; refresh ``latest.*``.

    Returns (run folder, written report paths). Raises OSError.
    """
    if not root.exists():
        root.mkdir(parents=True)
        (root / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
    proj_dir = root / project
    proj_dir.mkdir(parents=True, exist_ok=True)
    base = run_folder_name(venue)
    run_dir = proj_dir / base
    i = 2
    while run_dir.exists():  # two runs in the same minute
        run_dir = proj_dir / f"{base}-{i}"
        i += 1
    run_dir.mkdir()
    written: list[Path] = []
    for fmt, text in files.items():
        path = run_dir / f"report.{fmt}"
        path.write_text(text, encoding="utf-8")
        written.append(path)
        (proj_dir / f"latest.{fmt}").write_text(text, encoding="utf-8")
    return run_dir, written
