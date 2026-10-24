"""Agent-CLI backends: run reviewer prompts through a headless coding agent.

This is the zero-API-key path for subscription users: ``claude -p`` (Claude
Code) and ``codex exec`` (OpenAI Codex CLI) authenticate with the user's
existing subscription.  Any other headless CLI can be registered in
prebuttal.toml under ``[agents.<name>]``.

The prompt is always delivered on stdin (papers far exceed argv limits).
Temperature/seed are *recorded* in the report — agent CLIs do not expose them.
"""

from __future__ import annotations

import subprocess

from ..models import Usage
from .base import BaseProvider, ProviderError, TransientProviderError, strip_ansi

# Command-line arg length safety margin (Windows ~32k; stay well under).
_MAX_ARGV_CHARS = 24_000


def _run(
    cmd: list[str], prompt: str, *, stdin: bool, timeout_s: float
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            input=prompt if stdin else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        raise ProviderError(f"{cmd[0]} timed out after {timeout_s:.0f}s") from e
    except FileNotFoundError as e:
        raise ProviderError(f"agent CLI not found: {cmd[0]} (is it on PATH?)") from e
    except OSError:
        # Windows: .cmd/.bat launchers sometimes need an explicit cmd /c.
        if cmd[0].lower().endswith((".cmd", ".bat")):
            return _run(["cmd", "/c", *cmd], prompt, stdin=stdin, timeout_s=timeout_s)
        raise


class AgentCLIProvider(BaseProvider):
    kind = "agent"

    def __init__(
        self,
        backend: str,
        command: list[str],
        *,
        model: str = "",
        stdin: bool = True,
        timeout_s: float = 900.0,
        detail: str = "",
    ):
        super().__init__(backend, model, timeout_s=timeout_s)
        self.command = list(command)
        self.stdin = stdin
        self.detail = detail

    def describe(self) -> str:
        base = f"{self.backend} ({self.command[0]}, subscription auth)"
        return base + (f" / {self.model}" if self.model else "")

    def _complete(self, *, system, user, temperature, seed, max_tokens):
        prompt = f"{system}\n\n---\n\n{user}"
        if self.stdin:
            proc = _run(self.command, prompt, stdin=True, timeout_s=self.timeout_s)
        else:
            if len(prompt) > _MAX_ARGV_CHARS:
                raise ProviderError(
                    f"prompt too long for argv ({len(prompt)} chars); "
                    "configure this agent with stdin = true"
                )
            proc = _run([*self.command, prompt], "", stdin=False, timeout_s=self.timeout_s)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[-500:]
            raise TransientProviderError(f"{self.command[0]} exited {proc.returncode}: {err}")
        return strip_ansi(proc.stdout or ""), Usage()


def claude_provider(model: str = "", *, timeout_s: float = 900.0) -> AgentCLIProvider:
    return AgentCLIProvider(
        "agent-claude",
        ["claude", "-p"],
        model=model,
        timeout_s=timeout_s,
        detail="Claude Code headless (`claude -p`), subscription auth, zero API key",
    )


def codex_provider(model: str = "", *, timeout_s: float = 900.0) -> AgentCLIProvider:
    return AgentCLIProvider(
        "agent-codex",
        ["codex", "exec", "--skip-git-repo-check", "-"],
        model=model,
        timeout_s=timeout_s,
        detail="Codex CLI headless (`codex exec`), subscription auth, zero API key",
    )
