"""Persona library.

Each persona is a plain-text markdown file in this directory: the file name
(stem) is the persona id, the file body is the system prompt.  Drop a new
``my_persona.md`` here (or point ``prebuttal.toml`` at custom ids) and it is
immediately usable — community PRs welcome.
"""

from __future__ import annotations

from pathlib import Path

PERSONAS_DIR = Path(__file__).parent


def available_personas() -> list[str]:
    return sorted(p.stem for p in PERSONAS_DIR.glob("*.md"))


def load_persona(persona_id: str) -> str:
    path = PERSONAS_DIR / f"{persona_id}.md"
    if not path.is_file():
        raise KeyError(
            f"unknown persona '{persona_id}' — available: {', '.join(available_personas())}"
        )
    return path.read_text(encoding="utf-8").strip()
