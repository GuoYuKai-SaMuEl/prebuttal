"""API providers: OpenAI, Anthropic, Gemini (BYO key).

JSON mode is requested where the API supports it; the orchestrator's parser
tolerates markdown fences and surrounding chatter anyway.
"""

from __future__ import annotations

import os

import httpx

from ..models import Usage
from .base import BaseProvider, ProviderError, TransientProviderError


def _env_default(name: str, fallback: str) -> str:
    return os.environ.get(f"PREBUTTAL_{name}_MODEL", fallback)


class _HTTPProvider(BaseProvider):
    kind = "api"

    def _post_json(self, url: str, headers: dict, payload: dict) -> dict:
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                r = client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as e:
            raise TransientProviderError(f"network error: {e}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise TransientProviderError(f"HTTP {r.status_code}: {r.text[:200]}")
        if r.status_code != 200:
            raise ProviderError(f"HTTP {r.status_code}: {r.text[:400]}")
        try:
            return r.json()
        except ValueError as e:
            raise ProviderError(f"non-JSON API response: {r.text[:200]}") from e


class OpenAIProvider(_HTTPProvider):
    DEFAULT_MODEL = "gpt-5.6-terra"

    def __init__(self, backend: str = "api-openai", model: str = "", **kw):
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderError("OPENAI_API_KEY is not set (get one at platform.openai.com)")
        super().__init__(backend, model or _env_default("OPENAI", self.DEFAULT_MODEL), **kw)
        self.api_key = key
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    @classmethod
    def default_model(cls) -> str:
        return _env_default("OPENAI", cls.DEFAULT_MODEL)

    def _complete(self, *, system, user, temperature, seed, max_tokens):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        if seed is not None:
            payload["seed"] = seed
        data = self._post_json(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            payload=payload,
        )
        try:
            text = data["choices"][0]["message"]["content"] or ""
            u = data.get("usage", {})
            usage = Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"unexpected OpenAI response shape: {str(data)[:300]}") from e
        return text, usage


class OpenRouterProvider(_HTTPProvider):
    """OpenRouter — one key, hundreds of models, OpenAI-compatible wire format.

    The default model is a ``:free`` id so the zero-cost story holds out of the
    box (free models are rate-limited by OpenRouter; 3 reviewers + AC fits).
    ``response_format`` is deliberately NOT forced: many models behind OpenRouter
    reject JSON mode, and the orchestrator's extractor tolerates prose anyway.
    """

    # Non-reasoning instruct model: reasoning models on the free tier burn the
    # whole max-tokens budget on hidden thinking and return no content.
    DEFAULT_MODEL = "google/gemma-4-31b-it:free"
    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, backend: str = "api-openrouter", model: str = "", **kw):
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise ProviderError(
                "OPENROUTER_API_KEY is not set (get one at openrouter.ai/keys; "
                "free models available)"
            )
        super().__init__(backend, model or _env_default("OPENROUTER", self.DEFAULT_MODEL), **kw)
        self.api_key = key

    @classmethod
    def default_model(cls) -> str:
        return _env_default("OPENROUTER", cls.DEFAULT_MODEL)

    def _complete(self, *, system, user, temperature, seed, max_tokens):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if seed is not None:
            payload["seed"] = seed
        data = self._post_json(
            f"{self.BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                # OpenRouter's suggested app attribution headers
                "HTTP-Referer": "https://github.com/GuoYuKai-SaMuEl/prebuttal",
                "X-Title": "prebuttal",
            },
            payload=payload,
        )
        try:
            choice = data["choices"][0]
            content = choice["message"].get("content")
            if isinstance(content, list):  # some upstream providers send parts
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            text = content or ""
            u = data.get("usage") or {}
            usage = Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"unexpected OpenRouter response shape: {str(data)[:300]}") from e
        if not text.strip():
            finish = choice.get("finish_reason", "")
            details = u.get("completion_tokens_details") or {}
            reasoning = details.get("reasoning_tokens", 0) or 0
            if finish == "length" or reasoning:
                raise ProviderError(
                    f"{self.model} spent the whole {max_tokens}-token budget on hidden "
                    f"reasoning (reasoning_tokens={reasoning}, finish_reason={finish}) and "
                    "returned no content; pick a non-reasoning model (`prebuttal models`) "
                    "or raise max-tokens"
                )
            raise TransientProviderError("empty completion from OpenRouter")
        return text, usage


class AnthropicProvider(_HTTPProvider):
    DEFAULT_MODEL = "claude-sonnet-5-5"

    def __init__(self, backend: str = "api-anthropic", model: str = "", **kw):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY is not set (get one at console.anthropic.com)")
        super().__init__(backend, model or _env_default("ANTHROPIC", self.DEFAULT_MODEL), **kw)
        self.api_key = key

    @classmethod
    def default_model(cls) -> str:
        return _env_default("ANTHROPIC", cls.DEFAULT_MODEL)

    def _complete(self, *, system, user, temperature, seed, max_tokens):
        # Anthropic has no seed parameter: recorded in the report, not enforced.
        payload = {
            "model": self.model,
            "system": system,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": user}],
        }
        data = self._post_json(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            payload=payload,
        )
        try:
            text = "".join(b.get("text", "") for b in data["content"])
            u = data.get("usage", {})
            usage = Usage(u.get("input_tokens", 0), u.get("output_tokens", 0))
        except (KeyError, TypeError) as e:
            raise ProviderError(f"unexpected Anthropic response shape: {str(data)[:300]}") from e
        return text, usage


class GeminiProvider(_HTTPProvider):
    """Google Gemini — the default "first key" path thanks to its free tier."""

    DEFAULT_MODEL = "gemini-3.5-flash-lite"

    def __init__(self, backend: str = "api-gemini", model: str = "", **kw):
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ProviderError(
                "GEMINI_API_KEY is not set (free tier available at aistudio.google.com)"
            )
        super().__init__(backend, model or _env_default("GEMINI", self.DEFAULT_MODEL), **kw)
        self.api_key = key

    @classmethod
    def default_model(cls) -> str:
        return _env_default("GEMINI", cls.DEFAULT_MODEL)

    def _complete(self, *, system, user, temperature, seed, max_tokens):
        gen = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        }
        if seed is not None:
            gen["seed"] = seed
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen,
        }
        data = self._post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self.api_key},
            payload=payload,
        )
        try:
            cand = data["candidates"][0]
            text = "".join(p.get("text", "") for p in cand["content"]["parts"])
            u = data.get("usageMetadata", {})
            usage = Usage(u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0))
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"unexpected Gemini response shape: {str(data)[:300]}") from e
        return text, usage
