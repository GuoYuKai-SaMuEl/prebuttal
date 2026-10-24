#!/usr/bin/env python3
"""Phase A of the ZCode bridge: dump the exact prompts the CLI would send.

Uses the real package functions (same code path as AgentCLIProvider), so the
subagents that answer these files see byte-identical prompts.
"""

from __future__ import annotations

import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo))

from prebuttal.config import load_config
from prebuttal.ingestion import ingest
from prebuttal.orchestrator import build_reviewer_system, build_reviewer_user
from prebuttal.pack import render_pack
from prebuttal.personas import load_persona
from prebuttal.venues import get_venue


def main() -> int:
    cfg = load_config(None)
    venue = get_venue("iclr")
    paper = ingest(str(repo / "examples" / "demo-paper"))
    pack = render_pack(paper, budget_chars=cfg.budget_chars)

    out = repo / "scripts" / "zcode_bridge" / "prompts"
    out.mkdir(parents=True, exist_ok=True)
    (out / "pack.txt").write_text(pack, encoding="utf-8")
    for r in cfg.reviewers:
        system = build_reviewer_system(load_persona(r.persona), venue)
        user = build_reviewer_user(pack)
        blob = system + "\n\n---\n\n" + user
        (out / f"reviewer_{r.id}_{r.persona}.txt").write_text(blob, encoding="utf-8")
        print(f"reviewer_{r.id}_{r.persona}.txt: {len(blob):,} chars")
    print("pack.txt:", f"{len(pack):,} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
