# Prebuttal

> **Answer Reviewer 2 before Reviewer 2 exists.**

[![CI](https://github.com/GuoYuKai-SaMuEl/prebuttal/actions/workflows/ci.yml/badge.svg)](https://github.com/GuoYuKai-SaMuEl/prebuttal/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/pyproject.toml)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230.svg)](https://github.com/astral-sh/ruff)

[![View a sample report](https://img.shields.io/badge/%E2%96%B6_View_sample-report-2ea44f?style=for-the-badge)](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/examples/sample-report.md)
[![Share page](https://img.shields.io/badge/Share_page-5087d2?style=for-the-badge)](https://guoyukai-samuel.github.io/prebuttal/reports/sample.html)
[![Website](https://img.shields.io/badge/Website-5087d2?style=for-the-badge&logo=github&logoColor=white)](https://guoyukai-samuel.github.io/prebuttal/)

**Purpose-built for ML conferences: real NeurIPS / ICLR / ICML / ARR review-form
output, three reviewers running in fully independent contexts (optionally
cross-model), and a built-in pipeline to measure its scores against real
OpenReview ratings.**

Prebuttal is a pre-submission **stress test** for your paper: it sends your
submission through three isolated AI reviewers with different temperaments
plus an area chair, and hands you a conference-format review report — scores,
disagreement, weaknesses with citations to your own tables — *before* the real
Reviewers 1–3 see it. See a synthetic sample:
[report](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/examples/sample-report.md) ·
[share page](https://guoyukai-samuel.github.io/prebuttal/reports/sample.html) — or what a deliberately flawed
(fictional) paper gets: [1/10 report](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/examples/weak-paper-report.md).

---

## Why not just paste the paper into ChatGPT?

That is the main competitor. It loses, four ways:

| Paste into ChatGPT | Prebuttal |
|---|---|
| One conversation role-playing three reviewers → **persona collapse** into a single bland compromise opinion | Three reviewers in **fully independent contexts** (separate calls/processes), genuinely different verdicts + measured disagreement |
| Long papers get skimmed; tables are flattened into prose | **Ingestion pipeline**: cell-by-cell table extraction (LaTeX tabular parsing, PDF table detection, caption fallback) — reviewers can point at *Table 3, column 4* |
| Output is free-form chat text | **Real conference review forms**: NeurIPS 1–6, ICLR 1–10, ICML 1–10, ARR Soundness/Excitement/Overall — with official scale anchors |
| Scores are vibes | Seeds and temperatures applied where the backend supports them (API, Ollama) and marked n/a where it doesn't (agent CLIs), recorded backends/models per reviewer, and a **calibration script** to measure scores against real OpenReview ratings (published results pending) |

## Quickstart

```bash
pip install prebuttal

prebuttal run paper.pdf --venue iclr
prebuttal run https://arxiv.org/abs/2510.12345 --venue neurips
prebuttal run ./latex-src/ --venue acl
```

Prefer an isolated install for command-line tools? `pipx install prebuttal`
or `uv tool install prebuttal` work the same way (or `uvx prebuttal ...` to
run without installing). Requires Python 3.11+.

The first run costs **zero setup** if you already have a subscription CLI or
Ollama — Prebuttal auto-detects the cheapest path at startup and prints what it
chose (`prebuttal backends` to inspect):

| Backend | Auth | Notes |
|---|---|---|
| `agent-claude` (`claude -p`) | your Claude subscription, **zero API key** | preferred reviewer |
| `agent-codex` (`codex exec`) | your Codex subscription, **zero API key** | gives cross-model reviews together with claude; runs locked down, ignoring `~/.codex/config.toml` (see [SECURITY.md](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/SECURITY.md)) |
| `api-gemini` | GEMINI_API_KEY | **free tier** — the cheapest "first key" path |
| `api-openai` / `api-anthropic` | OPENAI_API_KEY / ANTHROPIC_API_KEY | BYO key |
| `api-openrouter` | OPENROUTER_API_KEY | one key, hundreds of models — **`:free` ids cost nothing** (default is one); prices shown live in `prebuttal models` |
| `ollama` | none | local & private — *unpublished papers never leave your machine* (with the default localhost host) |
| `relay` | none | file protocol: prompts spool to disk and **you, your agent's subagents, or any system** write the answers — zero key, explicit only (`--backend relay`; never picked by auto) |

**Unpublished manuscript?** The text is sent to the backend's provider, and
what happens to it there is that provider's privacy policy, not ours — see
[Privacy & data custody](#privacy--data-custody). For local-only review use
`ollama` or `relay`.

> ⚠️ **Free tiers are usually paid for with your data.** Free API tiers (the
> Gemini free tier, OpenRouter `:free` models and their upstream providers)
> may let the provider log, review or train on what you send. They are fine
> for published papers and trying the tool out — for an unpublished
> manuscript, check the provider's current terms, use a paid tier, or stay
> local.

Useful flags:

```bash
prebuttal run paper.pdf --venue neurips --dry-run   # cost + plan preview, calls nothing
prebuttal run paper.pdf --venue iclr --json out.json  # also write machine-readable JSON
prebuttal run paper.pdf --note "added ablation"     # label this revision
prebuttal run paper.pdf --seed 42                   # reproducible (API / Ollama backends)
prebuttal run paper.pdf -y                          # skip the plan confirmation
```

In auto mode on a terminal, Prebuttal shows the review plan before calling
anything — press Enter to run, `e` to re-pick each reviewer's persona, backend
and model via numbered menus, or `n` to abort. CI and pipes get the plan
printed and proceed automatically; fully-explicit configs never prompt.

`prebuttal models` lists every backend's actually-available models (live API
scan + installed Ollama models + claude aliases) with the current default
marked — pick one and set `model = "..."` per reviewer in prebuttal.toml.
Built-in defaults are mid-tier models current at release time and change
between versions — providers retire model ids quickly, so if a default stops
working, upgrade prebuttal or pin a model yourself.

## The reviewers

| id | Persona | Behavior |
|---|---|---|
| R1 | `senior_kind` | senior, constructive; core contribution + main concerns, grounded |
| R2 | `adversarial` | *Reviewer 2 in the flesh*: motivation, baselines, novelty, overclaiming |
| R3 | `detail_obsessive` | reads every table cell; statistics, ablations, reproducibility |
| AC | `area_chair` | meta-review, adjudicates disagreement, estimates the final rating |

Every persona enforces the same protocol: **cite the evidence** (section,
table, number) or the point doesn't count; use the full scale; JSON-only
output. There is also an easter-egg roast persona (`persona = "paper_roast"`)
for when you need the truth *fast*.

Personas live in [`prebuttal/personas/`](https://github.com/GuoYuKai-SaMuEl/prebuttal/tree/main/prebuttal/personas) and venue forms in
[`prebuttal/venues/forms/`](https://github.com/GuoYuKai-SaMuEl/prebuttal/tree/main/prebuttal/venues/forms) — plain text files, PRs
welcome (scale wording drifts every year; keep it current).

## Your own venue (custom review forms)

Built in: `neurips`, `iclr`, `icml`, `acl`. Anything else — CVPR, AAAI, a
journal, this year's revised ICML form, your lab's internal mock review — is
one TOML file plus the form text:

```bash
prebuttal venues new cvpr              # template in ~/.prebuttal/venues/
prebuttal venues new icml-2027 --from icml --here   # copy a built-in, project-local
prebuttal venues                       # list built-in + custom (invalid ones flagged)
prebuttal venues show cvpr             # the scores and form reviewers will see
prebuttal run paper.pdf --venue cvpr   # or --venue path/to/venue.toml
```

```toml
# cvpr.toml
name = "CVPR 2027"
form = "cvpr.md"          # the reviewer guidelines, shown to reviewers verbatim
rating = "rating"         # which score is the overall recommendation

[[fields]]
key = "weaknesses"
label = "Weaknesses"
kind = "list"             # text | list | score

[[fields]]
key = "rating"
label = "Overall recommendation"
kind = "score"
max = 6                   # scores run 1..max; half_steps = true allows 3.5
anchors = { "1" = "Reject", "3" = "Borderline", "6" = "Strong accept" }
```

Venues are looked up in `./.prebuttal/venues/` (commit it to share with
co-authors) and then `~/.prebuttal/venues/`; built-in names can't be
shadowed, so a copy needs its own name. Files are checked before any model is
called, and every error names the file and the setting. Reports keep the
venue's definition, so archived runs still render after the file changes.
Custom venues are not calibrated: the calibration script needs OpenReview
scores for a real venue. A venue's form text is instructions to your reviewers, so only
use venue files you trust (the form must sit next to its `.toml`).

## Configuration

`prebuttal init` writes a commented `prebuttal.toml`. Per-reviewer backends,
models and temperatures:

```toml
[default]
venue = "iclr"
seed = 42
# effort = "high"             # optional, see "Reasoning effort" below

[[reviewer]]
id = "R1"
persona = "senior_kind"
backend = "agent-claude"      # claude -p, subscription auth
temperature = 0.4

[[reviewer]]
id = "R2"
persona = "adversarial"
backend = "agent-codex"       # codex exec, subscription auth
model = "gpt-5.1"             # optional: forwarded as --model (agent CLIs too)
temperature = 0.7

[[reviewer]]
id = "R3"
persona = "detail_obsessive"
backend = "api-gemini"        # free tier; default model gemini-3.5-flash-lite
temperature = 0.5

[ac]
persona = "area_chair"
backend = "agent-claude"
```

### Reasoning effort

Leave it unset and every model thinks as much as its provider's default — the
right choice for most papers. To trade cost and time for depth, set
`--effort low|medium|high` for one run, `effort = "..."` under `[default]`,
or per `[[reviewer]]` / `[ac]`. It maps onto each backend's own control:

| Backend | Sent as |
|---|---|
| `agent-claude` | `claude --effort` |
| `agent-codex` | `-c model_reasoning_effort=...` |
| `api-anthropic` | `output_config.effort` |
| `api-openai` | `reasoning_effort` (gpt-5 and later / o-series reasoning models) |
| `api-gemini` | `thinkingLevel` (Gemini 3+) / `thinkingBudget` (2.x) |
| `api-openrouter` | `reasoning.effort` |
| `ollama` | `think` (gpt-oss models) |

Where a model has no such control (classic chat models, relay, custom agent
CLIs) the setting is skipped; `--dry-run` says so up front, and every report
lists the effort each review actually ran with.

## Calibration (honesty, not prophecy)

Scores are meaningless unless measured. The calibration pipeline runs Prebuttal
on papers that **already have real OpenReview reviews** and plots predicted vs
true mean ratings:

The script lives in the repository (it is not part of the pip package), so
run it from a clone:

```bash
git clone https://github.com/GuoYuKai-SaMuEl/prebuttal && cd prebuttal
pip install -e ".[calibration]"
python scripts/calibration/calibrate.py \
    --venue-id ICLR.cc/2024/Conference --venue iclr -n 20 --out-dir calib_out
```

Output: scatter plot + MAE + correlation. **No calibration results are
published yet** — until they are, treat every score as uncalibrated. Once
published, the claim they support is narrow
and deliberate: *this tool was measured* — unlike role-play prompts. It is
**not** a claim that it predicts your score; real reviewers disagree with each
other by more than this tool's error. Disagreement (σ) is reported with every
aggregate for exactly that reason.

## The revision plan

Reviews tell you what is wrong; the **revision plan** tells you what to do
about it. The area chair merges what the reviewers raised into a short,
prioritised list — no extra model call, it comes with the meta-review:

```
- [ ] **must** — Baseline set is thin: Table 1 misses a Perceiver comparison
      → Add Perceiver-AR to Table 1 or scope the claim to the baselines run (R2, R3 · effort: medium)
- [ ] **should** — No variance across seeds for the Table 2 ablation
      → Report mean and std over 3 seeds (R3 · effort: small)
```

It opens every report, the run prints the top items (`Fix first:`), and
`prebuttal plan [run]` prints it as a checklist to paste into your notes or an
issue (`--json` for scripts). After you revise and re-run, `prebuttal diff`
checks the old plan against the new reviews: which items are no longer
raised, which still are, and what is new.

## Projects, reports & revision history

Each paper gets a **project**, found from where it came from: the same PDF
path, LaTeX folder or arXiv id always lands in the same project, even when the
title changes between revisions (`--project NAME` to pick one yourself). Every
run gets a number within it — `mamba-linear-time-sequence#3` — and its own
report folder, so nothing is ever overwritten:

```
prebuttal-reports/                    (has a .gitignore: reviews stay out of git)
└── mamba-linear-time-sequence/
    ├── latest.md / latest.html       ← always the newest run
    ├── 2026-10-25_1530_iclr/report.md, report.html
    └── 2026-10-26_0910_iclr/report.md, report.html
```

The complete record (Markdown, HTML, JSON and the resolved config — backends,
models, seeds) is also archived under `~/.prebuttal/` (`--no-save` opts out),
so everything below works from any directory:

```bash
prebuttal projects                   # one line per paper: runs, latest score, trend
prebuttal runs [project]             # its runs, newest first, with notes
prebuttal open                       # newest report in the browser (HTML)
prebuttal plan                       # the newest run's revision plan as a checklist
prebuttal diff                       # newest run vs the one before: ratings, weaknesses, plan
prebuttal dashboard                  # local HTML overview: every project, score trends, links
prebuttal show / export / note / rm  # print, copy out, annotate, delete runs
prebuttal projects rename|rm         # tidy up
```

Runs are referenced as `latest` (the default), `mamba` (newest run of a
project), `mamba#3` (run 3), `mamba~1` (one before the newest) or by id
prefix.

The revision loop: fix what the reviewers flagged, re-run with the same
`--seed` and a `--note "what changed"`, then `prebuttal diff` shows which
weaknesses went away, persisted, or appeared, and which revision-plan items
are no longer raised. Report location and formats
are configurable: `--out-dir`, `--format md,html,json`, or an `[output]`
section in `prebuttal.toml` (`dir = ""` keeps reports in the archive only).
Need a file at a fixed path, e.g. for a script? `--json PATH`, or
`prebuttal export -f md -o PATH` after the run.

## Skill package

[`skills/prebuttal/SKILL.md`](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/skills/prebuttal/SKILL.md) teaches any agent to
drive the CLI and interpret the JSON — including relay mode (the reviewers are
the agent's own subagents) and the `runs`/`diff` revision loop. The skill file
is explicit about the one rule that matters: the agent must **run the CLI**,
never role-play the reviewers itself.

When the CLI detects it is running inside a coding agent (currently Claude
Code and Gemini CLI), `prebuttal run` and `prebuttal backends` print a one-line
hint pointing at relay mode. An agent environment that should always use its
own subagents can pin it once with `PREBUTTAL_BACKEND=relay`. Relay is never
chosen automatically: the CLI has to run in the background while the agent
answers the requests, or both sides wait on each other.

Install it into your agent's skills directory — for Claude Code:

```bash
mkdir -p ~/.claude/skills/prebuttal && curl -fsSL -o ~/.claude/skills/prebuttal/SKILL.md \
  https://raw.githubusercontent.com/GuoYuKai-SaMuEl/prebuttal/main/skills/prebuttal/SKILL.md
# or, from a clone: cp -r skills/prebuttal ~/.claude/skills/
```

Other agents (ZCode, Codex, …): copy or symlink `skills/prebuttal/` wherever
your agent discovers skills (see its docs), or reference the file from your
`AGENTS.md` / system prompt.

## Reference

### Environment variables

**API keys** — two ways, pick either:

```bash
prebuttal key set gemini     # quick setup: hidden prompt, stored for next time
# or the classic way: set GEMINI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY yourself
```

Stored keys live in `~/.prebuttal/keys.env` (user-only permissions, like
`~/.aws/credentials`); real environment variables always take precedence, so
CI setups are unaffected. `prebuttal key status` shows what's set (masked),
`prebuttal key unset <name>` removes one.

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) / `OPENROUTER_API_KEY` | enable the matching API backend |
| `OPENAI_BASE_URL` | point `api-openai` at an OpenAI-compatible proxy |
| `PREBUTTAL_OPENAI_MODEL` / `PREBUTTAL_ANTHROPIC_MODEL` / `PREBUTTAL_GEMINI_MODEL` / `PREBUTTAL_OPENROUTER_MODEL` | override each backend's default model |
| `PREBUTTAL_OLLAMA_HOST` (or `OLLAMA_HOST`) | Ollama base URL (default `http://localhost:11434`) |
| `PREBUTTAL_BACKEND` | force one backend for every reviewer + the AC (e.g. `relay`); `--backend` still wins, `prebuttal.toml` loses |
| `PREBUTTAL_HOME` | run-history and key storage location (default `~/.prebuttal`) |

API keys are only read from the environment or `keys.env` — never written to
reports, JSON, or share pages.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 2 | bad usage / config error / paper not found / unknown run id |
| 3 | no review backend available |
| 4 | partial failure (some reviewers or the AC failed; report still written) |
| 5 | every reviewer failed |
| 130 | interrupted (Ctrl+C) |

## Comparison

What Prebuttal provides, next to the common alternatives (by category —
check any specific tool's own docs for what it supports):

| Approach | Form | Venue forms | Calibration | Cross-model | Tables in-pipeline |
|---|---|---|---|---|---|
| **Prebuttal** | CLI + skill | NeurIPS / ICLR / ICML / ARR (editable plain text) | OpenReview script (scatter + MAE; results pending) | claude × codex × API × ollama | cell-by-cell |
| generic "review my paper" agent skills / prompts | agent skill | varies | rarely | single model | via the host model |
| multi-agent peer-review research frameworks | research code | study-specific | study-specific | sometimes | rarely |
| paste into a chatbot | chat | ✗ | ✗ | ✗ | ✗ |

## How it works

```
PDF / LaTeX dir / arXiv link
   └─ ingestion: sections, cell-accurate tables, figure captions, refs
        └─ reviewer pack (budget-aware; tables are never truncated)
             ├─ R1 senior_kind ──┐ three independent contexts,
             ├─ R2 adversarial ──┤ parallel fan-out, venue form + JSON schema
             ├─ R3 detail_obsessive ─┤
             └─ AC area chair ◄──┘ meta-review + estimated rating + disagreement
                  └─ Markdown + HTML report per run · JSON · project history
```

Orchestration lives in the CLI, not the host agent — the same pipeline runs
from a terminal, from inside any coding agent, or in CI.

## Roadmap & versioning

Versioning policy while pre-1.0: **patch** releases (0.1.1, 0.1.2, …) are
fixes and small additions; **minor** releases (0.2, 0.3, …) are substantial
new features; 1.0 only once the interface is battle-tested.

Tentative — priorities shift with usage and feedback. Short-term the focus
is **hardening the core on real papers**, not adding features:

1. **v0.2 (released)** — core: ingestion pipeline, real venue
   forms, 3 independent reviewers + AC, every backend (agent CLIs / APIs /
   Ollama / relay), reports + JSON + share page, calibration script; plus
   projects & revision history (per-paper report folders, run management,
   local dashboard) and per-role reasoning effort; v0.2.1 hardened PDF table
   extraction on real two-column papers
2. **v0.3 (current)** — custom venues (any review form and scale as a TOML
   file) and the revision plan (the AC's prioritised fix list, checked
   against the next run by `prebuttal diff`)
3. **Now (v0.3.x)** — polish from real-usage findings: calibration scatter
   plot + honest per-model calibration notes, provider-reliability UX
   (free-pool reality, retry transparency), relay UX
4. **Next (v0.4+)** — community personas, OpenReview submission
   integration, and a browser-only web quick-scan (GitHub Pages: drag-drop a
   PDF + your own OpenRouter/Gemini key — no server, we stay a
   non-custodian); then the rebuttal workbench (reviews → point-by-point
   response letter) and "CI for papers" (GitHub Action: \ref/\label checks,
   citation sanity)
5. **Eventually** — the calibration script becomes a public benchmark /
   leaderboard: tools depreciate, benchmarks appreciate.

## Develop

```bash
git clone https://github.com/GuoYuKai-SaMuEl/prebuttal && cd prebuttal
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Windows
.venv/bin/pip install -e ".[dev]"                               # macOS/Linux
pytest -q
```

Contributions welcome — the easiest ones are venue forms, personas, and
backends; see [CONTRIBUTING.md](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/CONTRIBUTING.md) for the three-step guide.
Also read [CHANGELOG.md](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/CHANGELOG.md), [SECURITY.md](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/SECURITY.md), and our
[Code of Conduct](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/CODE_OF_CONDUCT.md).

## Honesty & policy

- Prebuttal **labels every review** with the backend and model that produced it.
- It reports score **disagreement**, always. High σ is information.
- It is a stress test, **not** a predictor — the report footer says so, every time.
- Mind conference policies: with [NeurIPS 2026 running an official AI-assisted
  reviewing experiment](https://neurips.cc/Conferences/2026/ai-reviewing-experiment),
  the etiquette is clear — AI to *prepare* your own paper is yours to decide;
  AI to *review* others' papers must follow each venue's disclosure rules.

### Privacy & data custody

- **Your paper's text goes to whatever backend you configure.** With API or
  agent-CLI backends the manuscript is transmitted to that provider — and
  OpenRouter further routes each request to a third-party upstream provider.
  What happens to the text there (retention, training use, human review) is
  governed **solely by each provider's terms and privacy policy**, not by
  Prebuttal.
- **Prebuttal is an integration layer, not a data custodian.** This project
  operates no models and runs no servers; we never see your paper. For
  unpublished results, check the backend provider's data-use terms before
  sending — provider-side handling of your data is the provider's
  responsibility, not this project's.
- **Free tiers deserve extra care**: free API tiers (e.g. Gemini's free
  tier, OpenRouter `:free` models) may allow logging or training on inputs;
  paid tiers usually don't. Read the terms before sending unpublished work.
- **Local-only is a first-class path**: `ollama` never sends text off your
  machine (as long as `PREBUTTAL_OLLAMA_HOST` / `OLLAMA_HOST` point at
  localhost — a remote Ollama server receives the paper like any API), and
  `relay` leaves who answers entirely to you.
- **What Prebuttal itself stores stays on your disk**: run history (pack
  text, raw outputs, resolved config) under `~/.prebuttal/runs/` and keys in
  `~/.prebuttal/keys.env` (user-only). No telemetry. Note reports and share
  pages contain excerpts of your paper — sharing them publishes those
  excerpts.

## License & trademarks

Prebuttal is an independent project, not affiliated with or endorsed by
NeurIPS, ICLR, ICML, ACL/ARR or any model provider. Venue names are used only
to describe which review form a report follows; the forms are paraphrased
summaries of the public reviewer guidelines.

MIT
