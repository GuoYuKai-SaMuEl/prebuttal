"""Ollama backend: local models — zero cost, papers never leave the machine."""

from __future__ import annotations

import os

import httpx

from ..models import Usage
from .base import BaseProvider, ProviderError, TransientProviderError


def ollama_base_url() -> str:
    return (
        os.environ.get("PREBUTTAL_OLLAMA_HOST")
        or os.environ.get("OLLAMA_HOST")
        or "http://localhost:11434"
    ).rstrip("/")


def ollama_models(base_url: str | None = None) -> list[str]:
    base = (base_url or ollama_base_url()).replace("://localhost:", "://127.0.0.1:")
    try:
        r = httpx.get(f"{base}/api/tags", timeout=2.5)
        r.raise_for_status()
        return [m.get("name", "") for m in r.json().get("models", []) if m.get("name")]
    except Exception:
        return []


class OllamaProvider(BaseProvider):
    kind = "ollama"

    def __init__(self, backend: str = "ollama", model: str = "", **kw):
        base = ollama_base_url()
        if not model:
            installed = ollama_models(base)
            if not installed:
                raise ProviderError(
                    f"Ollama not reachable at {base} — start it (`ollama serve`) "
                    "and pull a model (`ollama pull llama3.1`)"
                )
            model = installed[0]
        super().__init__(backend, model, **kw)
        self.base_url = base.replace("://localhost:", "://127.0.0.1:")

    def _complete(self, *, system, user, temperature, seed, max_tokens):
        options = {"temperature": temperature, "num_predict": max_tokens}
        if seed is not None:
            options["seed"] = seed
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": options,
        }
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout_s)
        except httpx.HTTPError as e:
            raise TransientProviderError(f"cannot reach Ollama at {self.base_url}: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        text = data.get("message", {}).get("content", "")
        usage = Usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0))
        return text, usage
