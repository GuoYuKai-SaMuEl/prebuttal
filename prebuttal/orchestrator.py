"""Orchestration: fan out independent reviewers in parallel, then the AC.

The core architectural decision (plan §3.1): each reviewer is a *fully
independent* completion — separate process/call, separate context — because
role-playing three reviewers in one conversation collapses into one bland
compromise opinion ("persona collapse").
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from .config import RunConfig, reviewer_seed
from .models import (
    MetaReview,
    Review,
    ReviewReport,
    RunInfo,
    StructuredPaper,
    Usage,
    make_aggregate,
    sha256_text,
)
from .pack import render_pack
from .personas import load_persona
from .providers.base import BaseProvider, ProviderError
from .venues import Venue

Log = Callable[[str], None]

COMMON_RULES = """\
Reviewing protocol (non-negotiable):
1. Ground everything. Cite sections, tables, figures and exact numbers from the
   submission ("Table 3: 71.2 vs 68.9"). A point without evidence will be discarded.
2. Use the full rating scale. Do not cluster at the middle. Weak paper, low
   score; strong paper, high score.
3. Rate what is written, not what the authors might have meant: missing
   evidence counts as missing.
4. Do not invent facts. If something seems absent from the submission, phrase
   it as a question to the authors instead of asserting it.
5. Output format: return ONLY a single JSON object with the requested keys.
   No markdown fences, no commentary before or after the JSON."""

AC_SPEC = """\
Return ONLY a JSON object with exactly these keys:
  "meta_review": string      // your full meta-review, markdown allowed
  "estimated_rating": number // your predicted final rating on the conference scale
  "confidence": number       // your confidence, scale 1 to 5
  "recommendation": string   // one line: accept / borderline / reject leaning
  "disagreements": string    // where the reviewers disagreed and who you side with"""

# Keep raw outputs bounded in reports/JSON.
_RAW_CAP = 20_000


# ------------------------------------------------------------------ JSON utils


def extract_json_object(text: str) -> dict | None:
    """Best-effort JSON object extraction from an LLM completion."""
    if not text:
        return None

    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass

    for start, ch in enumerate(text):
        if ch != "{":
            continue
        depth = 0
        in_str = False
        esc = False
        for j in range(start, len(text)):
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : j + 1])
                        if isinstance(obj, dict):
                            return obj
                    except ValueError:
                        pass
                    break
    return None


def _to_number(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"-?\d+(?:\.\d+)?", v)
        if m:
            return float(m.group())
    return None


def coerce_fields(payload: dict, venue: Venue) -> dict:
    fields: dict = {}
    for f in venue.fields:
        v = payload.get(f.key)
        if f.kind == "text":
            fields[f.key] = str(v).strip() if isinstance(v, str) else ("" if v is None else str(v))
        elif f.kind == "list":
            if isinstance(v, list):
                fields[f.key] = [str(x).strip() for x in v if str(x).strip()]
            elif isinstance(v, str) and v.strip():
                fields[f.key] = [v.strip()]
            else:
                fields[f.key] = []
        else:  # score
            n = _to_number(v)
            if n is None or f.max is None:
                fields[f.key] = None
            else:
                if not f.allow_float:
                    n = float(round(n))
                n = min(max(n, f.min), float(f.max))
                fields[f.key] = n
    return fields


# ------------------------------------------------------------------ prompting


def build_reviewer_system(persona_text: str, venue: Venue) -> str:
    return (
        persona_text.strip()
        + "\n\n---\n\n"
        + venue.form_text().strip()
        + "\n\n---\n\n"
        + venue.json_spec()
        + "\n\n"
        + COMMON_RULES
    )


def build_reviewer_user(pack: str) -> str:
    return (
        "The full submission follows (structured: sections, complete cell-by-cell "
        "tables, figure captions).\n\n"
        + pack
        + "\n\n---\nEnd of submission. Return ONLY the JSON review object now."
    )


def build_ac_system(venue: Venue) -> str:
    persona = load_persona("area_chair")
    rating = venue.rating_field
    anchors = "\n".join(
        f"  {k} = {v}" for k, v in sorted(rating.anchors.items(), key=lambda kv: float(kv[0]))
    )
    scale = (
        f"scale {rating.min:g} to {rating.max:g}:\n{anchors}"
        if anchors
        else f"scale {rating.min:g} to {rating.max:g}."
    )
    return (
        persona.strip()
        + f"\n\n---\n\nThe conference rating scale is {scale}\n\n"
        + AC_SPEC
        + "\n\n"
        + COMMON_RULES.replace(
            "return ONLY a single JSON object with the requested keys.",
            "return ONLY a single JSON object.",
        )
    )


def _review_digest(review: Review, venue: Venue) -> dict[str, Any]:
    rating = review.rating
    anchor = venue.rating_field.anchor_for(rating) if rating is not None else ""
    digest: dict[str, Any] = {
        "reviewer": review.reviewer_id,
        "persona": review.persona,
        "rating": rating,
        "rating_label": anchor,
        "confidence": review.confidence,
    }
    for f in venue.fields:
        if f.kind != "score":
            v = review.fields.get(f.key)
            if isinstance(v, list):
                v = [s[:600] for s in v]
            elif isinstance(v, str):
                v = v[:1500]
            digest[f.key] = v
    if review.error:
        digest["error"] = review.error
    return digest


def build_ac_user(pack: str, reviews: list[Review], venue: Venue) -> str:
    digests = json.dumps([_review_digest(r, venue) for r in reviews], indent=2, ensure_ascii=False)
    return (
        "The submission (possibly elided) follows.\n\n"
        + pack
        + "\n\n---\n\nThe three reviews follow as JSON.\n\n"
        + digests
        + "\n\n---\nWrite the meta-review now. Return ONLY the JSON object."
    )


# ------------------------------------------------------------------ execution


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run_one_reviewer(
    rcfg,
    index: int,
    venue: Venue,
    pack: str,
    provider: BaseProvider,
    cfg: RunConfig,
    log: Log,
) -> Review:
    seed = reviewer_seed(cfg, rcfg, index)
    review = Review(
        reviewer_id=rcfg.id,
        persona=rcfg.persona,
        backend=provider.backend,
        model=provider.model,
        temperature=rcfg.temperature,
        seed=seed,
        started_at=_now(),
    )
    try:
        persona_text = load_persona(rcfg.persona)
    except KeyError as e:
        review.error = str(e)
        return review

    system = build_reviewer_system(persona_text, venue)
    user = build_reviewer_user(pack)
    t0 = time.monotonic()
    log(f"[{rcfg.id}] dispatching {rcfg.persona} via {provider.describe()}")
    try:
        comp = provider.complete(
            system=system,
            user=user,
            temperature=rcfg.temperature,
            seed=seed,
            max_tokens=cfg.max_tokens,
            retries=cfg.retries,
        )
    except ProviderError as e:
        review.duration_s = time.monotonic() - t0
        review.error = str(e)
        review.raw_output = ""
        log(f"[{rcfg.id}] FAILED: {e}")
        return review

    review.usage = comp.usage
    text = comp.text
    payload = extract_json_object(text)
    if payload is None:
        # one repair pass: models sometimes wrap JSON in prose/fences
        try:
            comp2 = provider.complete(
                system=system + "\nYour previous answer was not valid JSON.",
                user=text[:8000] + "\n\nReturn ONLY the corrected JSON object.",
                temperature=0.0,
                seed=seed,
                max_tokens=cfg.max_tokens,
                retries=0,
            )
            payload = extract_json_object(comp2.text)
            review.usage.add(comp2.usage)
        except ProviderError:
            payload = None

    review.duration_s = time.monotonic() - t0
    review.raw_output = text[:_RAW_CAP]

    if payload is None:
        review.parse_ok = False
        review.error = "could not parse a JSON review from the model output"
        log(f"[{rcfg.id}] completed but output was not valid JSON")
        return review

    review.fields = coerce_fields(payload, venue)
    review.rating = review.fields.get(venue.rating_key)
    review.confidence = review.fields.get(venue.confidence_key) if venue.confidence_key else None
    review.parse_ok = True
    rating_str = f" rating {review.rating:g}" if review.rating is not None else ""
    log(f"[{rcfg.id}] done in {review.duration_s:.0f}s{rating_str} ({review.usage.describe()})")
    return review


def run_reviews(
    cfg: RunConfig,
    venue: Venue,
    pack: str,
    providers: dict[str, BaseProvider],
    log: Log,
) -> list[Review]:
    reviews: list[Review] = [None] * len(cfg.reviewers)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=max(1, len(cfg.reviewers))) as pool:
        futures = {}
        for idx, rcfg in enumerate(cfg.reviewers):
            provider = providers[rcfg.id]
            futures[pool.submit(run_one_reviewer, rcfg, idx, venue, pack, provider, cfg, log)] = idx
        for fut in as_completed(futures):
            idx = futures[fut]
            reviews[idx] = fut.result()
    return reviews


def run_meta(
    cfg: RunConfig,
    venue: Venue,
    pack: str,
    reviews: list[Review],
    provider: BaseProvider,
    log: Log,
) -> MetaReview:
    meta = MetaReview(
        backend=provider.backend,
        model=provider.model,
        temperature=cfg.ac.temperature,
    )
    t0 = time.monotonic()
    log(f"[AC] synthesizing via {provider.describe()}")
    try:
        comp = provider.complete(
            system=build_ac_system(venue),
            user=build_ac_user(pack, reviews, venue),
            temperature=cfg.ac.temperature,
            seed=cfg.seed,
            max_tokens=min(cfg.max_tokens, 4000),
            retries=cfg.retries,
        )
    except ProviderError as e:
        meta.error = str(e)
        meta.duration_s = time.monotonic() - t0
        log(f"[AC] FAILED: {e}")
        return meta

    meta.usage = comp.usage
    payload = extract_json_object(comp.text)
    meta.duration_s = time.monotonic() - t0
    meta.raw_output = comp.text[:_RAW_CAP]
    if payload is None:
        meta.error = "could not parse meta-review JSON"
        log("[AC] output was not valid JSON")
        return meta

    meta.parse_ok = True
    meta.meta_review = str(payload.get("meta_review", "")).strip()
    meta.estimated_rating = _clamp_score(_to_number(payload.get("estimated_rating")), venue)
    meta.confidence = _clamp_score(_to_number(payload.get("confidence")), max_val=5.0)
    meta.recommendation = str(payload.get("recommendation", "")).strip()
    meta.disagreements = str(payload.get("disagreements", "")).strip()
    log(f"[AC] done in {meta.duration_s:.0f}s")
    return meta


def _clamp_score(v: float | None, venue: Venue | None = None, max_val: float = 5.0) -> float | None:
    if v is None:
        return None
    hi = venue.rating_field.max if venue else max_val
    if hi is None:
        hi = max_val
    return min(max(v, 1.0), float(hi))


def make_summarizer(provider: BaseProvider, log: Log) -> Callable[[str, str], str | None]:
    """LLM compression for oversized sections (cfg.compress = true)."""

    def summarize(heading: str, text: str) -> str | None:
        try:
            comp = provider.complete(
                system=(
                    "You compress sections of an academic paper for reviewers. "
                    "Keep every number, table reference, dataset name and claim. "
                    "Output a compact paragraph, at most 300 words."
                ),
                user=f"Section: {heading}\n\n{text}",
                temperature=0.0,
                max_tokens=800,
                retries=1,
            )
            return comp.text.strip() or None
        except ProviderError as e:
            log(f"[pack] summarizer failed for '{heading}': {e}")
            return None

    return summarize


# ------------------------------------------------------------------ entry point


def run_report(
    paper: StructuredPaper,
    cfg: RunConfig,
    venue: Venue,
    providers: dict[str, BaseProvider],
    ac_provider: BaseProvider,
    log: Log,
) -> ReviewReport:
    summarizer = make_summarizer(ac_provider, log) if cfg.compress else None
    pack = render_pack(paper, budget_chars=cfg.budget_chars, summarizer=summarizer)

    reviews = run_reviews(cfg, venue, pack, providers, log)
    meta = run_meta(cfg, venue, pack, reviews, ac_provider, log)
    aggregate = make_aggregate(reviews)

    usage_total = Usage()
    for r in reviews:
        usage_total.add(r.usage)
    usage_total.add(meta.usage)

    run_info = RunInfo(
        venue=venue.key,
        seed=cfg.seed,
        generated_at=RunInfo.now_iso(),
        source=paper.source_path,
        source_type=paper.source_type,
        pack_chars=len(pack),
        pack_sha256=sha256_text(pack),
        config_path=cfg.config_path,
    )
    return ReviewReport(
        paper=paper,
        venue_key=venue.key,
        reviews=reviews,
        meta=meta,
        aggregate=aggregate,
        run=run_info,
        usage_total=usage_total,
    )
