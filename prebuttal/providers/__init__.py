"""Provider registry and factory."""

from __future__ import annotations

from collections.abc import Callable

from ..config import RunConfig
from .agent_cli import AgentCLIProvider, claude_provider, codex_provider
from .api import (
    API_PROVIDERS,
    AnthropicProvider,
    GeminiProvider,
    OpenAIProvider,
    OpenRouterProvider,
)
from .base import BaseProvider, Completion, ProviderError, TransientProviderError
from .detect import (
    RELAY_AGENT_HINT,
    BackendStatus,
    NoBackendError,
    auto_candidates,
    default_model_for,
    detect_host_agent,
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
    "api-openrouter": _factory(OpenRouterProvider),
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
    backend: str,
    model: str,
    cfg: RunConfig,
    *,
    timeout_s: float | None = None,
    effort: str = "",
) -> BaseProvider:
    provider = _make_provider(backend, model, cfg, timeout_s)
    provider.effort = effort
    return provider


def _make_provider(
    backend: str, model: str, cfg: RunConfig, timeout_s: float | None
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
    "API_PROVIDERS",
    "RELAY_AGENT_HINT",
    "AgentCLIProvider",
    "AnthropicProvider",
    "BackendStatus",
    "BaseProvider",
    "Completion",
    "GeminiProvider",
    "NoBackendError",
    "OllamaProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
    "ProviderError",
    "RelayProvider",
    "TransientProviderError",
    "auto_candidates",
    "build_provider",
    "default_model_for",
    "detect_host_agent",
    "ollama_models",
    "register_backend",
    "resolve_backends",
    "scan_backends",
]
