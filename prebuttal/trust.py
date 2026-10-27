"""Consent for a prebuttal.toml found in the working directory.

A config passed with ``--config`` is the user's own choice.  One that is
merely *found* in the current directory may have come with someone else's
paper repo or an unpacked arXiv source, and it can decide a lot: run
commands (``[agents.*]``), send the manuscript to a provider the user never
picked (a pinned backend — maybe a free tier that trains on inputs), or write
files outside the project.  Those settings need a yes once; the approval is
remembered for that file's exact content (like direnv), so editing the file
asks again.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .config import RunConfig
from .projects import atomic_write
from .runs import make_private_dir, runs_root


def _store() -> Path:
    return runs_root() / "trusted-configs.json"


def _key(path: str) -> str:
    return Path(path).resolve().as_posix()


def _digest(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load() -> dict[str, str]:
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def is_trusted(path: str) -> bool:
    try:
        return _load().get(_key(path)) == _digest(path)
    except OSError:
        return False


def remember(path: str) -> None:
    """Best-effort: a failure only means the question comes back next time."""
    try:
        data = _load()
        data[_key(path)] = _digest(path)
        make_private_dir(runs_root())
        atomic_write(_store(), json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _outside_cwd(directory: str) -> bool:
    if not directory:
        return False
    target = Path(directory).expanduser().resolve()
    return not target.is_relative_to(Path.cwd().resolve())


def concerns(
    cfg: RunConfig, backends: list[tuple[str, str]], *, pinned: bool, relay: bool
) -> list[str]:
    """What this discovered config would do that needs consent, one line each.

    ``backends``: (backend, model) of the roles about to run; ``pinned``: they
    come from the file (no --backend / $PREBUTTAL_BACKEND); ``relay``: the
    relay spool is in use."""
    if not cfg.config_discovered:
        return []
    lines = []
    seen: set[str] = set()
    for backend, model in backends:
        if backend.startswith("agent-") and backend[6:] in cfg.agents:
            line = f"runs: {backend}: {cfg.agents[backend[6:]].describe()}"
        elif pinned and backend != "relay":
            line = f"sends the paper to: {backend}" + (f" / {model}" if model else "")
        else:
            continue
        if line not in seen:
            seen.add(line)
            lines.append(line)
    if _outside_cwd(cfg.output_dir):
        lines.append(f"writes reports to: {Path(cfg.output_dir).expanduser().resolve()}")
    if relay and _outside_cwd(cfg.relay_dir):
        lines.append(f"spools the paper to: {Path(cfg.relay_dir).expanduser().resolve()}")
    return lines


def pinned_by_file(cli_backend: str | None) -> bool:
    """Backends come from the file unless --backend or $PREBUTTAL_BACKEND won."""
    return cli_backend is None and not os.environ.get("PREBUTTAL_BACKEND", "").strip()
