"""Provider abstraction: every backend exposes one ``complete()`` call."""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import Usage


class ProviderError(Exception):
    """Permanent failure (bad key, bad request, missing CLI...)."""


class TransientProviderError(Exception):
    """Retryable failure (429, 5xx, network hiccup)."""


@dataclass
class Completion:
    text: str
    usage: Usage
    model: str
    backend: str


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][A-B0-9]|\r")


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


class BaseProvider(ABC):
    kind = "api"  # "api" | "agent" | "ollama"

    def __init__(self, backend: str, model: str, *, timeout_s: float = 900.0):
        self.backend = backend
        self.model = model
        self.timeout_s = timeout_s

    @abstractmethod
    def _complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        seed: int | None,
        max_tokens: int,
    ) -> tuple[str, Usage]:
        """Do one completion; raise Transient/Provider errors, never return empty silently."""

    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.4,
        seed: int | None = None,
        max_tokens: int = 4000,
        retries: int = 2,
    ) -> Completion:
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                text, usage = self._complete(
                    system=system,
                    user=user,
                    temperature=temperature,
                    seed=seed,
                    max_tokens=max_tokens,
                )
                if not text or not text.strip():
                    raise TransientProviderError("empty completion")
                return Completion(text=text, usage=usage, model=self.model, backend=self.backend)
            except TransientProviderError as e:
                last = e
                if attempt < retries:
                    time.sleep(min(2**attempt * 2, 20))
        raise ProviderError(f"[{self.backend}] {last}")

    def describe(self) -> str:
        model = f" / {self.model}" if self.model else ""
        return f"{self.backend}{model}"
