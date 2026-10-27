"""Provider abstraction: every backend exposes one ``complete()`` call."""

from __future__ import annotations

import re
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import Usage, effort_support


class ProviderError(Exception):
    """Permanent failure (bad key, bad request, missing CLI...)."""


class TransientProviderError(Exception):
    """Retryable failure (429, 5xx, network hiccup).

    ``slow=True`` marks saturation-style failures (429, overloaded 503/529)
    where capacity can stay gone for minutes, so backoff is longer and gets
    more attempts.  ``retry_after``: the server's own wait hint, in seconds.
    """

    def __init__(self, message: str, *, slow: bool = False, retry_after: float | None = None):
        super().__init__(message)
        self.slow = slow
        self.retry_after = retry_after


# Overload waits: 15s, 30s, 60s, 90s (~3 min) before a reviewer is given up.
SLOW_MIN_RETRIES = 4
_MAX_WAIT_S = 120.0


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
    # backends whose _complete() takes ``images`` (PNG bytes shown with the user turn)
    supports_images = False

    def __init__(self, backend: str, model: str, *, timeout_s: float = 900.0):
        self.backend = backend
        self.model = model
        self.timeout_s = timeout_s
        self.effort = ""  # requested reasoning effort ("" = model default)

    @property
    def applied_effort(self) -> str:
        """The effort this provider actually sends; "" when unset or unsupported."""
        return self.effort if self.effort and effort_support(self.backend, self.model) else ""

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
        retries: int = 3,
        images: list[bytes] | None = None,
    ) -> Completion:
        # only image-capable backends get the argument: others keep their signature
        extra = {"images": images} if images and self.supports_images else {}
        attempt = 0
        while True:
            try:
                text, usage = self._complete(
                    system=system,
                    user=user,
                    temperature=temperature,
                    seed=seed,
                    max_tokens=max_tokens,
                    **extra,
                )
                if not text or not text.strip():
                    raise TransientProviderError("empty completion")
                return Completion(text=text, usage=usage, model=self.model, backend=self.backend)
            except TransientProviderError as e:
                # overload gets more patience, but retries=0 (a repair pass) stays 0
                budget = max(retries, SLOW_MIN_RETRIES) if e.slow and retries > 0 else retries
                if attempt >= budget:
                    raise ProviderError(f"[{self.backend}] {e}") from e
                wait = e.retry_after
                if wait is None:
                    wait = min(2**attempt * (15 if e.slow else 3), 90)
                wait = min(max(wait, 0.0), _MAX_WAIT_S)
                print(
                    f"[{self.backend}] {str(e)[:120]} — retrying in {wait:.0f}s "
                    f"({attempt + 1}/{budget})",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(wait)
                attempt += 1

    def describe(self) -> str:
        model = f" / {self.model}" if self.model else ""
        return f"{self.backend}{model}"
