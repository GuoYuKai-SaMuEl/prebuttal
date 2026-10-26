"""``prebuttal dashboard``: one local HTML page over every project and run.

A static file (no server, no network, no JavaScript dependencies) written next
to the archive, so its links to each run's ``report.html`` are relative and
work offline.  Like the archive itself it stays on this machine.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from . import __version__
from .report import report_from_dict
from .runs import ProjectSummary, RunRecord, runs_root
from .share import render_share_html
from .venues import venue_from_report

DEFAULT_REPO_URL = "https://github.com/GuoYuKai-SaMuEl/prebuttal"


def _e(s: object) -> str:
    return html.escape(str(s), quote=True)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def dashboard_path() -> Path:
    return runs_root() / "dashboard.html"


def ensure_html(rec: RunRecord, repo_url: str = DEFAULT_REPO_URL) -> Path:
    """The run's archived ``report.html``, rendered from report.json if missing.

    Runs archived before HTML became a default output have only md + json.
    """
    path = rec.dir_path / "report.html"
    if path.is_file():
        return path
    data = json.loads((rec.dir_path / "report.json").read_text(encoding="utf-8"))
    report = report_from_dict(data)
    path.write_text(
        render_share_html(report, venue_from_report(data), repo_url),
        encoding="utf-8",
    )
    return path


def _fraction(r: RunRecord) -> float | None:
    if r.mean is None or not r.scale:
        return None
    return max(0.0, min(1.0, r.mean / r.scale))


def _sparkline(runs: list[RunRecord]) -> str:
    """Score trend, oldest → newest, as a fraction of each venue's scale."""
    pts = [(r, f) for r in reversed(runs) if (f := _fraction(r)) is not None]
    if len(pts) < 2:
        return ""
    w, h, pad = 220, 48, 5
    # zoom to the scores' own range (at least 30% of the scale) so a one-point
    # revision gain is visible instead of a flat line
    fs = [f for _r, f in pts]
    mid, half = (max(fs) + min(fs)) / 2, max(0.15, (max(fs) - min(fs)) / 2 + 0.05)
    lo, hi = max(0.0, mid - half), min(1.0, mid + half)
    step = (w - 2 * pad) / (len(pts) - 1)
    coords = [
        (pad + i * step, h - pad - (f - lo) / (hi - lo) * (h - 2 * pad))
        for i, (_r, f) in enumerate(pts)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3"><title>{_e(r.label)}: '
        f"{r.mean:g}/{r.scale:g}</title></circle>"
        for (x, y), (r, _f) in zip(coords, pts, strict=True)
    )
    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'role="img" aria-label="score trend"><polyline points="{line}"/>{dots}</svg>'
    )


def _score(r: RunRecord) -> str:
    if r.mean is None:
        return "n/a"
    return f"{r.mean:g}<span class=max>/{r.scale:g}</span>" if r.scale else f"{r.mean:g}"


def _delta(p: ProjectSummary) -> str:
    if len(p.runs) < 2:
        return ""
    a, b = p.runs[1], p.runs[0]
    fa, fb = _fraction(a), _fraction(b)
    if fa is None or fb is None or a.mean is None or b.mean is None:
        return ""
    d = b.mean - a.mean if a.scale == b.scale else None
    if d is None:
        return '<span class="delta">venue changed</span>'
    cls = "up" if d > 0 else ("down" if d < 0 else "flat")
    return f'<span class="delta {cls}">{d:+g} vs #{a.run_no}</span>'


def _run_rows(p: ProjectSummary, base: Path) -> str:
    rows = []
    for r in p.runs:
        inside = r.dir_path.is_relative_to(base)
        rel = r.dir_path.relative_to(base).as_posix() if inside else ""
        links = (
            f'<a href="{_e(rel)}/report.html">HTML</a> · <a href="{_e(rel)}/report.md">MD</a>'
            if rel
            else ""
        )
        std = f"{r.std:g}" if r.std is not None else "-"
        rows.append(
            f"<tr><td>#{r.run_no}</td><td>{_e(r.when)}</td><td>{_e(r.venue)}</td>"
            f"<td class=num>{_score(r)}</td><td class=num>{std}</td>"
            f"<td class=note>{_e(r.note)}</td><td class=links>{links}</td></tr>"
        )
    return "".join(rows)


def render_dashboard(projects: list[ProjectSummary], *, base: Path | None = None) -> str:
    base = base or runs_root()
    n_runs = sum(len(p.runs) for p in projects)
    cards = []
    for p in projects:
        last = p.latest
        cards.append(f"""
  <section class="card">
    <div class="head">
      <div>
        <h2>{_e(p.title or p.key)}</h2>
        <div class="sub"><code>{_e(p.key)}</code> · {_plural(len(p.runs), "run")}
          · last {_e(last.when)}</div>
      </div>
      <div class="score">{_score(last)} {_delta(p)}</div>
    </div>
    {_sparkline(p.runs)}
    <table>
      <thead><tr><th>run</th><th>date</th><th>venue</th><th>score</th><th>σ</th>
        <th>note</th><th></th></tr></thead>
      <tbody>{_run_rows(p, base)}</tbody>
    </table>
  </section>""")  # noqa: RUF001
    body = "".join(cards) or (
        '<p class="empty">No runs yet. Review a paper with '
        "<code>prebuttal run paper.pdf</code> and it appears here.</p>"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Prebuttal dashboard</title>
<style>
  :root {{ --bg:#f7f7f8; --card:#fff; --ink:#1d1d1f; --mute:#6b6b76; --line:#e4e4e8;
    --accent:#3b6fd8; --up:#1f8a4c; --down:#c0392b; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#141416; --card:#1d1d21; --ink:#ececf0; --mute:#9a9aa6; --line:#2e2e35;
      --accent:#7aa2ff; --up:#4cc38a; --down:#ff7b6b; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  main {{ max-width:960px; margin:0 auto; padding:28px 16px 48px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .lead {{ color:var(--mute); margin:0 0 22px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:16px 18px; margin:0 0 16px; }}
  .head {{ display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }}
  h2 {{ font-size:17px; margin:0; }}
  .sub {{ color:var(--mute); font-size:13px; }}
  .score {{ font-size:26px; font-weight:650; white-space:nowrap; }}
  .max {{ font-size:14px; color:var(--mute); font-weight:400; }}
  .delta {{ font-size:13px; font-weight:500; margin-left:6px; color:var(--mute); }}
  .delta.up {{ color:var(--up); }} .delta.down {{ color:var(--down); }}
  .spark {{ display:block; margin:10px 0 4px; max-width:100%; }}
  .spark polyline {{ fill:none; stroke:var(--accent); stroke-width:2; }}
  .spark circle {{ fill:var(--accent); }}
  table {{ width:100%; border-collapse:collapse; font-size:13.5px; margin-top:8px; }}
  th, td {{ text-align:left; padding:6px 8px; border-top:1px solid var(--line); }}
  th {{ color:var(--mute); font-weight:500; border-top:none; }}
  td.num {{ font-variant-numeric:tabular-nums; }}
  td, th {{ white-space:nowrap; }} td.note {{ white-space:normal; min-width:12em; }}
  td.links {{ white-space:nowrap; }}
  a {{ color:var(--accent); }}
  code {{ font-size:12.5px; }}
  .empty {{ color:var(--mute); }}
  footer {{ color:var(--mute); font-size:12.5px; margin-top:24px; }}
  @media (max-width:640px) {{ table {{ display:block; overflow-x:auto; }} }}
</style>
</head>
<body>
<main>
  <h1>Prebuttal dashboard</h1>
  <p class="lead">{_plural(len(projects), "project")} ·
    {_plural(n_runs, "run")} · scores are simulated reviews, not predictions</p>
  {body}
  <footer>Generated by Prebuttal {_e(__version__)} from your local run archive — this page stays
    on your machine. Refresh with <code>prebuttal dashboard</code>.</footer>
</main>
</body>
</html>
"""
