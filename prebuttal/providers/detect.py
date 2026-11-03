"""Backend auto-detection: pick the cheapest zero-friction path at startup.

Preference order (plan §4): agent CLIs (subscription, zero key) first —
Claude + Codex together give cross-model reviews for free — then the Gemini
free tier, then OpenAI/Anthropic keys, then a local Ollama.
"""

from __future__ import annotations

import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from ..config import RunConfig
from ..keys import KEY_MAP
from .agent_cli import _run
from .api import API_PROVIDERS
from .ollama import ollama_base_url, ollama_tags, pick_ollama_model

# How each agent CLI reports its sign-in without calling a model, and the
# command that fixes it.  Exit 0 = signed in on both (checked on claude 2.1,
# codex 0.164); a CLI too old to have the command is given the benefit of
# the doubt.
_SIGN_IN = {
    "claude": (["auth", "status"], "claude auth login"),
    "codex": (["login", "status"], "codex login"),
}

_PREFERENCE = [
    "agent-claude",
    "agent-codex",
    "api-gemini",
    "api-openai",
    "api-anthropic",
    "api-openrouter",
    "ollama",
]

# Always "available" but never picked by auto mode: a relay reviewer waits for a
# human/agent to write answers, so it must be an explicit choice.
EXPLICIT_ONLY = frozenset({"relay"})

# Env vars coding agents set in the shells they spawn (best-effort detection;
# only markers the agents document/emit themselves).
_HOST_AGENT_MARKERS = (
    ("CLAUDECODE", "Claude Code"),
    ("GEMINI_CLI", "Gemini CLI"),
)

RELAY_AGENT_HINT = (
    "running inside {agent}. To have YOUR OWN subagents act as the reviewers, "
    "re-run with --backend relay (or set PREBUTTAL_BACKEND=relay) in the "
    "background and answer the relay/*.req.md files — see https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/skills/prebuttal/SKILL.md#relay-mode-zero-api-key-zero-cli-install"
)


def detect_host_agent() -> str | None:
    """Name of the coding agent this process runs under, if recognizable."""
    for var, name in _HOST_AGENT_MARKERS:
        if os.environ.get(var, "").strip() not in ("", "0"):
            return name
    return None


@dataclass(frozen=True)
class BackendStatus:
    backend: str
    kind: str
    available: bool
    detail: str
    default_model: str = ""


class NoBackendError(Exception):
    def __init__(self, statuses: list[BackendStatus]):
        hint = (
            "no review backend available. Install one of:\n"
            "  - Claude Code CLI  (npm i -g @anthropic-ai/claude-code)  -> agent-claude\n"
            "  - Codex CLI        (npm i -g @openai/codex)              -> agent-codex\n"
            "  - set GEMINI_API_KEY (free tier)                         -> api-gemini\n"
            "  - set OPENAI_API_KEY / ANTHROPIC_API_KEY                 -> api-openai/-anthropic\n"
            "  - set OPENROUTER_API_KEY (has :free models)              -> api-openrouter\n"
            "  - run Ollama locally (ollama pull llama3.1)               -> ollama\n"
            "Or answer the reviews yourself / via your agent: --backend relay\n"
            "See `prebuttal backends`."
        )
        super().__init__(hint)
        self.statuses = statuses


def signed_out(cli: str) -> bool:
    """True only when the CLI's own status command says it is not signed in.

    Installed is not enough: a signed-out (or expired) `claude` would be
    picked first and fail every review. Anything unclear — no such command,
    a timeout — counts as signed in, as before this check existed.
    """
    args, _ = _SIGN_IN[cli]
    try:
        proc = _run([cli, *args], "", stdin=False, timeout_s=20)
    except Exception:
        return False
    if proc.returncode == 0:
        return False
    if cli == "claude":
        try:
            return json.loads(proc.stdout).get("loggedIn") is False
        except (ValueError, AttributeError):
            return False
    return "not logged in" in f"{proc.stdout}\n{proc.stderr}".lower()


def scan_backends(cfg: RunConfig | None = None) -> list[BackendStatus]:
    out: list[BackendStatus] = []

    paths = {cli: shutil.which(cli) for cli in _SIGN_IN}
    found = [cli for cli, path in paths.items() if path]
    with ThreadPoolExecutor(max_workers=2) as pool:  # each takes a second or so
        out_of = dict(zip(found, pool.map(signed_out, found), strict=True))
    for backend, cli in (("agent-claude", "claude"), ("agent-codex", "codex")):
        path = paths[cli]
        if out_of.get(cli):
            detail = f"{cli} CLI {path}, not signed in — run `{_SIGN_IN[cli][1]}`"
        else:
            detail = f"{cli} CLI {path or 'not found on PATH'}"
        out.append(
            BackendStatus(backend, "agent", path is not None and not out_of.get(cli), detail)
        )

    for cls in API_PROVIDERS:
        env = next((v for v in cls.KEY_VARS if os.environ.get(v)), cls.KEY_VARS[0])
        has = bool(os.environ.get(env))
        note = f"{env} set"
        if not has:
            friendly = next(k for k, v in KEY_MAP.items() if v == env)
            note = f"{env} not set ({cls.KEY_HELP}; `prebuttal key set {friendly}`)"
        out.append(BackendStatus(cls.BACKEND, "api", has, note, cls.default_model() if has else ""))

    base = ollama_base_url()
    tags = ollama_tags(base)
    models = [t["name"] for t in tags]
    chat = pick_ollama_model(base, tags) if models else ""
    if chat:
        ollama_detail = f"running at {base}, models: {', '.join(models[:3])}"
    elif models:
        ollama_detail = (
            f"running at {base}, but only embedding models ({', '.join(models[:3])}) — "
            "pull one that chats: `ollama pull llama3.1`"
        )
    else:
        ollama_detail = f"not reachable at {base}"
    out.append(BackendStatus("ollama", "ollama", bool(chat), ollama_detail, chat))

    out.append(
        BackendStatus(
            "relay",
            "relay",
            True,
            "file bridge: you, your agent's subagents or any system answer "
            "(explicit only: --backend relay)",
        )
    )

    if cfg:
        for name, spec in cfg.agents.items():
            path = shutil.which(spec.command[0]) if spec.command else None
            out.append(
                BackendStatus(
                    f"agent-{name}",
                    "agent",
                    path is not None,
                    f"custom agent {' '.join(spec.command)} {path or 'not found'}",
                )
            )
    return out


def auto_candidates(statuses: list[BackendStatus], cfg: RunConfig | None) -> list[BackendStatus]:
    """Backends that ``auto`` may pick, in preference order (never EXPLICIT_ONLY)."""
    by_name = {s.backend: s for s in statuses}
    order: list[BackendStatus] = []
    for name in _PREFERENCE:
        s = by_name.get(name)
        if s and s.available:
            order.append(s)
    if cfg:
        for name in cfg.agents:
            s = by_name.get(f"agent-{name}")
            if s and s.available and s not in order:
                order.append(s)
    # any other available, non-explicit backend (registered plugins) joins last
    known = {s.backend for s in order}
    for s in sorted(statuses, key=lambda x: x.backend):
        if s.available and s.backend not in known and s.backend not in EXPLICIT_ONLY:
            order.append(s)
    return order


def resolve_backends(
    cfg: RunConfig, statuses: list[BackendStatus]
) -> tuple[list[tuple[str, str, str]], tuple[str, str]]:
    """Assign concrete (backend, model) to each reviewer and the AC.

    ``auto`` reviewers get distinct backends in preference order (cycling when
    fewer are available); explicit backends pass through untouched, so an
    all-explicit setup (e.g. ``--backend relay``) needs no auto candidate.
    """
    avail = auto_candidates(statuses, cfg)
    needs_auto = cfg.ac.backend == "auto" or any(r.backend == "auto" for r in cfg.reviewers)
    if needs_auto and not avail:
        raise NoBackendError(statuses)

    resolved: list[tuple[str, str, str]] = []
    auto_idx = 0
    for rcfg in cfg.reviewers:
        if rcfg.backend == "auto":
            s = avail[auto_idx % len(avail)]
            auto_idx += 1
            resolved.append((rcfg.id, s.backend, rcfg.model or s.default_model))
        else:
            resolved.append((rcfg.id, rcfg.backend, rcfg.model))

    if cfg.ac.backend == "auto":
        ac = (avail[0].backend, cfg.ac.model or avail[0].default_model)
    else:
        ac = (cfg.ac.backend, cfg.ac.model)
    return resolved, ac


def default_model_for(backend: str, statuses: list[BackendStatus]) -> str:
    for s in statuses:
        if s.backend == backend:
            return s.default_model
    return ""
