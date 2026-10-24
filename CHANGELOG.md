# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While pre-1.0: **patch** releases (0.1.x) are fixes and small additions; **minor**
releases (0.2, 0.3, …) are substantial new features.

## [Unreleased]

### Added

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

### Fixed

- PDF ingestion on real LaTeX output: wrapped titles now join into one title,
  section numbers separated from their titles merge back (side-by-side or
  stacked), and table cells are rebuilt from word geometry so kerned decimals
  survive (`47.9` no longer reads `479 .`; negative deltas keep their sign).

[Unreleased]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/HEAD
