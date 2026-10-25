# Prebuttal

> **Answer Reviewer 2 before Reviewer 2 exists.**

[![CI](https://github.com/GuoYuKai-SaMuEl/prebuttal/actions/workflows/ci.yml/badge.svg)](https://github.com/GuoYuKai-SaMuEl/prebuttal/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230.svg)](https://github.com/astral-sh/ruff)

**Purpose-built for ML conferences: real NeurIPS / ICLR / ICML / ARR review-form
output, three reviewers running in fully independent contexts (optionally
cross-model), and scoring calibrated against real OpenReview distributions.**

Prebuttal is a pre-submission **stress test** for your paper: it sends your
submission through three isolated AI reviewers with different temperaments
plus an area chair, and hands you a conference-format review report — scores,
disagreement, weaknesses with citations to your own tables — *before* the real
Reviewers 1–3 see it. See a synthetic sample:
[report](examples/sample-report.md) ·
[share page](examples/sample-report.html).

---

## Why not just paste the paper into ChatGPT?

That is the main competitor. It loses, four ways:

| Paste into ChatGPT | Prebuttal |
|---|---|
| One conversation role-playing three reviewers → **persona collapse** into a single bland compromise opinion | Three reviewers in **fully independent contexts** (separate calls/processes), genuinely different verdicts + measured disagreement |
| Long papers get skimmed; tables are flattened into prose | **Ingestion pipeline**: cell-by-cell table extraction (LaTeX tabular parsing, PDF table detection, caption fallback) — reviewers can point at *Table 3, column 4* |
| Output is free-form chat text | **Real conference review forms**: NeurIPS 1–6, ICLR 1–10, ICML 1–10, ARR Soundness/Excitement/Overall — with official scale anchors |
| Scores are vibes | Fixed seeds, recorded backends/models per reviewer, score **calibration** against real OpenReview ratings |

## Quickstart

```bash
pipx install prebuttal          # or: uvx prebuttal ...

prebuttal run paper.pdf --venue iclr
prebuttal run https://arxiv.org/abs/2510.12345 --venue neurips
prebuttal run ./latex-src/ --venue acl
```

The first run costs **zero setup** if you already have a subscription CLI or
Ollama — Prebuttal auto-detects the cheapest path at startup and prints what it
chose (`prebuttal backends` to inspect):

| Backend | Auth | Notes |
|---|---|---|
| `agent-claude` (`claude -p`) | your Claude subscription, **zero API key** | preferred reviewer |
| `agent-codex` (`codex exec`) | your Codex subscription, **zero API key** | gives cross-model reviews together with claude |
| `api-gemini` | GEMINI_API_KEY | **free tier** — the cheapest "first key" path |
| `api-openai` / `api-anthropic` | OPENAI_API_KEY / ANTHROPIC_API_KEY | BYO key |
| `ollama` | none | local & private — *unpublished papers never leave your machine* |
| `relay` | none | file protocol: prompts spool to disk and **you, your agent's subagents, or any system** write the answers — zero key, explicit only (`--backend relay`; never picked by auto) |

Useful flags:

```bash
prebuttal run paper.pdf --venue neurips --dry-run   # cost + plan preview, calls nothing
prebuttal run paper.pdf --venue iclr --json out.json --share   # machine output + share page
prebuttal run paper.pdf --seed 42                   # reproducible
prebuttal run paper.pdf -y                          # skip the plan confirmation
```

In auto mode on a terminal, Prebuttal shows the review plan before calling
anything — press Enter to run, `e` to re-pick each reviewer's persona, backend
and model via numbered menus, or `n` to abort. CI and pipes get the plan
printed and proceed automatically; fully-explicit configs never prompt.

`prebuttal models` lists every backend's actually-available models (live API
scan + installed Ollama models + claude aliases) with the current default
marked — pick one and set `model = "..."` per reviewer in prebuttal.toml.

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

Personas live in [`prebuttal/personas/`](prebuttal/personas/) and venue forms in
[`prebuttal/venues/forms/`](prebuttal/venues/forms/) — plain text files, PRs
welcome (scale wording drifts every year; keep it current).

## Configuration

`prebuttal init` writes a commented `prebuttal.toml`. Per-reviewer backends,
models and temperatures:

```toml
[default]
venue = "iclr"
seed = 42

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
backend = "api-gemini"        # free tier; default model gemini-2.5-flash
temperature = 0.5

[ac]
persona = "area_chair"
backend = "agent-claude"
```

## Calibration (honesty, not prophecy)

Scores are meaningless unless measured. The calibration pipeline runs Prebuttal
on papers that **already have real OpenReview reviews** and plots predicted vs
true mean ratings:

```bash
pip install "prebuttal[calibration]"
python scripts/calibration/calibrate.py \
    --venue-id ICLR.cc/2024/Conference --venue iclr -n 20 --out-dir calib_out
```

Output: scatter plot + MAE + correlation. The claim this supports is narrow
and deliberate: *this tool was measured* — unlike role-play prompts. It is
**not** a claim that it predicts your score; real reviewers disagree with each
other by more than this tool's error. Disagreement (σ) is reported with every
aggregate for exactly that reason.

## Run history & revision diffing

Every run is archived automatically (best-effort, never blocks a review) under
`~/.prebuttal/` — reports, JSON, and the resolved config (backends, models,
seeds) for exact reproduction:

```bash
prebuttal runs                       # list archived runs
prebuttal show <run-id-prefix>       # re-read a report (--json for the data)
prebuttal diff <old> <new>           # ratings A→B + weakness movement
```

`diff` is the revision loop: fix what the reviewers flagged, re-run with the
same `--seed`, and see which weaknesses went away, persisted, or appeared.
Basic usage is unchanged — archiving is silent, `--no-save` opts out.

## Skill package

[`skills/prebuttal/SKILL.md`](skills/prebuttal/SKILL.md) teaches any agent to
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
mkdir -p ~/.claude/skills && cp -r skills/prebuttal ~/.claude/skills/
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
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | enable the matching API backend |
| `OPENAI_BASE_URL` | point `api-openai` at an OpenAI-compatible proxy |
| `PREBUTTAL_OPENAI_MODEL` / `PREBUTTAL_ANTHROPIC_MODEL` / `PREBUTTAL_GEMINI_MODEL` | override each backend's default model |
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

| Project | Form | Venue forms | Calibration | Cross-model | Tables in-pipeline |
|---|---|---|---|---|---|
| **Prebuttal** | CLI + skill | NeurIPS / ICLR / ICML / ARR (editable plain text) | OpenReview scatter + MAE | claude × codex × API × ollama | cell-by-cell |
| econ-paper-review-skill | agent skill | economics journals only | ✗ | ✗ | ✗ |
| academic-paper-reviewer (TypingMind) | agent skill | ✗ | ✗ | ✗ | ✗ |
| AgentReview / LLM-REVal | research framework | ✗ (not a tool) | ✗ | ✗ | ✗ |
| paste into ChatGPT | chat | ✗ | ✗ | ✗ | ✗ |

## How it works

```
PDF / LaTeX dir / arXiv link
   └─ ingestion: sections, cell-accurate tables, figure captions, refs
        └─ reviewer pack (budget-aware; tables are never truncated)
             ├─ R1 senior_kind ──┐ three independent contexts,
             ├─ R2 adversarial ──┤ parallel fan-out, venue form + JSON schema
             ├─ R3 detail_obsessive ─┤
             └─ AC area chair ◄──┘ meta-review + estimated rating + disagreement
                  └─ Markdown report · --json · --share page
```

Orchestration lives in the CLI, not the host agent — the same pipeline runs
from a terminal, from inside any coding agent, or in CI.

## Roadmap & versioning

Versioning policy while pre-1.0: **patch** releases (0.1.1, 0.1.2, …) are
fixes and small additions; **minor** releases (0.2, 0.3, …) are substantial
new features; 1.0 only once the interface is battle-tested.

1. **v0.1 (current, pre-release)** — core: ingestion pipeline, real venue
   forms, 3 independent reviewers + AC, every backend (agent CLIs / APIs /
   Ollama / relay), reports + JSON + share page, calibration script
2. **v0.1.x** — more venues, community personas, OpenReview submission
   integration, relay UX polish
3. **v0.2** — rebuttal workbench (reviews → point-by-point response letter);
   "CI for papers" (GitHub Action: \ref/\label checks, citation sanity)
4. **v0.3+** — the calibration script becomes a public benchmark /
   leaderboard: tools depreciate, benchmarks appreciate.

## Develop

```bash
git clone https://github.com/GuoYuKai-SaMuEl/prebuttal && cd prebuttal
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Windows
.venv/bin/pip install -e ".[dev]"                               # macOS/Linux
pytest -q
```

Contributions welcome — the easiest ones are venue forms, personas, and
backends; see [CONTRIBUTING.md](CONTRIBUTING.md) for the three-step guide.
Also read [CHANGELOG.md](CHANGELOG.md), [SECURITY.md](SECURITY.md), and our
[Code of Conduct](CODE_OF_CONDUCT.md).

## Honesty & policy

- Prebuttal **labels every review** with the backend and model that produced it.
- It reports score **disagreement**, always. High σ is information.
- It is a stress test, **not** a predictor — the report footer says so, every time.
- Mind conference policies: with [NeurIPS 2026 running an official AI-assisted
  reviewing experiment](https://neurips.cc/Conferences/2026/ai-reviewing-experiment),
  the etiquette is clear — AI to *prepare* your own paper is yours to decide;
  AI to *review* others' papers must follow each venue's disclosure rules.

## License

MIT
