"""Ollama backend: local models — zero cost, papers never leave the machine."""

from __future__ import annotations

import os

import httpx

from ..models import Usage
from .base import BaseProvider, ProviderError, TransientProviderError


def ollama_base_url() -> str:
    """The Ollama URL to call. ``OLLAMA_HOST`` is often the *server's* bind
    address as Ollama documents it (``0.0.0.0:11434``, no scheme): a client
    reaches that on loopback, over http.  ``localhost`` and ``0.0.0.0`` are
    normalised here once, so listings, errors and requests all agree."""
    host = (
        (
            os.environ.get("PREBUTTAL_OLLAMA_HOST")
            or os.environ.get("OLLAMA_HOST")
            or "http://localhost:11434"
        )
        .strip()
        .rstrip("/")
    )
    if "://" not in host:
        host = "http://" + host
    scheme, rest = host.split("://", 1)
    if scheme == "http" and ":" not in rest.split("/", 1)[0]:  # like Ollama: port 11434
        rest = rest.replace("/", ":11434/", 1) if "/" in rest else rest + ":11434"
    return f"{scheme}://{rest}".replace("://0.0.0.0", "://127.0.0.1").replace(
        "://localhost:", "://127.0.0.1:"
    )


def ollama_models(base_url: str | None = None) -> list[str]:
    base = base_url or ollama_base_url()
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
        self.base_url = base

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
        if self.applied_effort:  # gpt-oss takes "low" | "medium" | "high"
            payload["think"] = self.applied_effort
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout_s)
        except httpx.HTTPError as e:
            raise TransientProviderError(f"cannot reach Ollama at {self.base_url}: {e}") from e
        if r.status_code >= 500:  # e.g. the model is still loading or ran out of memory
            raise TransientProviderError(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
        if r.status_code != 200:
            raise ProviderError(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
        try:
            data = r.json()
        except ValueError as e:
            raise ProviderError(f"non-JSON Ollama response: {r.text[:200]}") from e
        text = (data.get("message") or {}).get("content", "")
        usage = Usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0))
        return text, usage
