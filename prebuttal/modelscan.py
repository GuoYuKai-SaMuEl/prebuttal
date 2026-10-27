"""Model discovery: what models does each available backend actually offer?

Backs ``prebuttal backends <name>`` — a read-only listing so users can pick informed
``model = "..."`` values for prebuttal.toml.  API list endpoints are free,
single calls; agent CLIs don't expose a list API, so they get curated notes.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
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

# OpenRouter carries ~470 ids; keep the ones a reviewer backend can use.
_OR_NOISE = re.compile(
    r"embed|rerank|guard|whisper|-vl$|video|image|tts|lyria|veo|banana|"
    r"diffusion|sora|online|sora|voice",
    re.I,
)
# No popularity field on the endpoint — curate by known family names instead.
_OR_NOTABLE = re.compile(
    r"(^|/)(llama|qwen|deepseek|gemini|gpt|claude|kimi|glm|minimax|mistral|"
    r"gemma|phi|nemotron|grok)",
    re.I,
)


@dataclass
class ModelListing:
    backend: str
    models: list[str]
    default: str
    note: str = ""
    prices: dict[str, str] | None = None  # id -> price label (OpenRouter live)

    def render(self, max_rows: int = 25) -> str:
        head = f"{self.backend}  (default: {self.default or 'CLI decides'})"
        lines = [head]
        if not self.models:
            lines.append(f"  {self.note or '(none listed)'}")
        else:
            shown = self.models[:max_rows]
            for m in shown:
                mark = " *" if m == self.default else ""
                price = f"  {self.prices[m]}" if self.prices and m in self.prices else ""
                lines.append(f"  - {m}{mark}{price}")
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


def openrouter_catalog(max_rows: int = 40) -> tuple[list[str], dict[str, str]] | None:
    """OpenRouter's /models endpoint is public (no key): free models first,
    then a curated notable set, each with a live per-1M price label."""
    data = _get("https://openrouter.ai/api/v1/models", headers={})
    if data is None:
        return None
    free: list[str] = []
    notable: list[str] = []
    prices: dict[str, str] = {}
    for m in data.get("data", []):
        mid = m.get("id", "")
        if not mid or _OR_NOISE.search(mid):
            continue
        arch = m.get("architecture") or {}
        if "text" not in (arch.get("output_modalities") or []):
            continue
        if mid.endswith(":free"):
            prices[mid] = "(free)"
            free.append(mid)
            continue
        pin, pout = m.get("pricing", {}).get("prompt"), m.get("pricing", {}).get("completion")
        try:
            per_in, per_out = float(pin) * 1e6, float(pout) * 1e6
        except (TypeError, ValueError):
            continue
        prices[mid] = f"(${per_in:.2f}/${per_out:.2f} per 1M)"
        if _OR_NOTABLE.search(mid):
            notable.append(mid)
    ids = sorted(free) + sorted(notable)
    return ids[:max_rows], {k: prices[k] for k in ids[:max_rows]}


def _gemini() -> ModelListing:
    from .providers.api import GeminiProvider

    gkey = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not gkey:
        return ModelListing(
            "api-gemini", [], GeminiProvider.default_model(), "(no key — prebuttal key set gemini)"
        )
    models = gemini_models(gkey)
    note = "" if models is not None else "(could not reach the Gemini API)"
    return ModelListing("api-gemini", models or [], GeminiProvider.default_model(), note)


def _openai() -> ModelListing:
    from .providers.api import OpenAIProvider

    okey = os.environ.get("OPENAI_API_KEY")
    if not okey:
        return ModelListing(
            "api-openai", [], OpenAIProvider.default_model(), "(no key — prebuttal key set openai)"
        )
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    models = openai_models(okey, base)
    note = "" if models is not None else "(could not reach the OpenAI-compatible endpoint)"
    return ModelListing("api-openai", models or [], OpenAIProvider.default_model(), note)


def _anthropic() -> ModelListing:
    from .providers.api import AnthropicProvider

    akey = os.environ.get("ANTHROPIC_API_KEY")
    if not akey:
        return ModelListing(
            "api-anthropic",
            [],
            AnthropicProvider.default_model(),
            "(no key — prebuttal key set anthropic)",
        )
    models = anthropic_models(akey)
    note = "" if models is not None else "(could not reach the Anthropic API)"
    return ModelListing("api-anthropic", models or [], AnthropicProvider.default_model(), note)


def _openrouter() -> ModelListing:
    from .providers.api import OpenRouterProvider

    cat = openrouter_catalog()  # public: shown even without a key
    if cat is None:
        return ModelListing(
            "api-openrouter",
            [],
            OpenRouterProvider.default_model(),
            "(could not reach openrouter.ai)",
        )
    ids, or_prices = cat
    return ModelListing(
        "api-openrouter",
        ids,
        OpenRouterProvider.default_model(),
        "free ids first; any id from openrouter.ai/models works — "
        "set OPENROUTER_API_KEY (or `prebuttal key set openrouter`) to use",
        prices=or_prices,
    )


def _ollama() -> ModelListing:
    from .providers.ollama import ollama_base_url, ollama_models

    installed = ollama_models(ollama_base_url())
    return ModelListing(
        "ollama",
        installed,
        installed[0] if installed else "llama3.1",
        "(ollama pull <model> to add more)" if installed else "(not running)",
    )


_LISTERS: dict[str, Callable[[], ModelListing]] = {
    "api-gemini": _gemini,
    "api-openai": _openai,
    "api-anthropic": _anthropic,
    "api-openrouter": _openrouter,
    "ollama": _ollama,
    "agent-claude": lambda: ModelListing(
        "agent-claude", list(_CLAUDE_ALIASES), "", "aliases; full model ids also work"
    ),
    "agent-codex": lambda: ModelListing(
        "agent-codex", [], "", "the codex CLI picks its own default — see `codex --help`"
    ),
    "relay": lambda: ModelListing("relay", [], "", "whoever answers the .req.md files decides"),
}
BACKENDS = tuple(_LISTERS)


def scan(only: str | None = None) -> list[ModelListing]:
    """Listings for every known backend, or just ``only`` (one network call at most)."""
    if only is not None:
        return [_LISTERS[only]()]
    return [lister() for lister in _LISTERS.values()]


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
