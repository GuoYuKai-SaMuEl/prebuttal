#!/usr/bin/env python3
"""Phase B2 of the ZCode bridge: build the AC prompt from subagent answers."""

from __future__ import annotations

import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo))

from prebuttal.config import load_config
from prebuttal.ingestion import ingest
from prebuttal.models import Review
from prebuttal.orchestrator import (
    build_ac_system,
    build_ac_user,
    coerce_fields,
    extract_json_object,
)
from prebuttal.pack import render_pack
from prebuttal.venues import get_venue

BRIDGE = repo / "scripts" / "zcode_bridge"


def main() -> int:
    cfg = load_config(None)
    venue = get_venue("iclr")
    paper = ingest(str(repo / "examples" / "demo-paper"))
    pack = render_pack(paper, budget_chars=cfg.budget_chars)

    answers = BRIDGE / "answers"
    reviews = []
    for r in cfg.reviewers:
        key = r.persona.split("_")[0]  # senior_kind -> senior, detail_obsessive -> detail
        raw = (answers / f"{key}.txt").read_text(encoding="utf-8")
        payload = extract_json_object(raw)
        if payload is None:
            raise SystemExit(f"answer for {r.persona} is not parseable JSON:\n{raw[:300]}")
        fields = coerce_fields(payload, venue)
        reviews.append(
            Review(
                reviewer_id=r.id,
                persona=r.persona,
                backend="agent-zcode",
                model="zcode-subagent",
                temperature=r.temperature,
                seed=0,
                fields=fields,
                rating=fields.get(venue.rating_key),
                confidence=fields.get(venue.confidence_key),
                parse_ok=True,
            )
        )
        print(
            f"{r.id} {r.persona}:"
            f" rating={fields.get(venue.rating_key)} conf={fields.get(venue.confidence_key)}"
        )

    blob = build_ac_system(venue) + "\n\n---\n\n" + build_ac_user(pack, reviews, venue)
    (BRIDGE / "prompts" / "ac.txt").write_text(blob, encoding="utf-8")
    print(f"prompts/ac.txt: {len(blob):,} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
