"""Model discovery: what models does each available backend actually offer?

Backs ``prebuttal backends <name>`` — a read-only listing so users can pick informed
``model = "..."`` values for prebuttal.toml.  API list endpoints are free,
single calls; `agy models` lists its own; the other agent CLIs don't expose
a list, so they get curated notes.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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

# `agy models` lists each model once per thinking level (gemini-3.8-flash-high);
# prebuttal sets the level with `effort`, so the listing shows the base ids.
_AGY_LEVEL = re.compile(r"-(low|medium|high|xhigh|max)$")

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
        data = r.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _entries(data: dict, key: str) -> list[dict]:
    """The objects under ``data[key]``; anything else (a proxy's odd answer) is skipped."""
    items = data.get(key)
    return [m for m in items if isinstance(m, dict)] if isinstance(items, list) else []


def _obj(v: object) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _list(v: object) -> list:
    return v if isinstance(v, list) else []


def gemini_models(api_key: str) -> list[str] | None:
    data = _get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": api_key},
    )
    if data is None:
        return None
    out = []
    for m in _entries(data, "models"):
        if "generateContent" not in _list(m.get("supportedGenerationMethods")):
            continue
        mid = str(m.get("name") or "").removeprefix("models/")
        if mid and not _GEMINI_DROP.search(mid):
            out.append(mid)
    return sorted(out)


def openai_models(api_key: str, base_url: str = "https://api.openai.com/v1") -> list[str] | None:
    data = _get(f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"})
    if data is None:
        return None
    ids = (str(m.get("id") or "") for m in _entries(data, "data"))
    return sorted({i for i in ids if i and _OPENAI_KEEP.match(i) and not _OPENAI_DROP.search(i)})


def anthropic_models(api_key: str) -> list[str] | None:
    data = _get(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    if data is None:
        return None
    return sorted(str(m["id"]) for m in _entries(data, "data") if m.get("id"))


def openrouter_catalog(max_rows: int = 40) -> tuple[list[str], dict[str, str]] | None:
    """OpenRouter's /models endpoint is public (no key): free models first,
    then a curated notable set, each with a live per-1M price label."""
    data = _get("https://openrouter.ai/api/v1/models", headers={})
    if data is None:
        return None
    free: list[str] = []
    notable: list[str] = []
    prices: dict[str, str] = {}
    for m in _entries(data, "data"):
        mid = str(m.get("id") or "")
        if not mid or _OR_NOISE.search(mid):
            continue
        if "text" not in _list(_obj(m.get("architecture")).get("output_modalities")):
            continue
        if mid.endswith(":free"):
            prices[mid] = "(free)"
            free.append(mid)
            continue
        pricing = _obj(m.get("pricing"))
        pin: Any = pricing.get("prompt")
        pout: Any = pricing.get("completion")
        try:
            per_in, per_out = float(pin) * 1e6, float(pout) * 1e6
        except (TypeError, ValueError):
            continue
        prices[mid] = f"(${per_in:.2f}/${per_out:.2f} per 1M)"
        if _OR_NOTABLE.search(mid):
            notable.append(mid)
    ids = sorted(free) + sorted(notable)
    return ids[:max_rows], {k: prices[k] for k in ids[:max_rows]}


def _keyed(
    cls_name: str, short: str, fetch: Callable[[str], list[str] | None], where: str
) -> Callable[[], ModelListing]:
    """Lister for an API that needs a key to list its models."""

    def listing() -> ModelListing:
        from .providers import api

        cls = getattr(api, cls_name)
        key = cls.env_key()
        if not key:
            note = f"(no key — prebuttal key set {short})"
            return ModelListing(cls.BACKEND, [], cls.default_model(), note)
        models = fetch(key)
        note = "" if models is not None else f"(could not reach {where})"
        return ModelListing(cls.BACKEND, models or [], cls.default_model(), note)

    return listing


def _openai_here(key: str) -> list[str] | None:
    return openai_models(key, os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))


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
    from .providers.ollama import ollama_base_url, ollama_tags, pick_ollama_model

    base = ollama_base_url()
    tags = ollama_tags(base)
    installed = [t["name"] for t in tags]
    chat = pick_ollama_model(base, tags) if installed else ""
    if chat:
        note = "(ollama pull <model> to add more)"
    elif installed:  # still listed: `ollama rm` needs the names
        note = "(only embedding models, which can't review — ollama pull llama3.1)"
    else:
        note = "(not running)"
    return ModelListing("ollama", installed, chat or "none", note)


def agy_models() -> list[str]:
    """Base model ids from `agy models` (one call, no model is run)."""
    from .providers.agent_cli import _run

    proc = _run(["agy", "models"], "", stdin=False, timeout_s=30)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip()[-300:])
    out: list[str] = []
    for line in proc.stdout.splitlines():
        if "\t" not in line:
            continue  # "Fetching available models..."
        base = _AGY_LEVEL.sub("", line.split("\t", 1)[0].strip())
        if base and base not in out:
            out.append(base)
    return out


def _agy() -> ModelListing:
    note = "the agy CLI picks its own default; set the thinking level with `effort`"
    try:
        return ModelListing("agent-agy", agy_models(), "", note)
    except Exception as e:  # not installed, signed out, offline
        return ModelListing("agent-agy", [], "", f"could not list models ({e})")


_LISTERS: dict[str, Callable[[], ModelListing]] = {
    "api-gemini": _keyed("GeminiProvider", "gemini", gemini_models, "the Gemini API"),
    "api-openai": _keyed(
        "OpenAIProvider", "openai", _openai_here, "the OpenAI-compatible endpoint"
    ),
    "api-anthropic": _keyed(
        "AnthropicProvider", "anthropic", anthropic_models, "the Anthropic API"
    ),
    "api-openrouter": _openrouter,
    "ollama": _ollama,
    "agent-claude": lambda: ModelListing(
        "agent-claude", list(_CLAUDE_ALIASES), "", "aliases; full model ids also work"
    ),
    "agent-codex": lambda: ModelListing(
        "agent-codex", [], "", "the codex CLI picks its own default — see `codex --help`"
    ),
    "agent-agy": _agy,
    "relay": lambda: ModelListing("relay", [], "", "whoever answers the .req.md files decides"),
}
BACKENDS = tuple(_LISTERS)


def scan(only: str | None = None) -> list[ModelListing]:
    """Listings for every known backend, or just ``only`` (one network call at most)."""
    if only is not None:
        return [_LISTERS[only]()]
    return [lister() for lister in _LISTERS.values()]
