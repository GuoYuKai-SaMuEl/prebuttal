<div align="center">

# Prebuttal

**Answer Reviewer 2 before Reviewer 2 exists.**

A pre-submission stress test for ML papers: three independent AI reviewers
and an area chair, on the real NeurIPS / ICLR / ICML / ARR / CVPR review forms.

[![PyPI](https://img.shields.io/pypi/v/prebuttal.svg)](https://pypi.org/project/prebuttal/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/pyproject.toml)
[![CI](https://github.com/GuoYuKai-SaMuEl/prebuttal/actions/workflows/ci.yml/badge.svg)](https://github.com/GuoYuKai-SaMuEl/prebuttal/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/LICENSE)

[**Website**](https://guoyukai-samuel.github.io/prebuttal/) ·
[**Guide**](https://guoyukai-samuel.github.io/prebuttal/guide/) ·
[**Sample report**](https://guoyukai-samuel.github.io/prebuttal/reports/sample.html) ·
[**Real-paper demos**](#see-it-on-real-papers) ·
[Changelog](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/CHANGELOG.md) ·
[Roadmap](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/ROADMAP.md)

English · [简体中文](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/README.zh-CN.md) · [繁體中文](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/README.zh-TW.md)

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
Fix first: [must] no "NeurIPS Paper Checklist" section — the venue requires one
           [must] Section 3.1 / Table 1: baseline Transformer trained for 1 epoch vs GlobalGate for 5 epoch…
           [must] Section 3.1: the same 200 LongQA-Mini questions are used for hyperparameter selection and…
Report:   prebuttal-reports/globalgate-a-universal/2026-10-27_2228_neurips/report.html
```

<sub>Real output (report path shortened) on <a href="https://github.com/GuoYuKai-SaMuEl/prebuttal/tree/main/examples/weak-paper">a fictional paper with planted flaws</a>: claude, codex and Gemini as the three reviewers.</sub>

## Highlights

- **Three reviewers, zero shared context.** Each runs as its own call or
  process — optionally on different models (Claude × Codex × Gemini × …) — so
  verdicts genuinely differ, and the disagreement is always reported.
- **Real review forms.** NeurIPS 1–6, ICLR 1–10, ICML 1–10, CVPR 1–5, ARR
  Soundness/Excitement/Overall with the official anchors; any other venue is
  one TOML file.
- **Your tables, cell by cell.** LaTeX and PDF ingestion keeps every number,
  so reviewers cite "Table 3, column 4" — not a guess.
- **A revision plan, not just a verdict.** The area chair turns the reviews
  into a prioritised must / should / could checklist; `prebuttal diff` checks
  it against the next round.
- **A desk-reject pre-flight.** `prebuttal check` catches anonymity leaks,
  page-limit overruns, missing required sections and leftover `??` — no
  model, no cost, also as a GitHub Action.
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
prebuttal run paper.zip --venue cvpr        # Overleaf: Menu → Download → Source
```

Python 3.11+. `prebuttal backends` shows what you can review with; if nothing
is ready, it tells you the quickest way to get one (often `prebuttal key set
gemini` for a free key). Each run prints its report paths and the next useful
commands. Everything else is in the [guide](https://guoyukai-samuel.github.io/prebuttal/guide/).

## See it on real papers

| Paper | Venue | Prebuttal | Real outcome |
|---|---|---|---|
| [Direct Preference Optimization](https://guoyukai-samuel.github.io/prebuttal/reports/dpo.html) | NeurIPS 2023 | 4.33/6 · AC 5 | accepted (oral) |
| [LLaVA-1.5](https://guoyukai-samuel.github.io/prebuttal/reports/llava.html) | CVPR 2024 | 3.33/5 · AC 4 | accepted (highlight) |
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

## Documentation

The [**guide**](https://guoyukai-samuel.github.io/prebuttal/guide/) covers every
command and setting, task by task:

- [**Before you submit**](https://guoyukai-samuel.github.io/prebuttal/guide/#check) —
  `prebuttal check` finds anonymity leaks, page-limit overruns, missing required
  sections, `??` and hidden text, in a PDF or a LaTeX project (folder or Overleaf
  `.zip`). Exit code 6 means a desk-reject risk. Per-venue checklists:
  [NeurIPS](https://guoyukai-samuel.github.io/prebuttal/venues/neurips/) ·
  [ICLR](https://guoyukai-samuel.github.io/prebuttal/venues/iclr/) ·
  [ICML](https://guoyukai-samuel.github.io/prebuttal/venues/icml/) ·
  [ARR](https://guoyukai-samuel.github.io/prebuttal/venues/acl/) ·
  [CVPR](https://guoyukai-samuel.github.io/prebuttal/venues/cvpr/).
- [**A mock review**](https://guoyukai-samuel.github.io/prebuttal/guide/#review) —
  the plan and cost before anything runs (`--dry-run`), the three personas, and how
  to read the report.
- [**The revision loop**](https://guoyukai-samuel.github.io/prebuttal/guide/#revision-loop) —
  `--note`, `prebuttal diff` (`--llm` matches by meaning), `prebuttal retry`.
- [**Projects & history**](https://guoyukai-samuel.github.io/prebuttal/guide/#projects) —
  `projects`, `runs`, `show` (`--open`, `-o`, `--plan`, `--json`), `note`, `rm`.
- [**Backends & privacy**](https://guoyukai-samuel.github.io/prebuttal/guide/#backends) —
  what `auto` picks, API keys (`prebuttal key set`), environment variables.
- [**Configuration**](https://guoyukai-samuel.github.io/prebuttal/guide/#configuration) —
  every `prebuttal.toml` setting: per-reviewer backends and models, `effort`,
  `figures`, `[output]`.
- [**Your own venue**](https://guoyukai-samuel.github.io/prebuttal/guide/#venues) —
  any review form and scale as one TOML file.
- [**Inside a coding agent**](https://guoyukai-samuel.github.io/prebuttal/guide/#agents) —
  the agent skill and relay mode.
- [**Command reference**](https://guoyukai-samuel.github.io/prebuttal/guide/#reference)
  and exit codes.

## On every push: the GitHub Action

For a paper kept in a GitHub repository, `prebuttal check` runs on every push and
pull request. It needs no secrets: nothing is sent anywhere.

```yaml
# .github/workflows/paper.yml
name: Paper
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: GuoYuKai-SaMuEl/prebuttal@v0.6.0
        with:
          paper: paper/          # a LaTeX folder, main .tex or .zip, or a built PDF
          venue: cvpr            # optional: else prebuttal.toml, else neurips
```

The job fails on anything that can get the paper desk-rejected; every finding is
also an annotation on the run and the pull request.

## Privacy

Your paper's text goes to the backend you configure, and what happens there is
that provider's policy, not ours: Prebuttal runs no models and no servers, and
sends no telemetry. **Free tiers are usually paid for with your data** — fine for
published papers and for trying the tool; for unpublished work check the terms,
use a paid tier, or stay local with `ollama` or `relay`. Run history and stored
keys stay on your disk, user-only.

## Honesty & policy

- Every review is **labelled** with the backend and model that produced it.
- Score **disagreement** is reported, always. High σ is information.
- It is a stress test, **not** a predictor. A
  [calibration script](https://github.com/GuoYuKai-SaMuEl/prebuttal/tree/main/scripts/calibration)
  against real OpenReview ratings exists; no results are published yet, so treat
  every score as uncalibrated.
- Mind conference policies: with [NeurIPS 2026 running an official
  AI-assisted reviewing experiment](https://neurips.cc/Conferences/2026/ai-reviewing-experiment),
  the etiquette is clear — AI to *prepare* your own paper is yours to decide;
  AI to *review* others' papers must follow each venue's disclosure rules.

## Roadmap

Pre-1.0: patch releases are fixes and small additions, minor releases are
substantial features. In short (details in
[ROADMAP.md](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/ROADMAP.md)):

1. **0.5 — nothing leaks before submission**: `prebuttal check`
   (also as a GitHub Action), agent CLIs with no tool that can read your
   keys, `backends` as the one setup view; CVPR and Overleaf .zip sources
2. **0.6 (current) — a smaller CLI**: the 0.4 aliases go, `plan` becomes
   `show --plan`, and `run` keeps only per-run flags (project-wide ones
   live in `prebuttal.toml`)
3. **0.7 — a revision loop you can trust**: repeated reviews, a diff that
   says when a change is within noise, meaning-based matching by default
4. **0.8 — reach**: more venues, community personas
5. **Separate track** — calibration against real OpenReview outcomes

## Contributing

```bash
git clone https://github.com/GuoYuKai-SaMuEl/prebuttal && cd prebuttal
python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # Windows: .venv\Scripts\pip
pytest -q
```

The easiest contributions are venue forms, personas and backends — see
[CONTRIBUTING.md](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/CONTRIBUTING.md)
for the three-step guide and the project's design commitments (fewer flags,
honesty first). Personas and venue forms are plain text in
[`prebuttal/personas/`](https://github.com/GuoYuKai-SaMuEl/prebuttal/tree/main/prebuttal/personas) and
[`prebuttal/venues/forms/`](https://github.com/GuoYuKai-SaMuEl/prebuttal/tree/main/prebuttal/venues/forms).
Security issues: [SECURITY.md](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/SECURITY.md).
Please follow the [Code of Conduct](https://github.com/GuoYuKai-SaMuEl/prebuttal/blob/main/CODE_OF_CONDUCT.md).

## License

MIT. Prebuttal is an independent project, not affiliated with or endorsed by
NeurIPS, ICLR, ICML, ACL/ARR, CVPR or any model provider. Venue names only describe
which review form a report follows; the forms are paraphrased summaries of the
public reviewer guidelines.
