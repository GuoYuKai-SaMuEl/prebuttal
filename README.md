<div align="center">

# Prebuttal

**Answer Reviewer 2 before Reviewer 2 exists.**

A pre-submission stress test for ML papers: three independent AI reviewers
and an area chair, on the real NeurIPS / ICLR / ICML / ARR review forms.

[![PyPI](https://img.shields.io/pypi/v/prebuttal.svg)](https://pypi.org/project/prebuttal/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/pyproject.toml)
[![CI](https://github.com/GuoYuKai-SaMuEl/prebuttal/actions/workflows/ci.yml/badge.svg)](https://github.com/GuoYuKai-SaMuEl/prebuttal/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/LICENSE)

[**Website**](https://guoyukai-samuel.github.io/prebuttal/) ·
[**Sample report**](https://guoyukai-samuel.github.io/prebuttal/reports/sample.html) ·
[**Real-paper demos**](#see-it-on-real-papers) ·
[Changelog](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/CHANGELOG.md) ·
[Roadmap](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/ROADMAP.md)

</div>

```console
$ pip install prebuttal
$ prebuttal run examples/weak-paper --venue neurips
[prebuttal] parsed: “GlobalGate: A Universal Attention Mechanism That Solves Long-Context Reasoning” — 7 sections, 1 tables, 0 figure captions
[prebuttal] Pre-flight check (error): no "NeurIPS Paper Checklist" section — the venue requires one
[R2] dispatching adversarial via agent-codex (codex, subscription auth) / gpt-6-luna
[R1] dispatching senior_kind via agent-claude (claude, subscription auth) / sonnet
[R3] dispatching detail_obsessive via api-gemini / gemini-3.5-flash-lite
[R3] done in 9s rating 1 (1,776 in / 570 out)
[R2] done in 11s rating 2 (usage n/a (backend reports no tokens))
[R1] done in 25s rating 1 (usage n/a (backend reports no tokens))
[AC] synthesizing via agent-claude (claude, subscription auth) / sonnet
[AC] done in 27s

Predicted: 1.33/6 (σ 0.47, range 1–2)
Fix first: [must] Section 3.1 / Table 1: baseline Transformer trained for 1 epoch vs GlobalGate for 5 epoch…
           [must] Section 3.1: the same 200 LongQA-Mini questions are used for hyperparameter selection and…
           [must] Section 3.2: no comparison with any existing long-context or gated-attention method ('kno…
Report:   prebuttal-reports/globalgate-a-universal/2026-10-27_2228_neurips/report.html
```

<sub>Real output (report path shortened) on <a href="https://github.com/GuoYuKai-SaMuEl/prebuttal/tree/main/examples/weak-paper">a fictional paper with planted flaws</a>: claude, codex and Gemini as the three reviewers.</sub>

## Highlights

- **Three reviewers, zero shared context.** Each runs as its own call or
  process — optionally on different models (Claude × Codex × Gemini × …) — so
  verdicts genuinely differ, and the disagreement is always reported.
- **Real review forms.** NeurIPS 1–6, ICLR 1–10, ICML 1–10, ARR
  Soundness/Excitement/Overall with the official anchors; any other venue is
  one TOML file.
- **Your tables, cell by cell.** LaTeX and PDF ingestion keeps every number,
  so reviewers cite "Table 3, column 4" — not a guess.
- **A revision plan, not just a verdict.** The area chair turns the reviews
  into a prioritised must / should / could checklist; `prebuttal diff` checks
  it against the next round.
- **A desk-reject pre-flight.** `prebuttal check` catches anonymity leaks,
  page-limit overruns, missing required sections and leftover `??` — no
  model, no cost.
- **Zero setup if you have a subscription.** Uses `claude` / `codex` CLIs you
  are already logged into, a free Gemini key, OpenRouter, or a local Ollama —
  and stays honest about which model wrote what.

## Quickstart

```bash
pip install prebuttal          # or: pipx install prebuttal · uv tool install prebuttal

prebuttal check paper.pdf --venue iclr      # desk-reject pre-flight, seconds, free
prebuttal run paper.pdf --venue iclr        # the full simulated review
prebuttal run https://arxiv.org/abs/2510.12345 --venue neurips
prebuttal run ./latex-src/ --venue acl      # a LaTeX project, no compiling needed
```

Python 3.11+. `prebuttal backends` shows what you can review with; if nothing
is ready, it tells you the quickest way to get one (often `prebuttal key set
gemini` for a free key). Each run prints its report paths and the next useful
commands.

## See it on real papers

| Paper | Venue | Prebuttal | Real outcome |
|---|---|---|---|
| [Direct Preference Optimization](https://guoyukai-samuel.github.io/prebuttal/reports/dpo.html) | NeurIPS 2023 | 4.33/6 · AC 5 | accepted (oral) |
| [Mamba v1 → v2, a revision round](https://guoyukai-samuel.github.io/prebuttal/reports/mamba-revision.html) | ICLR 2024 | 7.33 → 7.33/10 — "no change", and it says so | rejected → accepted at COLM |
| [GlobalGate (fictional, planted flaws)](https://guoyukai-samuel.github.io/prebuttal/reports/weak.html) | ICLR | 1.33/10 | — |

Unofficial demos on public arXiv versions; frontier models have likely seen
these papers in training, so read them as a demonstration of the workflow,
not as evidence of accuracy.

## Why not just paste the paper into ChatGPT?

| Paste into a chatbot | Prebuttal |
|---|---|
| One conversation role-plays three reviewers → **persona collapse** into one bland opinion | Three reviewers in **separate contexts**, genuinely different verdicts, measured disagreement |
| Long papers get skimmed; tables become prose | **Ingestion pipeline**: cell-by-cell tables (LaTeX `tabular`, PDF table detection, caption fallback) |
| Free-form chat text | The **venue's own review form** and scale |
| Scores are vibes | Every review labelled with backend and model, seeds applied where the backend supports them, and a calibration script against real OpenReview ratings (results not published yet) |

---

**Contents** ·
[Backends & privacy](#backends--privacy) ·
[`prebuttal check`](#before-you-submit-prebuttal-check) ·
[The reviewers](#the-reviewers) ·
[Revision plan & history](#the-revision-loop) ·
[Custom venues](#your-own-venue) ·
[Configuration](#configuration) ·
[Calibration](#calibration-honesty-not-prophecy) ·
[Agent skill](#use-it-from-a-coding-agent) ·
[Reference](#reference) ·
[How it works](#how-it-works) ·
[Contributing](#contributing) ·
[Honesty & privacy](#honesty--policy)

## Backends & privacy

Prebuttal picks the cheapest ready path at startup and prints the plan before
calling anything (`--dry-run` previews plan and cost; `-y` skips the prompt):

| Backend | Auth | Notes |
|---|---|---|
| `agent-claude` (`claude -p`) | your Claude subscription, **no API key** | preferred reviewer; runs with no tools at all |
| `agent-codex` (`codex exec`) | your Codex subscription, **no API key** | cross-model reviews together with claude; runs with no shell or file access ([SECURITY.md](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/SECURITY.md)) |
| `api-gemini` | `GEMINI_API_KEY` | **free tier** — the cheapest first key |
| `api-openai` / `api-anthropic` | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | bring your own key |
| `api-openrouter` | `OPENROUTER_API_KEY` | hundreds of models; **`:free` ids cost nothing** (the default is one) |
| `ollama` | none | local — *unpublished papers never leave your machine* |
| `relay` | none | prompts spool to files and **you, your agent's subagents or any system** answer — explicit only (`--backend relay`) |

`prebuttal backends` is the one setup view: what is ready, where its access
comes from (CLI login, env var or stored key — masked) and its default model.
`prebuttal backends <name>` lists that backend's available models. Defaults
are mid-tier models current at release time; providers retire ids quickly,
so if one stops working, upgrade prebuttal or pin a model.

**Unpublished manuscript?** Its text goes to the backend's provider, and what
happens there is that provider's policy, not ours. **Free tiers are usually
paid for with your data** (logging, training): fine for published papers and
trying the tool, but for unpublished work check the terms, use a paid tier, or
stay local with `ollama` or `relay`. More in [Privacy & data custody](#privacy--data-custody).

## Before you submit: `prebuttal check`

```bash
prebuttal check paper.pdf --venue iclr      # the PDF you will upload
prebuttal check ./latex-src/ --venue iclr   # the LaTeX project, without compiling
```

A deterministic pre-flight against what gets papers desk-rejected — no model,
no cost, a few seconds:

- **Anonymity** — author names in the PDF metadata, e-mail addresses on
  page 1, a camera-ready or NeurIPS `[preprint]` build, a visible
  acknowledgements section, links to your own repository, "our previous
  work [12]".
- **Format** — main-text pages over the venue's limit (two-column layouts
  included), a missing NeurIPS checklist / ICML impact statement / ARR
  limitations section.
- **Leftovers** — `??` references, `[?]` citations, TODOs, and text hidden
  from human readers.

A LaTeX project is checked without compiling: every `\ref` needs a `\label`
and every `\cite` a bibliography entry; the page limit needs the PDF. Exit
code 6 means something can get the paper desk-rejected, so it drops straight
into CI. The venue comes from `--venue`, else `prebuttal.toml`, else
`neurips`. Limits change yearly: the output names the call each rule came
from, so confirm against this year's CFP.

`prebuttal run` performs the same check on your own draft (a local PDF or
LaTeX project — not on arXiv papers, which are public and camera-ready) and
lists what it found in the report's notes.

## The reviewers

| id | Persona | Behavior |
|---|---|---|
| R1 | `senior_kind` | senior, constructive; core contribution and main concerns |
| R2 | `adversarial` | *Reviewer 2 in the flesh*: motivation, baselines, novelty, overclaiming |
| R3 | `detail_obsessive` | reads every table cell; statistics, ablations, reproducibility |
| AC | `area_chair` | meta-review, adjudicates disagreement, estimates the final rating, writes the revision plan |

Every persona follows the same protocol: **cite the evidence** (section,
table, number) or the point doesn't count; use the full scale; report text
that tries to instruct reviewers as a weakness instead of obeying it. For the
truth *fast*, there is an easter-egg roast persona (`persona = "paper_roast"`).
Personas and venue forms are plain text in
[`prebuttal/personas/`](https://github.com/GuoYuKai-SaMuEl/prebuttal/tree/main/prebuttal/personas) and
[`prebuttal/venues/forms/`](https://github.com/GuoYuKai-SaMuEl/prebuttal/tree/main/prebuttal/venues/forms) — PRs welcome.

## The revision loop

Every report opens with the **revision plan**: what the area chair would fix
first, merged from all reviews — no extra model call.

```
- [ ] **must** — Baseline set is thin: Table 1 misses a Perceiver comparison
      → Add Perceiver-AR to Table 1 or scope the claim to the baselines run (R2, R3 · effort: medium)
- [ ] **should** — No variance across seeds for the Table 2 ablation
      → Report mean and std over 3 seeds (R3 · effort: small)
```

Revise, re-run with the same `--seed` and a `--note "what changed"`, then:

```bash
prebuttal diff          # newest run vs the one before: ratings, weaknesses, plan items
prebuttal diff --llm    # match plan items by meaning (one model call) instead of wording
```

`diff` reports which plan items are no longer raised, which still are, and
what is new. Plain `diff` matches by wording, so a reworded issue can show up
as "not re-detected" *and* "new" — read both lists before ticking anything
off, or use `--llm`. Single runs are noisy: a score that moves by a point may
be the model, not your revision.

### Projects, reports & history

Each paper gets a **project**, found from its source: the same PDF path,
LaTeX folder or arXiv id always lands in the same project, even when the title
changes (`--project NAME` picks one; a local folder named like an arXiv id is
read locally, never swapped for the public version). Every run gets a number
— `mamba#3` — and its own report folder, so nothing is overwritten:

```
prebuttal-reports/                    (has a .gitignore: reviews stay out of git)
└── mamba-linear-time-sequence/
    ├── latest.md / latest.html       ← always the newest run
    ├── 2026-10-25_1530_iclr/report.md, report.html
    └── 2026-10-26_0910_iclr/report.md, report.html
```

The full record (Markdown, HTML, JSON, the exact reviewer text and the
resolved config) is archived under `~/.prebuttal/` (`--no-save` opts out), so
these work from any directory:

```bash
prebuttal projects                   # one line per paper: runs, latest score, trend
prebuttal projects --open            # the same as an HTML overview, with score trends
prebuttal runs [project]             # a paper's runs, newest first, with notes
prebuttal show                       # print the newest report
prebuttal show mamba#3 --open        # ... open it in the browser instead
prebuttal show -o review.html        # ... or save a copy (.md, .html or .json)
prebuttal plan                       # the newest revision plan as a checklist (--json too)
prebuttal retry                      # a reviewer failed? re-run only it (+ the AC), same text
prebuttal note / rm                  # annotate or delete runs (a whole paper: projects rm)
prebuttal projects rename|rm         # tidy up
```

Runs are referenced as `latest` (the default), `mamba` (newest run of a
project), `mamba#3`, `mamba~1` (one before the newest) or an id prefix; `rm`
wants a specific run, so a project name alone is refused there. Reports go
where you want them: `--out-dir`, an `[output]` section in `prebuttal.toml`
(`formats = ["md", "html", "json"]`), `--json PATH` for a fixed file, or
`prebuttal show -o PATH` afterwards.

## Your own venue

Built in: `neurips`, `iclr`, `icml`, `acl`. Anything else — CVPR, AAAI, a
journal, this year's revised form, your lab's mock review — is one TOML file
plus the form text:

```bash
prebuttal venues new cvpr                          # template in ~/.prebuttal/venues/
prebuttal venues new icml-2027 --from icml --here  # copy a built-in, project-local
prebuttal venues show cvpr                         # what reviewers will see
prebuttal run paper.pdf --venue cvpr               # or --venue path/to/venue.toml
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

[checks]                  # optional: what `prebuttal check` holds it to
double_blind = true
page_limit = 8
required_sections = ["Limitations"]   # these don't count toward the limit
```

Venues are looked up in `./.prebuttal/venues/` (commit it for co-authors),
then `~/.prebuttal/venues/`; built-in names can't be shadowed. Files are
validated before any model is called, and every error names the file and the
setting. Reports keep the venue's definition, so archived runs still render
after the file changes. A form is instructions to your reviewers, so only use
venue files you trust.

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
model = "sonnet"

[[reviewer]]
id = "R2"
persona = "adversarial"
backend = "agent-codex"       # codex exec, subscription auth
model = "gpt-6-luna"

[[reviewer]]
id = "R3"
persona = "detail_obsessive"
backend = "api-gemini"        # free tier

[ac]
backend = "agent-claude"
model = "opus"
```

For a single run, `--backend X` puts every role on one backend (each with
that backend's default model — a model the file set for another backend is
dropped) and `--model Y` sets the model; `--reviewers N` keeps the configured
reviewers and adds or drops the rest. A `prebuttal.toml` found in the current
directory (say, inside a co-author's repo) can't run commands, pick a
provider or write outside the folder without asking you first.

### Reasoning effort

Leave it unset and every model thinks as much as its provider's default — the
right choice for most papers. To trade cost and time for depth, use
`--effort low|medium|high` for one run, `effort = "..."` under `[default]`,
or per `[[reviewer]]` / `[ac]`:

| Backend | Sent as |
|---|---|
| `agent-claude` | `claude --effort` |
| `agent-codex` | `-c model_reasoning_effort=...` |
| `api-anthropic` | `output_config.effort` |
| `api-openai` | `reasoning_effort` (gpt-5 and later / o-series) |
| `api-gemini` | `thinkingLevel` (Gemini 3+) / `thinkingBudget` (2.x) |
| `api-openrouter` | `reasoning.effort` |
| `ollama` | `think` (gpt-oss models) |

Where a model has no such control the setting is skipped; `--dry-run` says so
up front, and every report lists the effort each review actually ran with.

### Figures as images

Reviewers see figure *captions* by default. With `--figures` (or
`figures = true` under `[default]`), reviewers on the vision-capable API
backends also get the figures as images: for a PDF or arXiv paper, each page
holding a figure caption; for a LaTeX project, the first `\includegraphics`
of each figure (files inside the project only). At most `max_figures`
(default 6), ~1.5k tokens each. A text-only model is retried without images;
agent CLIs, Ollama and relay keep captions only.

## Calibration (honesty, not prophecy)

Scores mean nothing unless measured. The calibration script runs Prebuttal on
papers that **already have real OpenReview reviews** and plots predicted vs
true mean ratings. It lives in the repository, not the pip package:

```bash
git clone https://github.com/GuoYuKai-SaMuEl/prebuttal && cd prebuttal
pip install -e ".[calibration]"
python scripts/calibration/calibrate.py \
    --venue-id ICLR.cc/2024/Conference --venue iclr -n 20 --out-dir calib_out
```

**No calibration results are published yet** — until they are, treat every
score as uncalibrated. Once published, the claim will be narrow: *this tool
was measured*, unlike role-play prompts. It is **not** a claim that it
predicts your score; real reviewers disagree with each other by more than
that. Disagreement (σ) is reported with every aggregate for exactly this
reason.

## Use it from a coding agent

[`skills/prebuttal/SKILL.md`](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/skills/prebuttal/SKILL.md)
teaches any agent to drive the CLI and interpret its JSON — including relay
mode, where the reviewers are the agent's own subagents. Its one hard rule:
the agent **runs the CLI**, never role-plays the reviewers itself.

```bash
mkdir -p ~/.claude/skills/prebuttal && curl -fsSL -o ~/.claude/skills/prebuttal/SKILL.md \
  https://raw.githubusercontent.com/GuoYuKai-SaMuEl/prebuttal/main/skills/prebuttal/SKILL.md
```

Other agents: copy `skills/prebuttal/` wherever yours discovers skills, or
reference the file from `AGENTS.md`. Inside Claude Code or Gemini CLI,
`prebuttal run` and `prebuttal backends` print a one-line relay hint;
`PREBUTTAL_BACKEND=relay` pins relay for a whole environment. Relay is never
chosen automatically: the CLI must run in the background while the agent
answers, or both sides wait on each other.

## Reference

### API keys and environment variables

```bash
prebuttal key set gemini     # hidden prompt, stored for next time
# or set GEMINI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / OPENROUTER_API_KEY yourself
```

Stored keys live in `~/.prebuttal/keys.env` (user-only, like
`~/.aws/credentials`); real environment variables win, so CI is unaffected.
`prebuttal backends` shows what is set (masked); `prebuttal key unset <name>`
removes one. Keys are never written to reports, JSON or share pages, never
passed to agent CLIs, and the agent CLIs get no tool that could read the file.

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) / `OPENROUTER_API_KEY` | enable the matching API backend |
| `OPENAI_BASE_URL` | point `api-openai` at an OpenAI-compatible proxy |
| `PREBUTTAL_OPENAI_MODEL` / `PREBUTTAL_ANTHROPIC_MODEL` / `PREBUTTAL_GEMINI_MODEL` / `PREBUTTAL_OPENROUTER_MODEL` | override each backend's default model |
| `PREBUTTAL_OLLAMA_HOST` (or `OLLAMA_HOST`) | Ollama address (default `http://localhost:11434`; Ollama's own `0.0.0.0:11434` form works too) |
| `PREBUTTAL_BACKEND` | one backend for every reviewer and the AC (e.g. `relay`); `--backend` still wins, `prebuttal.toml` loses |
| `PREBUTTAL_HOME` | run-history and key storage location (default `~/.prebuttal`) |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 2 | bad usage / config error / paper not found / unknown run id |
| 3 | no review backend available |
| 4 | partial failure (some reviewers or the AC failed; report still written — `prebuttal retry`) |
| 5 | every reviewer failed |
| 6 | `prebuttal check` found something that can get the paper desk-rejected |
| 130 | interrupted (Ctrl+C); finished reviews are archived — `prebuttal retry` completes the run |

## How it works

```
PDF / LaTeX dir / arXiv link
   ├─ pre-flight check: anonymity, page limit, required sections, leftovers
   └─ ingestion: sections, cell-accurate tables, figure captions, refs
        └─ reviewer pack (budget-aware; tables are never truncated)
             ├─ R1 senior_kind ──────┐ three independent contexts,
             ├─ R2 adversarial ──────┤ parallel fan-out, venue form + JSON schema
             ├─ R3 detail_obsessive ─┤
             └─ AC area chair ◄──────┘ meta-review, estimated rating, revision plan
                  └─ Markdown + HTML report per run · JSON · project history
```

Orchestration lives in the CLI, not the host agent — the same pipeline runs
from a terminal, inside any coding agent, or in CI.

| Approach | Form | Venue forms | Calibration | Cross-model | Tables in-pipeline |
|---|---|---|---|---|---|
| **Prebuttal** | CLI + agent skill | NeurIPS / ICLR / ICML / ARR + any custom | OpenReview script (results pending) | claude × codex × API × Ollama | cell-by-cell |
| generic "review my paper" prompts / skills | prompt or skill | varies | rarely | single model | via the host model |
| multi-agent peer-review research code | research code | study-specific | study-specific | sometimes | rarely |
| paste into a chatbot | chat | ✗ | ✗ | ✗ | ✗ |

## Roadmap

Pre-1.0: patch releases are fixes and small additions, minor releases are
substantial features. In short (details in
[ROADMAP.md](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/ROADMAP.md)):

1. **0.5 (current) — nothing leaks before submission**: `prebuttal check`,
   agent CLIs with no tool that can read your keys, `backends` as the one
   setup view
2. **0.6 — a revision loop you can trust**: repeated reviews, a diff that
   says when a change is within noise, meaning-based matching by default
3. **0.7 — reach**: more venues, community personas, a GitHub Action for papers
4. **Separate track** — calibration against real OpenReview outcomes

## Contributing

```bash
git clone https://github.com/GuoYuKai-SaMuEl/prebuttal && cd prebuttal
python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # Windows: .venv\Scripts\pip
pytest -q
```

The easiest contributions are venue forms, personas and backends — see
[CONTRIBUTING.md](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/CONTRIBUTING.md)
for the three-step guide and the project's design commitments (fewer flags,
honesty first). Security issues: [SECURITY.md](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/SECURITY.md).
Please follow the [Code of Conduct](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/CODE_OF_CONDUCT.md).

## Honesty & policy

- Every review is **labelled** with the backend and model that produced it.
- Score **disagreement** is reported, always. High σ is information.
- It is a stress test, **not** a predictor — every report says so.
- Mind conference policies: with [NeurIPS 2026 running an official
  AI-assisted reviewing experiment](https://neurips.cc/Conferences/2026/ai-reviewing-experiment),
  the etiquette is clear — AI to *prepare* your own paper is yours to decide;
  AI to *review* others' papers must follow each venue's disclosure rules.

### Privacy & data custody

- **Your paper's text goes to whatever backend you configure.** With API or
  agent-CLI backends it is sent to that provider (OpenRouter further routes
  it to an upstream provider). What happens there — retention, training,
  human review — is governed **solely by that provider's terms**.
- **Prebuttal is an integration layer, not a data custodian.** The project
  runs no models and no servers; it never sees your paper.
- **Local-only is a first-class path**: `ollama` keeps the text on your
  machine (as long as the Ollama address is local), and `relay` leaves who
  answers entirely to you.
- **What Prebuttal stores stays on your disk**: run history under
  `~/.prebuttal/` and keys in `~/.prebuttal/keys.env`, both user-only. No
  telemetry. Reports and share pages quote your paper — sharing them
  publishes those excerpts.

## License

MIT. Prebuttal is an independent project, not affiliated with or endorsed by
NeurIPS, ICLR, ICML, ACL/ARR or any model provider. Venue names only describe
which review form a report follows; the forms are paraphrased summaries of the
public reviewer guidelines.
