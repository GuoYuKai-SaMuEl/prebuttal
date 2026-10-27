"""Projects: every paper gets one, so its runs line up as a revision history.

A project is found automatically from where the paper came from — the same
PDF path, LaTeX directory or arXiv id always lands in the same project, even
after the title changes between revisions.  ``--project NAME`` picks one by
hand (and moves that source to it for future runs).

The registry is a small JSON file next to the run archive::

    ~/.prebuttal/projects.json
    {"version": 1, "projects": {"<key>": {"title": ..., "sources": [...], "created": ...}}}

Keys are short slugs (``mamba-linear-time-sequence``) used on the command
line and as folder names under ``prebuttal-reports/``.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ingestion.arxiv import parse_arxiv_id

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class ProjectError(Exception):
    """Unknown project, bad name, or a name that is already taken."""


def slugify(text: str, limit: int = 30) -> str:
    """``"Mamba: Linear-Time Sequence Modeling"`` -> ``mamba-linear-time-sequence``.

    Cut at a word boundary so keys stay short enough to type.
    """
    s = re.sub(r"[^a-z0-9]+", "-", (text or "paper").lower()).strip("-")
    if len(s) > limit:
        cut = s[: limit + 1].rsplit("-", 1)[0]
        s = cut if len(cut) >= limit // 2 else s[:limit]
    return s.strip("-") or "paper"


def source_identity(source: str) -> str:
    """Stable identity of a paper source: arXiv id (version dropped) or absolute path."""
    s = source.strip()
    arxiv_id = parse_arxiv_id(s) if not Path(s).exists() else None  # local copy wins
    if arxiv_id:
        return "arxiv:" + re.sub(r"v\d+$", "", arxiv_id)
    return "path:" + Path(s).expanduser().resolve().as_posix()


@dataclass
class Project:
    key: str
    title: str = ""
    sources: list[str] = field(default_factory=list)
    created: str = ""


def _root() -> Path:
    from .runs import runs_root  # runs imports this module

    return runs_root()


def registry_path() -> Path:
    return _root() / "projects.json"


def load_projects() -> dict[str, Project]:
    p = registry_path()
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # a corrupt registry must never block a review
    out: dict[str, Project] = {}
    for key, entry in (raw.get("projects") or {}).items():
        if not isinstance(entry, dict):
            continue
        out[key] = Project(
            key=key,
            title=str(entry.get("title", "")),
            sources=[str(s) for s in entry.get("sources", [])],
            created=str(entry.get("created", "")),
        )
    return out


def save_projects(projects: dict[str, Project]) -> None:
    from .runs import make_private_dir

    make_private_dir(_root())
    data: dict[str, Any] = {
        "version": 1,
        "projects": {
            k: {"title": p.title, "sources": p.sources, "created": p.created}
            for k, p in sorted(projects.items())
        },
    }
    atomic_write(registry_path(), json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + rename so a crash never leaves half a file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _unique_key(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"


def normalize_key(name: str) -> str:
    key = slugify(name, limit=64)
    if not KEY_RE.match(key):
        raise ProjectError(f"invalid project name {name!r}")
    return key


def assign_project(
    source: str, title: str, explicit: str | None = None, *, register: bool = True
) -> str:
    """Return the project key for this run, registering it when new.

    ``register=False`` (``run --no-save``) only looks the project up.
    """
    projects = load_projects()
    ident = source_identity(source)
    if explicit:
        key = normalize_key(explicit)
        for p in projects.values():  # the source now belongs to the named project
            if p.key != key and ident in p.sources:
                p.sources.remove(ident)
    else:
        found = next((p.key for p in projects.values() if ident in p.sources), None)
        key = found or _unique_key(slugify(title), set(projects))
    proj = projects.get(key)
    if proj is None:
        proj = projects[key] = Project(key=key, created=time.strftime("%Y-%m-%dT%H:%M:%S"))
    if ident not in proj.sources:
        proj.sources.append(ident)
    if title:
        proj.title = title  # latest revision's title
    if register:
        save_projects(projects)
    return key


def rename_project(old: str, new: str) -> str:
    """Rename a project in the registry; the caller rewrites run history."""
    projects = load_projects()
    new_key = normalize_key(new)
    if new_key in projects and new_key != old:
        raise ProjectError(f"project '{new_key}' already exists")
    proj = projects.pop(old, None)
    if proj is None:
        proj = Project(key=old)  # legacy project known only from run history
    proj.key = new_key
    projects[new_key] = proj
    save_projects(projects)
    return new_key


def forget_project(key: str) -> None:
    projects = load_projects()
    if projects.pop(key, None) is not None:
        save_projects(projects)
