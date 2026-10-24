#!/usr/bin/env python3
"""Generate a synthetic sample report from examples/demo-paper.

Uses deterministic in-process fake backends (no model is called, no cost) so
the README, screenshots and GIFs always have a stable artifact to point at.
The report is watermarked as synthetic via the backend names (fake-*).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prebuttal.config import load_config
from prebuttal.ingestion import ingest
from prebuttal.orchestrator import run_report
from prebuttal.pack import render_pack
from prebuttal.providers import register_backend
from prebuttal.report import dumps_json, render_markdown
from prebuttal.share import render_share_html
from prebuttal.venues import get_venue

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from conftest import PersonaFakeProvider


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    register_backend("fake", lambda model, cfg, t: PersonaFakeProvider(model=model or "fake-1"))

    cfg = load_config(None)
    cfg.venue = "iclr"
    for r in cfg.reviewers:
        r.backend = "fake"
    cfg.ac.backend = "fake"
    cfg.repo_url = "https://github.com/GuoYuKai-SaMuEl/prebuttal"

    venue = get_venue("iclr")
    paper = ingest(str(repo / "examples" / "demo-paper"))
    render_pack(paper, budget_chars=cfg.budget_chars)

    providers = {r.id: PersonaFakeProvider() for r in cfg.reviewers}
    ac = PersonaFakeProvider()
    report = run_report(paper, cfg, venue, providers, ac, log=print)

    out = repo / "examples"
    (out / "sample-report.md").write_text(render_markdown(report, venue), encoding="utf-8")
    (out / "sample-report.json").write_text(dumps_json(report, venue), encoding="utf-8")
    (out / "sample-report.html").write_text(
        render_share_html(report, venue, cfg.repo_url), encoding="utf-8"
    )
    print("wrote examples/sample-report.{md,json,html} (synthetic backends, no model called)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
