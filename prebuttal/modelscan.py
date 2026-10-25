"""Model discovery: what models does each available backend actually offer?

Backs ``prebuttal models`` — a read-only listing so users can pick informed
``model = "..."`` values for prebuttal.toml.  API list endpoints are free,
single calls; agent CLIs don't expose a list API, so they get curated notes.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import httpx

_TIMEOUT = 8.0

# OpenAI's /v1/models returns everything (embeddings, audio, previews…);
# keep the ids a reviewer backend can actually use.
_OPENAI_KEEP = re.compile(r"^(gpt-|o[134](-|$)|chatgpt-)", re.I)
_OPENAI_DROP = re.compile(r"embed|audio|image|dall-e|whisper|tts|moderation|transcribe", re.I)

# Gemini's list also carries non-chat surfaces; reviewers need text models only.
_GEMINI_DROP = re.compile(
    r"embed|a2a|image|tts|audio|transcribe|computer-use|live|veo|imagen|"
    r"deep-research|learnlm|antigravity|customtools|banana|gemma|lyria|"
    r"robotics|omni",
    re.I,
)

# `claude -p --model` accepts stable aliases (plus full model ids).
_CLAUDE_ALIASES = ["opus", "sonnet", "haiku"]


@dataclass
class ModelListing:
    backend: str
    models: list[str]
    default: str
    note: str = ""

    def render(self, max_rows: int = 25) -> str:
        head = f"{self.backend}  (default: {self.default or 'CLI decides'})"
        lines = [head]
        if not self.models:
            lines.append(f"  {self.note or '(none listed)'}")
        else:
            shown = self.models[:max_rows]
            for m in shown:
                mark = " *" if m == self.default else ""
                lines.append(f"  - {m}{mark}")
            hidden = len(self.models) - len(shown)
            if hidden > 0:
                lines.append(f"  … and {hidden} more")
            if self.note:
                lines.append(f"  {self.note}")
        return "\n".join(lines)


def _get(url: str, headers: dict) -> dict | None:
    try:
        r = httpx.get(url, headers=headers, timeout=_TIMEOUT)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def gemini_models(api_key: str) -> list[str] | None:
    data = _get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": api_key},
    )
    if data is None:
        return None
    out = []
    for m in data.get("models", []):
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        mid = m.get("name", "").removeprefix("models/")
        if mid and not _GEMINI_DROP.search(mid):
            out.append(mid)
    return sorted(out)


def openai_models(api_key: str, base_url: str = "https://api.openai.com/v1") -> list[str] | None:
    data = _get(f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"})
    if data is None:
        return None
    ids = [
        m.get("id", "")
        for m in data.get("data", [])
        if _OPENAI_KEEP.match(m.get("id", "")) and not _OPENAI_DROP.search(m.get("id", ""))
    ]
    return sorted({i for i in ids if i})


def anthropic_models(api_key: str) -> list[str] | None:
    data = _get(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    if data is None:
        return None
    return sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))


def scan() -> list[ModelListing]:
    """Build listings for every known backend, scanning where possible."""
    from .providers.api import AnthropicProvider, GeminiProvider, OpenAIProvider

    out: list[ModelListing] = []

    gkey = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if gkey:
        models = gemini_models(gkey)
        out.append(
            ModelListing(
                "api-gemini",
                models or [],
                GeminiProvider.default_model(),
                "" if models is not None else "(could not reach the Gemini API)",
            )
        )
    else:
        out.append(
            ModelListing(
                "api-gemini",
                [],
                GeminiProvider.default_model(),
                "(no key — prebuttal key set gemini)",
            )
        )

    okey = os.environ.get("OPENAI_API_KEY")
    if okey:
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        models = openai_models(okey, base)
        out.append(
            ModelListing(
                "api-openai",
                models or [],
                OpenAIProvider.default_model(),
                "" if models is not None else "(could not reach the OpenAI-compatible endpoint)",
            )
        )
    else:
        out.append(ModelListing("api-openai", [], OpenAIProvider.default_model(), "(no key)"))

    akey = os.environ.get("ANTHROPIC_API_KEY")
    if akey:
        models = anthropic_models(akey)
        out.append(
            ModelListing(
                "api-anthropic",
                models or [],
                AnthropicProvider.default_model(),
                "" if models is not None else "(could not reach the Anthropic API)",
            )
        )
    else:
        out.append(ModelListing("api-anthropic", [], AnthropicProvider.default_model(), "(no key)"))

    from .providers.ollama import ollama_base_url, ollama_models

    installed = ollama_models(ollama_base_url())
    out.append(
        ModelListing(
            "ollama",
            installed,
            installed[0] if installed else "llama3.1",
            "(ollama pull <model> to add more)" if installed else "(not running)",
        )
    )

    out.append(
        ModelListing("agent-claude", list(_CLAUDE_ALIASES), "", "aliases; full model ids also work")
    )
    out.append(
        ModelListing(
            "agent-codex", [], "", "the codex CLI picks its own default — see `codex --help`"
        )
    )
    out.append(ModelListing("relay", [], "", "whoever answers the .req.md files decides"))
    return out


def render(listings: list[ModelListing]) -> str:
    lines = ["Available models per backend (* = current default)", ""]
    lines += [x.render() for x in listings]
    lines += [
        "",
        "Pick one and set it per reviewer in prebuttal.toml:",
        '  [[reviewer]]  backend = "api-gemini"   model = "gemini-2.5-pro"',
        "or force everywhere for one run:  prebuttal run ... --model <id>",
    ]
    return "\n".join(lines)
