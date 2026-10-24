"""Provider registry and factory."""

from __future__ import annotations

from collections.abc import Callable

from ..config import RunConfig
from .agent_cli import AgentCLIProvider, claude_provider, codex_provider
from .api import AnthropicProvider, GeminiProvider, OpenAIProvider
from .base import BaseProvider, Completion, ProviderError, TransientProviderError
from .detect import (
    BackendStatus,
    NoBackendError,
    auto_candidates,
    default_model_for,
    resolve_backends,
    scan_backends,
)
from .ollama import OllamaProvider, ollama_models
from .relay import RelayProvider

Factory = Callable[[str, RunConfig, float], BaseProvider]


def _factory(cls):
    def make(model: str, cfg: RunConfig, timeout_s: float) -> BaseProvider:
        return cls(model=model, timeout_s=timeout_s)

    return make


_FACTORIES: dict[str, Factory] = {
    "api-openai": _factory(OpenAIProvider),
    "api-anthropic": _factory(AnthropicProvider),
    "api-gemini": _factory(GeminiProvider),
    "ollama": _factory(OllamaProvider),
    "agent-claude": lambda model, cfg, t: claude_provider(model, timeout_s=t),
    "agent-codex": lambda model, cfg, t: codex_provider(model, timeout_s=t),
    "relay": lambda model, cfg, t: RelayProvider(
        model=model or "external responder",
        spool_dir=cfg.relay_dir,
        timeout_s=cfg.relay_timeout_s,
    ),
}


def register_backend(name: str, factory: Factory) -> None:
    """Register (or replace) a backend — plugin/test hook."""
    _FACTORIES[name] = factory


def build_provider(
    backend: str, model: str, cfg: RunConfig, *, timeout_s: float | None = None
) -> BaseProvider:
    timeout = timeout_s if timeout_s is not None else cfg.timeout_s
    if backend.startswith("agent-") and backend[6:] in cfg.agents:
        spec = cfg.agents[backend[6:]]
        return AgentCLIProvider(
            backend, spec.command, model=model, stdin=spec.stdin, timeout_s=timeout
        )
    factory = _FACTORIES.get(backend)
    if factory is None:
        known = ", ".join(sorted(_FACTORIES))
        raise ProviderError(
            f"unknown backend '{backend}' — known: {known} (custom: [agents.<name>])"
        )
    return factory(model, cfg, timeout)


__all__ = [
    "AgentCLIProvider",
    "AnthropicProvider",
    "BackendStatus",
    "BaseProvider",
    "Completion",
    "GeminiProvider",
    "NoBackendError",
    "OllamaProvider",
    "OpenAIProvider",
    "ProviderError",
    "RelayProvider",
    "TransientProviderError",
    "auto_candidates",
    "build_provider",
    "default_model_for",
    "ollama_models",
    "register_backend",
    "resolve_backends",
    "scan_backends",
]
