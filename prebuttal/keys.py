"""API key storage: `prebuttal key set/unset/status`.

Keys live in ``~/.prebuttal/keys.env`` (KEY=VALUE lines, user-only permissions,
same trust level as ~/.aws/credentials).  At CLI startup stored keys are applied
to the environment with ``setdefault`` — real environment variables always win,
so CI and power users are unaffected.
"""

from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path

from .runs import make_private_dir

# friendly name -> environment variable (accept either, case-insensitively)
KEY_MAP = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


class KeyError_(Exception):
    """Raised for unknown backend names in key commands."""


def keys_path() -> Path:
    base = os.environ.get("PREBUTTAL_HOME")
    root = Path(base) if base else Path.home() / ".prebuttal"
    return root / "keys.env"


def resolve_name(name: str) -> str:
    low = name.strip().lower()
    if low in KEY_MAP:
        return KEY_MAP[low]
    for var in KEY_MAP.values():
        if low == var.lower():
            return var
    raise KeyError_(
        f"unknown key '{name}' — use one of: {', '.join(KEY_MAP)} "
        f"(or the env var names: {', '.join(KEY_MAP.values())})"
    )


def _read_all() -> dict[str, str]:
    p = keys_path()
    if not p.is_file():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def store_key(var: str, value: str) -> None:
    value = value.strip()
    if not value:
        raise KeyError_("refusing to store an empty key")
    if any(c.isspace() for c in value):  # a pasted line break would forge a second entry
        raise KeyError_("refusing a key that contains spaces or line breaks")
    data = _read_all()
    data[var] = value
    p = keys_path()
    make_private_dir(p.parent)
    text = "# prebuttal API keys — loaded at startup; env vars take precedence\n"
    text += "".join(f"{k}={v}\n" for k, v in data.items())
    # O_CREAT with 0o600 (POSIX); on Windows the user profile already isolates it
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    with contextlib.suppress(OSError):  # pragma: no cover - e.g. some filesystems
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)


def unset_key(var: str) -> bool:
    data = _read_all()
    if var not in data:
        return False
    del data[var]
    p = keys_path()
    if not data:
        p.unlink(missing_ok=True)
        return True
    p.write_text(
        "# prebuttal API keys — loaded at startup; env vars take precedence\n"
        + "".join(f"{k}={v}\n" for k, v in data.items()),
        encoding="utf-8",
    )
    return True


_applied: set[str] = set()


def apply_stored_keys() -> list[str]:
    """Load stored keys into the environment (never overriding real ones)."""
    applied: list[str] = []
    known = set(KEY_MAP.values())
    for var, value in _read_all().items():
        # only API keys: a hand-edited PATH= or PYTHONPATH= line must not reach the env
        if value and var in known and var not in os.environ:
            os.environ[var] = value
            _applied.add(var)
            applied.append(var)
    return applied


def applied_keys() -> frozenset[str]:
    """Env vars that came from keys.env (not from the user's real environment)."""
    return frozenset(_applied)


def mask(var: str) -> str | None:
    value = os.environ.get(var) or _read_all().get(var)
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}…{value[-2:]}"


def source(var: str) -> str | None:
    if os.environ.get(var):
        return "stored, loaded this run" if var in _applied else "env"
    if _read_all().get(var):
        return f"stored ({keys_path()})"
    return None
