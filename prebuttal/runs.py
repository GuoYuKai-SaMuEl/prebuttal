"""Run history: every review run is archived under ~/.prebuttal (best-effort).

This is an *advanced* feature with zero footprint on basic usage: `run` still
works exactly as before; archiving happens silently afterwards and a failure
to archive never fails the run.  Set ``PREBUTTAL_HOME`` to relocate the store
(also used by the test suite for isolation).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__


def runs_root() -> Path:
    base = os.environ.get("PREBUTTAL_HOME")
    return Path(base) if base else Path.home() / ".prebuttal"


def make_private_dir(path: Path) -> None:
    """Create ``path`` readable by the user only (0700 on POSIX).

    The store holds unpublished paper text, reviews and API keys; on shared
    machines (university clusters) the default 0755 would expose them to
    every other account.  Re-applied on each use so existing stores created
    by older versions get locked down too.  No-op where chmod can't apply.
    """
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o700)


def history_path() -> Path:
    return runs_root() / "history.jsonl"


def runs_dir() -> Path:
    return runs_root() / "runs"


def _slugify(text: str, limit: int = 32) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "paper").lower()).strip("-")
    return s[:limit].rstrip("-") or "paper"


def new_run_id(paper_title: str) -> str:
    # uuid tail keeps two runs of the same paper within one second distinct
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}-{_slugify(paper_title)}"


@dataclass
class RunRecord:
    id: str
    ts: str
    paper_title: str
    source: str
    venue: str
    seed: int
    mean: float | None
    std: float | None
    n: int
    dir: str

    @property
    def dir_path(self) -> Path:
        return Path(self.dir)


def save_run(
    report: Any,
    venue: Any,
    cfg: Any,
    *,
    md: str,
    json_str: str,
    html: str | None,
) -> RunRecord:
    """Archive one run. Raises OSError on failure; the caller treats it as non-fatal."""
    run_id = new_run_id(report.paper.title)
    make_private_dir(runs_root())
    out_dir = runs_dir() / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(md, encoding="utf-8")
    (out_dir / "report.json").write_text(json_str, encoding="utf-8")
    if html:
        (out_dir / "report.html").write_text(html, encoding="utf-8")
    resolved = {
        "prebuttal_version": __version__,
        "venue": venue.key,
        "seed": cfg.seed,
        "config_path": cfg.config_path,
        "pack_sha256": report.run.pack_sha256,
        "reviewers": [
            {
                "id": r.reviewer_id,
                "persona": r.persona,
                "backend": r.backend,
                "model": r.model,
                "temperature": r.temperature,
                "seed": r.seed,
                "rating": r.rating,
                "parse_ok": r.parse_ok,
            }
            for r in report.reviews
        ],
        "ac": {"backend": report.meta.backend, "model": report.meta.model},
    }
    (out_dir / "resolved-config.json").write_text(
        json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    rec = RunRecord(
        id=run_id,
        ts=report.run.generated_at,
        paper_title=report.paper.title,
        source=report.run.source,
        venue=venue.key,
        seed=cfg.seed,
        mean=report.aggregate.mean,
        std=report.aggregate.std,
        n=report.aggregate.n,
        dir=str(out_dir),
    )
    with history_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")
    return rec


def load_history() -> list[RunRecord]:
    p = history_path()
    if not p.is_file():
        return []
    out: list[RunRecord] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(RunRecord(**json.loads(line)))
        except (ValueError, TypeError):
            continue  # skip corrupt lines, never crash history reads
    out.sort(key=lambda r: r.id, reverse=True)
    return out


def find_run(query: str) -> tuple[RunRecord | None, list[RunRecord]]:
    """Resolve a run by exact id, unique id prefix, or unique title/id substring.

    Returns (match, candidates): candidates is non-empty when ambiguous.
    """
    hist = load_history()
    for r in hist:
        if r.id == query:
            return r, []
    pref = [r for r in hist if r.id.startswith(query)]
    if len(pref) == 1:
        return pref[0], []
    sub = [
        r for r in hist if query.lower() in r.id.lower() or query.lower() in r.paper_title.lower()
    ]
    if len(sub) == 1:
        return sub[0], []
    return None, (pref or sub)[:10]


# ------------------------------------------------------------------ rendering


def render_runs_table(records: list[RunRecord]) -> str:
    if not records:
        return (
            "No saved runs yet. Runs are archived automatically under "
            f"{runs_root()} — see `prebuttal run`."
        )
    header = f"{'run id':<40} {'venue':<8} {'mean':>6} {'sd':>5} {'n':>2}  title"
    lines = [header, "-" * min(len(header) + 48, 110)]
    for r in records:
        mean = f"{r.mean:g}" if r.mean is not None else "n/a"
        std = f"{r.std:g}" if r.std is not None else "-"
        lines.append(f"{r.id:<40} {r.venue:<8} {mean:>6} {std:>5} {r.n:>2}  {r.paper_title[:48]}")
    return "\n".join(lines)


def _weak_sim(a: str, b: str) -> float:
    wa = set(re.findall(r"[a-z0-9]+", a.lower()))
    wb = set(re.findall(r"[a-z0-9]+", b.lower()))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _num(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _load_run_json(rec: RunRecord) -> dict:
    p = Path(rec.dir) / "report.json"
    if not p.is_file():
        raise FileNotFoundError(f"archived report.json missing for {rec.id} ({p})")
    return json.loads(p.read_text(encoding="utf-8"))


def render_diff(a: RunRecord, b: RunRecord) -> str:
    """Human-readable A→B comparison: scores, per-reviewer ratings, weakness movement."""
    da, db = _load_run_json(a), _load_run_json(b)
    aa, ab = da.get("aggregate", {}), db.get("aggregate", {})
    ma, mb = _num(aa.get("mean")), _num(ab.get("mean"))
    scale = aa.get("rating_scale") or ab.get("rating_scale")

    out: list[str] = ["# Revision diff", ""]
    out.append(f"A · {a.id} · {a.ts} · seed {a.seed}")
    out.append(f"B · {b.id} · {b.ts} · seed {b.seed}")
    out.append("")

    def _score(m: float | None) -> str:
        return (
            f"{m:g}/{scale:g}" if (m is not None and scale) else ("n/a" if m is None else f"{m:g}")
        )

    out.append("## Predicted outcome")
    if ma is not None and mb is not None:
        out.append(f"- A {_score(ma)} → B {_score(mb)}  (Δ {mb - ma:+g})")
    else:
        out.append(f"- A {_score(ma)} → B {_score(mb)}")
    sa, sb = _num(aa.get("std")), _num(ab.get("std"))
    if sa is not None and sb is not None:
        out.append(f"- disagreement σ {sa:g} → {sb:g}")  # noqa: RUF001
    out.append("")

    ea, eb = da.get("meta", {}), db.get("meta", {})
    va, vb = _num(ea.get("estimated_rating")), _num(eb.get("estimated_rating"))
    if va is not None or vb is not None:
        line = f"- AC estimate A {_score(va)} → B {_score(vb)}"
        if va is not None and vb is not None:
            line += f"  (Δ {vb - va:+g})"
        out.append("## Area chair")
        out.append(line)
        out.append("")

    ra = {r.get("persona"): r for r in da.get("reviewers", [])}
    rb = {r.get("persona"): r for r in db.get("reviewers", [])}
    out.append("## Reviewer ratings (A → B)")
    for persona in sorted(set(ra) | set(rb)):
        x, y = ra.get(persona), rb.get(persona)
        fa = _num(x.get("rating")) if x else None
        fb = _num(y.get("rating")) if y else None
        line = f"- {persona}: "
        line += f"{fa:g}" if fa is not None else "n/a"
        line += " → "
        line += f"{fb:g}" if fb is not None else "n/a"
        if fa is not None and fb is not None:
            line += f"  (Δ {fb - fa:+g})"
        out.append(line)
    out.append("")

    out.append("## Weakness movement (heuristic: ≥35% word overlap counts as the same weakness)")
    moved_any = False
    for persona in sorted(set(ra) & set(rb)):
        old = list((ra[persona].get("fields") or {}).get("weaknesses") or [])
        new = list((rb[persona].get("fields") or {}).get("weaknesses") or [])
        if not old and not new:
            continue
        remaining: list[str] = []
        gone: list[str] = []
        matched_new: set[int] = set()
        for ow in old:
            best_i, best_s = -1, 0.0
            for i, nw in enumerate(new):
                s = _weak_sim(ow, nw)
                if s > best_s:
                    best_s, best_i = s, i
            if best_s >= 0.35:
                remaining.append(ow)
                matched_new.add(best_i)
            else:
                gone.append(ow)
        fresh = [nw for i, nw in enumerate(new) if i not in matched_new]
        if not (gone or fresh or remaining):
            continue
        moved_any = True
        out.append(f"### {persona}")
        for w in gone:
            out.append(f"- gone: {w[:220]}")
        for w in remaining:
            out.append(f"- persists: {w[:220]}")
        for w in fresh:
            out.append(f"- new: {w[:220]}")
        out.append("")
    if not moved_any:
        out.append("(no weaknesses reported in either run)")
        out.append("")

    out.append(
        "*Heuristic comparison of two simulated runs — same persona ≠ same reviewer; "
        "treat movements as signals, not measurements.*"
    )
    return "\n".join(out)
