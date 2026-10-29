"""Dry run: backend matrix + token/cost estimate, without calling any model."""

from __future__ import annotations

from .config import RunConfig, reviewer_seed, role_effort
from .models import effort_support, param_support
from .pack import estimate_tokens
from .providers.detect import BackendStatus, default_model_for

_PROMPT_OVERHEAD_CHARS = 3500  # persona + venue form + instructions


def _cost(
    model: str, kind: str, in_tok: int, out_tok: int, cfg: RunConfig
) -> tuple[float | None, str]:
    """(USD or None when unpriced, the line to show)."""
    if kind == "agent":
        return None, "uses your subscription — no per-token cost"
    if kind == "relay":
        return None, "answered by you / your agent — no model cost"
    if kind == "ollama":
        return None, "local model — free"
    if model.endswith(":free"):
        return None, "OpenRouter :free tier — $0 (rate-limited)"
    if not model:
        return None, "no price table entry for this backend's default model"
    price = cfg.pricing.get(model)
    if not price:
        return None, 'unknown price — add [pricing."' + model + '"] in prebuttal.toml'
    pin, pout = price
    cost = (in_tok * pin + out_tok * pout) / 1e6
    return cost, f"~${cost:.4f} (at ${pin:g}/${pout:g} per 1M tokens)"


def render_dry_run(
    cfg: RunConfig,
    resolved: list[tuple[str, str, str]],
    ac: tuple[str, str],
    pack_chars: int,
    statuses: list[BackendStatus],
) -> str:
    kind_by_backend = {s.backend: s.kind for s in statuses}
    pack_tok = estimate_tokens(pack_chars)
    in_tok = pack_tok + estimate_tokens(_PROMPT_OVERHEAD_CHARS)
    out_tok = cfg.est_completion_tokens

    lines: list[str] = []
    lines.append("=" * 62)
    lines.append("Prebuttal dry run — nothing will be called.")
    lines.append("=" * 62)
    lines.append("")
    lines.append("Review plan")
    persona_by_id = {r.id: r.persona for r in cfg.reviewers}

    def _effort(rid: str, backend: str, model: str) -> str:
        effort = role_effort(cfg, rid)
        if not effort:
            return ""
        if not effort_support(backend, model):
            return f"  effort: {effort} (not supported here — model default)"
        return f"  effort: {effort}"

    for rid, backend, model in resolved:
        model_s = model or "CLI default"
        persona = persona_by_id.get(rid, "")
        lines.append(
            f"  {rid:<4} {persona:<18} → {backend:<14} model: {model_s}"
            + _effort(rid, backend, model)
        )
    lines.append(
        f"  {'AC':<4} {'area_chair':<18} → {ac[0]:<14} model: {ac[1] or 'CLI default'}"
        + _effort("AC", ac[0], ac[1])
    )
    lines.append("")
    lines.append("Paper pack")
    lines.append(
        f"  {pack_chars:,} chars ≈ {pack_tok:,} tokens (budget {cfg.budget_chars:,} chars)"
    )
    lines.append(f"  per reviewer ≈ {in_tok:,} in + ~{out_tok:,} out tokens")
    if cfg.figures:
        lines.append(
            f"  figures: up to {cfg.max_figures} images per reviewer on vision-capable API "
            "backends (~1.5k tokens each, not in the estimate below)"
        )
    if cfg.compress:
        lines.append(
            "  compress: sections cut to fit the budget are first summarized by the AC's "
            "backend (one call each, not in the estimate below)"
        )
    lines.append("")
    lines.append("Cost estimate (indicative — see [pricing] overrides)")
    total = 0.0
    entries = [*resolved, ("AC", ac[0], ac[1])]
    for rid, backend, model in entries:
        kind = kind_by_backend.get(backend, "api")
        # model "" = the CLI default: price what will actually run
        cost, note = _cost(
            model or default_model_for(backend, statuses), kind, in_tok, out_tok, cfg
        )
        total += cost or 0.0
        lines.append(f"  {rid:<4} {backend:<14} {note}")
    if total > 0:
        lines.append(f"  total (priced backends): ~${total:.4f}")
    lines.append("")
    lines.append(
        "Seeds: "
        + ", ".join(
            f"{r.id}={reviewer_seed(cfg, r, i)}"
            for i, r in enumerate(cfg.reviewers)
            if any(rid == r.id for rid, _b, _m in resolved)
        )
        + f", AC={cfg.seed}"
    )
    ignored = sorted({b for (_r, b, m) in entries if not param_support(b, m)[1]})
    if ignored:
        lines.append(f"  (not applied by {', '.join(ignored)}: they use the model's defaults)")
    lines.append("")
    lines.append("Dry run only — no model was called.")
    return "\n".join(lines)
