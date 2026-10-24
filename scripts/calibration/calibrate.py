#!/usr/bin/env python3
"""Calibration: run Prebuttal on papers with known OpenReview ratings.

Fetches public submissions + official reviews from OpenReview, runs the full
Prebuttal pipeline on each paper's PDF, and compares predicted vs true mean
ratings.  Output: pairs.json + scatter.png + MAE/correlation on stdout.

Usage:
    python calibrate.py --venue-id ICLR.cc/2024/Conference --venue iclr \
        --n 20 --out-dir calib_out

Requires: pip install prebuttal[calibration]
Honesty: this measures *calibration of the tool*, not predictive power —
see scripts/calibration/README.md before quoting numbers.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo-local import

from prebuttal.config import RunConfig, load_config
from prebuttal.ingestion.pdf import ingest_pdf_bytes
from prebuttal.orchestrator import run_report
from prebuttal.providers import build_provider, resolve_backends, scan_backends
from prebuttal.venues import get_venue

_RATING_NUM = re.compile(r"^\s*(\d+(?:\.\d+)?)")


def parse_rating(value) -> float | None:
    """OpenReview ratings arrive as "6: Marginally above..." or numbers."""
    if value is None:
        return None
    s = str(value)
    m = _RATING_NUM.match(s)
    return float(m.group(1)) if m else None


def fetch_calibration_set(venue_id: str, n: int, min_reviews: int = 2):
    import openreview

    client = openreview.api.OpenReviewClient(baseurl="https://api2.openreview.net")
    notes = client.get_all_notes(
        invitation=f"{venue_id}/-/Submission",
        details={"replies": {"invitation": f"{venue_id}/-/Official_Review"}},
    )
    out = []
    for note in notes:
        replies = (note.details.get("replies") or []) if note.details else []
        ratings = []
        for rep in replies:
            c = rep.get("content", {})
            v = c.get("rating", {})
            if isinstance(v, dict):
                v = v.get("value")
            r = parse_rating(v)
            if r is not None:
                ratings.append(r)
        if len(ratings) >= min_reviews:
            out.append(
                {
                    "id": note.id,
                    "title": (note.content.get("title", {}) or {}).get("value", note.id),
                    "pdf": note.pdf,
                    "true_ratings": ratings,
                    "true_mean": round(statistics.mean(ratings), 2),
                }
            )
        if len(out) >= n:
            break
    return out


def fetch_pdf(client, venue_id: str, entry: dict) -> bytes:

    note = client.get_note(entry["id"])
    return client.get_attachment(note, "pdf")


def run_prebuttal(pdf_bytes: bytes, cfg: RunConfig):
    venue = get_venue(cfg.venue)
    paper = ingest_pdf_bytes(pdf_bytes, source_path="openreview")
    statuses = scan_backends(cfg)
    resolved, ac = resolve_backends(cfg, statuses)
    providers = {rid: build_provider(b, m, cfg) for rid, b, m in resolved}
    ac_provider = build_provider(ac[0], ac[1], cfg)
    return run_report(paper, cfg, venue, providers, ac_provider, log=lambda m: None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--venue-id", required=True, help="e.g. ICLR.cc/2024/Conference")
    ap.add_argument("--venue", required=True, help="prebuttal venue key: neurips|iclr|icml|acl")
    ap.add_argument("-n", "--n", type=int, default=20)
    ap.add_argument("--out-dir", default="calib_out")
    ap.add_argument("--config", default=None, help="prebuttal.toml (backends/models/seed)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(args.config)
    from prebuttal.config import apply_overrides

    cfg = apply_overrides(cfg, venue=args.venue)

    print(f"fetching {args.n} {args.venue_id} submissions with public reviews ...")
    entries = fetch_calibration_set(args.venue_id, args.n)
    print(f"got {len(entries)} papers")

    import openreview

    client = openreview.api.OpenReviewClient(baseurl="https://api2.openreview.net")

    pairs = []
    for i, entry in enumerate(entries, 1):
        try:
            pdf = fetch_pdf(client, args.venue_id, entry)
            report = run_prebuttal(pdf, cfg)
            pred = report.aggregate.mean
        except Exception as e:  # keep going — one bad paper must not sink the run
            print(f"[{i}/{len(entries)}] {entry['id']} failed: {e}")
            continue
        if pred is None:
            print(f"[{i}/{len(entries)}] {entry['id']} produced no ratings")
            continue
        pairs.append(
            {
                "id": entry["id"],
                "title": entry["title"],
                "true": entry["true_mean"],
                "predicted": pred,
                "n_true_reviews": len(entry["true_ratings"]),
            }
        )
        print(
            f"[{i}/{len(entries)}] true {entry['true_mean']:g} vs predicted {pred:g}"
            f" — {entry['title'][:60]}"
        )

    if not pairs:
        print("no usable pairs — aborting")
        return 1

    (out_dir / "pairs.json").write_text(json.dumps(pairs, indent=2), encoding="utf-8")

    trues = [p["true"] for p in pairs]
    preds = [p["predicted"] for p in pairs]
    mae = statistics.mean(abs(t - p) for t, p in zip(trues, preds, strict=False))
    try:
        corr = statistics.correlation(trues, preds)
    except statistics.StatisticsError:
        corr = float("nan")
    print(f"\nn={len(pairs)}  MAE={mae:.2f}  Pearson r={corr:.2f}")
    print(f"wrote {out_dir / 'pairs.json'} and {out_dir / 'scatter.png'}")

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(5.5, 5.5))
        ax.scatter(trues, preds, alpha=0.75, edgecolor="k", linewidth=0.4)
        lo = min(trues + preds) - 0.5
        hi = max(trues + preds) + 0.5
        ax.plot([lo, hi], [lo, hi], "--", color="gray", linewidth=1, label="perfect")
        ax.set_xlabel("true mean rating (OpenReview)")
        ax.set_ylabel("Prebuttal predicted rating")
        ax.set_title(f"{args.venue_id}  n={len(pairs)}  MAE={mae:.2f}  r={corr:.2f}")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out_dir / "scatter.png", dpi=160)
    except ImportError:
        print(
            "matplotlib not installed — skipping scatter.png (pip install prebuttal[calibration])"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
