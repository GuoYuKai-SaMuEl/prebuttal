"""Regenerate the GitHub Pages report pages under ``site/reports/``.

The landing page (``site/index.html``) is hand-written; this script only
re-renders the share pages for curated sample runs from their stored
``report.json`` and copies the synthetic sample report in, so the site
matches whatever the tool actually produced.

Usage::

    python scripts/build_site.py [runs_dir]

``runs_dir`` defaults to ``~/.prebuttal/runs`` (respect PREBUTTAL_HOME).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import MISSING
from dataclasses import fields as dc_fields
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from prebuttal.models import (
    Aggregate,
    MetaReview,
    Review,
    ReviewReport,
    RunInfo,
    StructuredPaper,
    Usage,
)
from prebuttal.share import render_share_html
from prebuttal.venues import get_venue

REPO_URL = "https://github.com/GuoYuKai-SaMuEl/prebuttal"

# (site filename, glob over run dir names) — first match with parseable
# reviews wins, so re-running after a better run upgrades the sample.
CURATED: list[tuple[str, str]] = [
    ("mamba.html", "*mamba*"),
    ("dpo.html", "*direct-preference*"),
]


def _dataclass_from(cls, data: dict):  # type: ignore[no-untyped-def]
    known = {f.name: f for f in dc_fields(cls)}
    kwargs = {k: v for k, v in data.items() if k in known and k != "usage"}
    if "usage" in known and isinstance(data.get("usage"), dict):
        kwargs["usage"] = Usage(**data["usage"])
    # stored summaries may omit fields (e.g. paper.abstract) — fill required
    # gaps with empty values; the share page only reads what matters.
    for name, f in known.items():
        if name in kwargs or f.default is not MISSING or f.default_factory is not MISSING:
            continue
        ann = str(f.type)
        kwargs[name] = [] if "list" in ann else ("" if "str" in ann else 0)
    return cls(**kwargs)


def report_from_json(d: dict) -> ReviewReport:  # type: ignore[type-arg]
    paper = _dataclass_from(StructuredPaper, d["paper"])
    reviews = [_dataclass_from(Review, r) for r in d["reviewers"]]
    meta = _dataclass_from(MetaReview, d["meta"])
    agg = _dataclass_from(Aggregate, d["aggregate"])
    run = _dataclass_from(RunInfo, d["run"])
    return ReviewReport(
        paper=paper,
        venue_key=venue_key(d),
        reviews=reviews,
        meta=meta,
        aggregate=agg,
        run=run,
    )


def find_report(runs_dir: Path, pattern: str) -> dict | None:  # type: ignore[type-arg]
    candidates = sorted(p for p in runs_dir.glob(pattern) if (p / "report.json").exists())
    for run_dir in reversed(candidates):  # newest first
        d = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        if any(r.get("parse_ok") for r in d.get("reviewers", [])):
            return d
    return None


def venue_key(d: dict) -> str:  # type: ignore[type-arg]
    v = d["venue"]
    return v["key"] if isinstance(v, dict) else v


def main() -> int:
    home = os.environ.get("PREBUTTAL_HOME") or os.path.expanduser("~/.prebuttal")
    runs_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(home) / "runs"
    out_dir = REPO / "site" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, pattern in CURATED:
        d = find_report(runs_dir, pattern)
        if d is None:
            print(f"[site] no usable run for {pattern} — skipping {name}")
            continue
        venue = get_venue(venue_key(d))
        html = render_share_html(report_from_json(d), venue, REPO_URL)
        (out_dir / name).write_text(html, encoding="utf-8")
        title = d["paper"]["title"][:60]
        print(f"[site] {name} <- {title!r} ({d['venue']})")

    sample = REPO / "examples" / "sample-report.html"
    if sample.exists():
        shutil.copy2(sample, out_dir / "sample.html")
        print("[site] sample.html <- examples/sample-report.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
