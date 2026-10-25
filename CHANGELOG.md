# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While pre-1.0: **patch** releases (0.1.x) are fixes and small additions; **minor**
releases (0.2, 0.3, …) are substantial new features.

## [Unreleased]

### Added

- `api-openrouter` backend: one OPENROUTER_API_KEY, hundreds of models,
  OpenAI-compatible wire format (attribution headers sent; JSON mode not
  forced since many OpenRouter models reject it). Default is a `:free` model
  (google/gemma-4-31b-it:free, non-reasoning — reasoning models on the free
  tier can spend the whole token budget on hidden thinking and return no
  content; that case now fails fast with an actionable error instead of
  retrying) so the zero-cost story holds; `:free`
  ids show as $0 in `--dry-run`. `prebuttal key set openrouter` stores the
  key. `prebuttal models` scans OpenRouter's public catalog with no key at
  all — free ids first with live per-1M prices, then curated notables — and
  the reviewer wizard accepts typing any custom model id. Free-tier
  resilience: `:free` reviewers dispatch staggered a few seconds apart and
  transient failures (429/5xx/empty) back off harder (6/12/24s, one more
  retry) since shared free pools saturate in waves.
- Interactive plan confirmation for auto mode: on a terminal, `prebuttal run`
  shows the full review plan (personas, backends, models, cost) before calling
  anything — `[Enter]` runs, `[e]` opens a numbered-menu wizard (persona →
  backend → live model list from `prebuttal models`), `[n]` aborts.
  Non-interactive contexts (CI, pipes) print the plan and proceed; `-y` /
  `--yes` silences; fully-explicit configs never prompt. `--dry-run` plans now
  show personas too, and backends registered via `register_backend` are
  eligible for auto assignment.
- `PREBUTTAL_BACKEND` environment variable: force one backend for every
  reviewer and the AC (e.g. `relay` for agent-subagent reviewing);
  precedence `--backend` > `PREBUTTAL_BACKEND` > `prebuttal.toml`.
- Inside a coding agent (Claude Code, Gemini CLI), `prebuttal run` and
  `prebuttal backends` print a hint pointing at relay mode.
- `prebuttal models` — live model discovery per backend: scans the Gemini /
  OpenAI / Anthropic model-list endpoints and Ollama's installed models
  (non-chat ids filtered out), shows the claude CLI aliases, marks the current
  default with `*`, and prints a copy-paste `model = "..."` toml example.
- `prebuttal key set/status/unset` — quick API-key setup: hidden-input prompt,
  stored in `~/.prebuttal/keys.env` (user-only, env vars take precedence);
  `prebuttal backends` and runs pick stored keys up automatically.
- Type checking: mypy (CI-enforced) and `py.typed` marker for downstream users.
- Regression fixture: a real pdflatex-compiled PDF locks ingestion behavior
  (wrapped titles, separate number/title heading lines, kerned decimals).
- README reference: environment variables, exit codes, skill installation.
- OpenAI/Anthropic request-shape tests and the Windows `cmd /c` agent-CLI
  fallback test; calibration parser unit tests.
- `prebuttal run` — review a paper from a PDF file, a LaTeX project directory,
  or an arXiv link/id, against the real review form of NeurIPS, ICLR, ICML or
  ACL Rolling Review (official scales and anchors; forms are plain-text and
  community-editable).
- Three independent-context reviewers + an area chair, fanned out in parallel;
  score aggregation with disagreement (σ, range) and per-review backend/model
  transparency in every report.
- Ingestion pipeline: LaTeX parsing with cell-accurate `tabular` extraction
  (`\multicolumn` expansion, `\label`/`\ref` resolution, appendix numbering,
  `.bbl` references), PDF parsing with ruled-table detection and
  caption-block fallback, arXiv download with metadata title.
- Reviewer pack with budget policy: abstract and all tables are never
  truncated; optional LLM compression (`compress = true`) for elided sections.
- Provider layer with startup auto-detection: `agent-claude` (`claude -p`),
  `agent-codex` (`codex exec`), `api-gemini` / `api-openai` / `api-anthropic`,
  local `ollama`, the file-protocol `relay` backend (human / host-agent
  subagents / external systems as responders), and custom `[agents.<name>]`
  CLI backends.
- Outputs: venue-format Markdown report, machine-readable `--json`,
  self-contained `--share` HTML page, `--dry-run` cost/backend matrix.
- Personas: `senior_kind`, `adversarial`, `detail_obsessive`, `area_chair`,
  and the `paper_roast` easter egg.
- `prebuttal.toml` configuration (per-reviewer persona × backend × model ×
  temperature × seed), `prebuttal init`, `prebuttal backends`.
- Agent skill (`skills/prebuttal/SKILL.md`) including relay mode.
- Calibration pipeline (`scripts/calibration/`): predicted vs true OpenReview
  ratings, scatter plot + MAE.
- Run history: every run archived under `~/.prebuttal` (reports, JSON, resolved
  config; best-effort, `--no-save` to opt out) with `prebuttal runs` / `show` /
  `diff` — score deltas and weakness movement (gone / persists / new) across
  revisions.

### Changed

- Default models brought up to the current mid-tier generation (verified
  against live model listings, 2026-10): `api-gemini` → **gemini-3.5-flash-lite**
  (latest flash-lite; cheapest long-context tier for the free-quota path),
  `api-openai` → **gpt-5.6-terra** (the GPT-5.6 balanced tier),
  `api-anthropic` → **claude-sonnet-5-5**. Old ids still work when pinned
  explicitly; pricing table extended accordingly. `prebuttal models` filters
  more non-chat noise (gemma / lyria / omni / robotics / nano-banana).

### Fixed

- Per-reviewer `model` now actually reaches agent-CLI backends
  (`claude -p --model X`, `codex exec --model X`); previously it was recorded
  in reports but never passed to the CLI.
- Auto mode no longer assigns reviewers to `relay` (which waited up to 30 min
  for a hand-written answer): relay is now explicit-only (`--backend relay`),
  and with no automatic backend `prebuttal run` exits 3 with guidance.
- Agent CLIs are launched via the path `prebuttal backends` detected, so
  npm-installed `claude.cmd` / `codex.cmd` work on Windows.
- API keys loaded from `~/.prebuttal/keys.env` are no longer passed to agent
  CLIs (a stored `ANTHROPIC_API_KEY` switched `claude -p` from subscription
  auth to API billing).
- LaTeX: `table*` / `figure*` were captured twice (duplicate tables, shifted
  numbers, wrong `\ref`); `tabular*` leaked its column spec into the first
  cell; nested `\input` now resolves from the root directory like LaTeX, and
  unresolvable inputs produce an ingestion warning instead of vanishing.
- PDF ingestion on real LaTeX output: wrapped titles now join into one title,
  section numbers separated from their titles merge back (side-by-side or
  stacked), and table cells are rebuilt from word geometry so kerned decimals
  survive (`47.9` no longer reads `479 .`; negative deltas keep their sign).

[Unreleased]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/HEAD
