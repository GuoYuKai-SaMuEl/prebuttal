"""Share page: one self-contained static HTML file, no external assets."""

from __future__ import annotations

import html

from .models import ReviewReport
from .venues import Venue

_SUMMARY_CHARS = 520
_ITEM_CHARS = 220
_META_CHARS = 1800


def _e(s: str) -> str:
    return html.escape(s or "", quote=True)


def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def render_share_html(report: ReviewReport, venue: Venue, repo_url: str) -> str:
    r = report
    max_rating = venue.rating_field.max
    agg = r.aggregate
    title = _e(r.paper.title)
    venue_name = _e(venue.name)

    score_html = ""
    if agg.mean is not None:
        score_html = f"""
    <div class="score">
      <div class="score-num">{agg.mean:g}<span class="score-max">/{max_rating:g}</span></div>
      <div class="score-sub">estimated · σ {agg.std:g} · range {agg.min:g}–{agg.max:g} · n={agg.n}</div>
    </div>"""
    else:
        score_html = '<div class="score"><div class="score-num">n/a</div></div>'

    cards = []
    for rev in r.reviews:
        if rev.parse_ok and rev.rating is not None:
            chip = f'<span class="chip chip-score">{rev.rating:g}/{max_rating:g}</span>'
        else:
            chip = '<span class="chip chip-fail">no rating</span>'
        summary_key = next(
            (f.key for f in venue.fields if f.kind == "text" and f.key == "summary"), None
        )
        summary = _clip(str(rev.fields.get(summary_key, "")) if summary_key else "", _SUMMARY_CHARS)
        weak_key = "weaknesses" if "weaknesses" in rev.fields else ""
        weaknesses = list(rev.fields.get(weak_key) or [])[:3]
        weak_html = ""
        if weaknesses:
            lis = "".join(f"<li>{_e(_clip(w, _ITEM_CHARS))}</li>" for w in weaknesses)
            weak_html = f'<div class="weak"><div class="card-label">Top weaknesses</div><ul>{lis}</ul></div>'
        model = _e(rev.model or "CLI default")
        cards.append(
            f"""
    <div class="card">
      <div class="card-head">
        <span class="rid">{_e(rev.reviewer_id)}</span>
        <span class="persona">{_e(rev.persona)}</span>
        {chip}
      </div>
      <div class="backend">{_e(rev.backend)} · {model} · conf {_e(f"{rev.confidence:g}" if rev.confidence is not None else "n/a")}</div>
      <p>{_e(summary)}</p>
      {weak_html}
    </div>"""
        )

    meta_html = ""
    if r.meta.parse_ok and (r.meta.meta_review or r.meta.estimated_rating is not None):
        est = (
            f'<div class="est">AC estimate: {r.meta.estimated_rating:g}/{max_rating:g}</div>'
            if r.meta.estimated_rating is not None
            else ""
        )
        meta_html = f"""
  <section class="meta">
    <h2>Meta-review</h2>
    {est}
    <p>{_e(_clip(r.meta.meta_review, _META_CHARS))}</p>
  </section>"""

    backends = " · ".join(f"{_e(rev.reviewer_id)}: {_e(rev.backend)}" for rev in r.reviews)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prebuttal — {title}</title>
<style>
  :root {{ --ink:#1a1d23; --mut:#6b7280; --line:#e5e7eb; --accent:#4f46e5; --bg:#f8fafc; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:16px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         color:var(--ink); background:var(--bg); }}
  .wrap {{ max-width:880px; margin:0 auto; padding:32px 20px 56px; }}
  header {{ border-bottom:2px solid var(--ink); padding-bottom:16px; margin-bottom:20px; }}
  .brand {{ font-size:13px; letter-spacing:.18em; text-transform:uppercase; color:var(--accent); font-weight:700; }}
  h1 {{ font-size:26px; margin:6px 0 4px; line-height:1.25; }}
  .meta-line {{ color:var(--mut); font-size:14px; }}
  .hero {{ display:flex; gap:24px; align-items:center; background:#fff; border:1px solid var(--line);
          border-radius:12px; padding:20px 24px; margin:18px 0; }}
  .score-num {{ font-size:44px; font-weight:800; line-height:1; }}
  .score-max {{ font-size:20px; color:var(--mut); font-weight:600; }}
  .score-sub {{ color:var(--mut); font-size:13px; margin-top:6px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:14px; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:16px 18px; }}
  .card-head {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  .rid {{ font-weight:800; }}
  .persona {{ color:var(--mut); font-size:13px; font-family:ui-monospace,Consolas,monospace; }}
  .chip {{ margin-left:auto; font-weight:700; font-size:13px; border-radius:999px; padding:2px 10px; }}
  .chip-score {{ background:#eef2ff; color:var(--accent); }}
  .chip-fail {{ background:#fef2f2; color:#b91c1c; }}
  .backend {{ color:var(--mut); font-size:12px; margin:4px 0 10px; }}
  .card ul {{ margin:6px 0 0; padding-left:18px; }}
  .card-label {{ font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:var(--mut); }}
  .meta {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:18px 22px; margin-top:18px; }}
  .meta h2 {{ font-size:16px; margin:0 0 8px; }}
  .est {{ font-weight:700; margin-bottom:6px; }}
  footer {{ margin-top:28px; padding-top:16px; border-top:1px solid var(--line);
           color:var(--mut); font-size:13px; }}
  code {{ background:#eef2ff; border-radius:6px; padding:2px 8px; font-size:13px; }}
  a {{ color:var(--accent); }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">Prebuttal</div>
    <h1>{title}</h1>
    <div class="meta-line">{venue_name} · simulated review · {r.run.generated_at} · seed {r.run.seed}</div>
    <div class="meta-line">backends: {backends}</div>
  </header>
  <div class="hero">{score_html}
    <div class="hero-note">Three independent AI reviewers, isolated contexts, plus an
    area chair. This is a <b>pre-submission stress test</b>, not a prediction.</div>
  </div>
  <div class="grid">{"".join(cards)}
  </div>
  {meta_html}
  <footer>
    Generated with <b>Prebuttal</b> — <code>pip install prebuttal</code> ·
    <a href="{_e(repo_url)}">{_e(repo_url)}</a><br>
    Simulated reviews by LLMs as listed; scores are not predictions of real reviewer behavior.
  </footer>
</div>
</body>
</html>
"""
