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


# a browser's name for a second download: "paper (1).zip", "paper(2).pdf"
_DOWNLOAD_COPY = re.compile(r"(?<=\S) ?\(\d{1,3}\)(?=\.[^.]+$|$)")


def source_identity(source: str) -> str:
    """Stable identity of a paper source: arXiv id (version dropped) or absolute path.

    The path ignores a browser's download-copy suffix, so re-downloading the
    Overleaf source as ``paper (1).zip`` stays in the same project.
    """
    s = source.strip()
    arxiv_id = parse_arxiv_id(s) if not Path(s).exists() else None  # local copy wins
    if arxiv_id:
        return "arxiv:" + re.sub(r"v\d+$", "", arxiv_id)
    p = Path(s).expanduser().resolve()
    name = _DOWNLOAD_COPY.sub("", p.name, count=1)
    return "path:" + p.with_name(name).as_posix()


@dataclass
class Project:
    key: str
    title: str = ""
    sources: list[str] = field(default_factory=list)
    created: str = ""
    # the highest run number ever given (#N is never reused after `rm`) and
    # the names it had (a run started before a rename is archived under it)
    last_run_no: int = 0
    aliases: list[str] = field(default_factory=list)


def _root() -> Path:
    from .runs import runs_root  # runs imports this module

    return runs_root()


def _lock(*, required: bool) -> contextlib.AbstractContextManager[None]:
    """The archive's write lock; the registry is rewritten whole, like the history."""
    from .runs import store_lock

    return store_lock(required=required)


def _as_list(v: Any) -> list:
    return v if isinstance(v, list) else []


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
    entries = raw.get("projects") if isinstance(raw, dict) else None
    out: dict[str, Project] = {}
    for key, entry in (entries if isinstance(entries, dict) else {}).items():
        if not isinstance(entry, dict):
            continue
        out[key] = Project(
            key=key,
            title=str(entry.get("title", "")),
            sources=[str(s) for s in _as_list(entry.get("sources"))],
            created=str(entry.get("created", "")),
            last_run_no=_whole(entry.get("last_run_no")),
            aliases=[str(s) for s in _as_list(entry.get("aliases"))],
        )
    return out


def _whole(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def current_key(projects: dict[str, Project], key: str) -> str:
    """``key``, or the project it was renamed to."""
    if key in projects:
        return key
    return next((p.key for p in projects.values() if key in p.aliases), key)


def save_projects(projects: dict[str, Project]) -> None:
    from .runs import make_private_dir

    make_private_dir(_root())
    data: dict[str, Any] = {
        "version": 1,
        "projects": {
            k: {
                "title": p.title,
                "sources": p.sources,
                "created": p.created,
                **({"last_run_no": p.last_run_no} if p.last_run_no else {}),
                **({"aliases": p.aliases} if p.aliases else {}),
            }
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
    if not register:
        return _assign(source, title, explicit, register=False)
    with _lock(required=False):
        return _assign(source, title, explicit, register=True)


def _assign(source: str, title: str, explicit: str | None, *, register: bool) -> str:
    projects = load_projects()
    ident = source_identity(source)
    if explicit:
        # an old name of a renamed project means that project: it is never
        # given to another paper, by --project any more than automatically
        key = current_key(projects, normalize_key(explicit))
        for p in projects.values():  # the source now belongs to the named project
            if p.key != key and ident in p.sources:
                p.sources.remove(ident)
    else:
        # a project registered before download copies were folded keeps its runs
        legacy = "path:" + Path(source.strip()).expanduser().resolve().as_posix()
        found = next((p.key for p in projects.values() if ident in p.sources), None)
        found = found or next((p.key for p in projects.values() if legacy in p.sources), None)
        # a renamed project's old names stay taken: a run or retry that still
        # holds one must not land in another paper's project
        taken = set(projects) | {a for p in projects.values() for a in p.aliases}
        key = found or _unique_key(slugify(title), taken)
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


def rename_project(old: str, new: str) -> tuple[str, int]:
    """Rename a project in the registry and the run history: (new key, runs renamed).

    Both files change under one lock, so a run archived meanwhile cannot land
    under the old name; a name used only by the history (a project archived
    before the registry existed) is taken too — renaming onto it would merge
    two papers' runs and number them twice."""
    from .runs import load_history, rewrite_history

    new_key = normalize_key(new)
    with _lock(required=True):
        projects = load_projects()
        records = load_history()
        own = projects[old].aliases if old in projects else []
        taken = (
            set(projects)
            | {r.project for r in records}
            | {a for p in projects.values() if p.key != old for a in p.aliases}
        )
        if new_key in taken and new_key != old:
            raise ProjectError(
                f"project '{new_key}' already exists (or was another project's name)"
            )
        moved = [r for r in records if r.project == old]
        for r in moved:
            r.project = new_key
        rewrite_history(records)  # the runs first: they are what `runs` and `show` read
        proj = projects.pop(old, None)
        if proj is None:
            proj = Project(key=old)  # legacy project known only from run history
        proj.key = new_key
        if old != new_key and old not in proj.aliases:
            proj.aliases.append(old)
        if new_key in own:  # back to one of its own earlier names
            proj.aliases.remove(new_key)
        projects[new_key] = proj
        try:
            save_projects(projects)
        except BaseException:
            # the two files cannot change in one step: undo the first, so the
            # paper is never split between the old and the new name
            for r in moved:
                r.project = old
            rewrite_history(records)
            raise
    return new_key, len(moved)


def forget_project(key: str) -> None:
    with _lock(required=True):
        projects = load_projects()
        if projects.pop(key, None) is not None:
            save_projects(projects)
