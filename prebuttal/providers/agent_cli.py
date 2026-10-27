"""Agent-CLI backends: run reviewer prompts through a headless coding agent.

This is the zero-API-key path for subscription users: ``claude -p`` (Claude
Code) and ``codex exec`` (OpenAI Codex CLI) authenticate with the user's
existing subscription.  Any other headless CLI can be registered in
prebuttal.toml under ``[agents.<name>]``.

The prompt is always delivered on stdin (papers far exceed argv limits).
Temperature/seed are *recorded* in the report — agent CLIs do not expose them.

The paper is untrusted input (any arXiv id can be reviewed), so the built-in
backends are locked down against prompt injection: ``claude`` runs with every
tool disabled and no MCP servers, ``codex`` in its read-only sandbox without
the user's config.toml (so no MCP servers) and without persisting the session,
and both in an empty temporary working directory instead of the user's project.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from .. import keys as key_store
from ..models import Usage
from .base import BaseProvider, ProviderError, TransientProviderError, strip_ansi

# Command-line arg length safety margin (Windows ~32k; stay well under).
_MAX_ARGV_CHARS = 24_000

# How claude / codex report a model id they don't know (lowercased).
_BAD_MODEL = (
    "unrecognized_model",  # claude: [claude-code:unrecognized_model]
    "may not exist or you may not have access",  # claude
    "model_not_found",  # codex (OpenAI error code)
)


def _child_env() -> dict[str, str]:
    """Environment for agent CLIs, minus API keys loaded from keys.env.

    Stored keys are meant for prebuttal's API backends only; leaking e.g.
    ANTHROPIC_API_KEY into `claude -p` would switch it from subscription auth
    to per-token API billing.  Keys the user exported themselves are kept.
    """
    applied = key_store.applied_keys()
    return {k: v for k, v in os.environ.items() if k not in applied}


def _is_batch_launcher(name: str) -> bool:
    """True when ``name`` runs through cmd.exe (a .cmd/.bat file on Windows)."""
    if os.name != "nt":
        return False
    exe = shutil.which(name) or name
    return exe.lower().endswith((".cmd", ".bat"))


def _run(
    cmd: list[str], prompt: str, *, stdin: bool, timeout_s: float, cwd: str | None = None
) -> subprocess.CompletedProcess:
    # Run what `prebuttal backends` detected: on Windows, npm installs
    # `claude.cmd` / `codex.cmd`, which CreateProcess can't find by bare name.
    exe = shutil.which(cmd[0])
    if exe:
        cmd = [exe, *cmd[1:]]
    try:
        return subprocess.run(
            cmd,
            input=prompt if stdin else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            env=_child_env(),
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as e:
        raise ProviderError(f"{cmd[0]} timed out after {timeout_s:.0f}s") from e
    except FileNotFoundError as e:
        raise ProviderError(f"agent CLI not found: {cmd[0]} (is it on PATH?)") from e
    except OSError:
        # Windows: .cmd/.bat launchers sometimes need an explicit cmd /c.
        if cmd[0].lower().endswith((".cmd", ".bat")):
            return _run(["cmd", "/c", *cmd], prompt, stdin=stdin, timeout_s=timeout_s, cwd=cwd)
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
        model_flag: str = "",
        isolate_cwd: bool = False,
        effort_args: tuple[str, ...] = (),
    ):
        """``model_flag``: how to forward `model` to the CLI.  "" = don't
        (custom agents); "append" = add `--model X` at the end; "before-last"
        = insert before the last arg (for CLIs whose final arg is the stdin
        prompt marker, e.g. `codex exec ... -`).  ``isolate_cwd``: run in an
        empty temp dir so an injected prompt finds no project files.
        ``effort_args``: flag template for the reasoning effort, with
        ``{effort}`` substituted, inserted where ``model_flag`` puts --model."""
        super().__init__(backend, model, timeout_s=timeout_s)
        self.command = list(command)
        self.stdin = stdin
        self.detail = detail
        self.model_flag = model_flag
        self.isolate_cwd = isolate_cwd
        self.effort_args = effort_args

    def describe(self) -> str:
        base = f"{self.backend} ({self.command[0]}, subscription auth)"
        return base + (f" / {self.model}" if self.model else "")

    def _build_command(self) -> list[str]:
        cmd = list(self.command)
        if not self.model_flag:
            return cmd
        flags: list[str] = []
        if self.model:
            flags += ["--model", self.model]
        if self.applied_effort and self.effort_args:
            flags += [a.format(effort=self.applied_effort) for a in self.effort_args]
        if self.model_flag == "before-last" and len(cmd) > 1:
            return cmd[:-1] + flags + [cmd[-1]]
        return cmd + flags

    def _complete(self, *, system, user, temperature, seed, max_tokens):
        if self.isolate_cwd:
            with tempfile.TemporaryDirectory(prefix="prebuttal-agent-") as cwd:
                return self._complete_in(system, user, cwd)
        return self._complete_in(system, user, None)

    def _complete_in(self, system: str, user: str, cwd: str | None):
        prompt = f"{system}\n\n---\n\n{user}"
        cmd = self._build_command()
        if self.stdin:
            proc = _run(cmd, prompt, stdin=True, timeout_s=self.timeout_s, cwd=cwd)
        else:
            if len(prompt) > _MAX_ARGV_CHARS:
                raise ProviderError(
                    f"prompt too long for argv ({len(prompt)} chars); "
                    "configure this agent with stdin = true"
                )
            if _is_batch_launcher(cmd[0]):
                # cmd.exe re-parses a .cmd/.bat command line: `&`, `|`, `%VAR%` in
                # the (untrusted) paper text would be run as commands
                raise ProviderError(
                    f"{cmd[0]} is a Windows batch launcher, which cannot safely take the "
                    "paper as an argument; configure this agent with stdin = true"
                )
            proc = _run([*cmd, prompt], "", stdin=False, timeout_s=self.timeout_s, cwd=cwd)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[-500:]
            if "unknown option" in err.lower() or "unexpected argument" in err.lower():
                # an outdated CLI that lacks the lock-down flags: retrying won't help
                raise ProviderError(
                    f"{cmd[0]} rejected a flag prebuttal needs ({err}) — "
                    f"update {cmd[0]} to its latest version"
                )
            if any(m in err.lower() for m in _BAD_MODEL):
                # a model id the CLI doesn't know: the same answer every attempt
                raise ProviderError(
                    f"{cmd[0]} rejected the model name ({err}) — check the model id "
                    f"against `{cmd[0]} --help` or its docs"
                )
            raise TransientProviderError(f"{cmd[0]} exited {proc.returncode}: {err}")
        return strip_ansi(proc.stdout or ""), Usage()


def claude_provider(model: str = "", *, timeout_s: float = 900.0) -> AgentCLIProvider:
    return AgentCLIProvider(
        "agent-claude",
        # no tools, no MCP servers: a reviewer only needs to read the prompt
        ["claude", "-p", "--tools", "", "--strict-mcp-config"],
        model=model,
        timeout_s=timeout_s,
        detail="Claude Code headless (`claude -p`), subscription auth, zero API key",
        model_flag="append",
        isolate_cwd=True,
        effort_args=("--effort", "{effort}"),
    )


def codex_provider(model: str = "", *, timeout_s: float = 900.0) -> AgentCLIProvider:
    return AgentCLIProvider(
        "agent-codex",
        # read-only sandbox for shell commands; no user config (= no MCP servers
        # an injected prompt could call); no session files with the paper on disk
        [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ignore-user-config",
            "--ephemeral",
            "-",
        ],
        model=model,
        timeout_s=timeout_s,
        detail="Codex CLI headless (`codex exec`), subscription auth, zero API key",
        model_flag="before-last",
        isolate_cwd=True,
        effort_args=("-c", 'model_reasoning_effort="{effort}"'),
    )
