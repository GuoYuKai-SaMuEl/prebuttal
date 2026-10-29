# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While pre-1.0: **patch** releases (0.1.x) are fixes and small additions; **minor**
releases (0.2, 0.3, …) are substantial new features.

## [Unreleased]

### Changed
- Internal: dead code removed (`BackendStatus.line()`, `EFFORTS`), the
  CLI command dispatch folded into one table (with `run` listed explicitly),
  and small duplicated helpers merged (key-file serialisation and its 0600
  write path, words-in-box filter, heading-word table). No behavior change.

### Fixed
- `check` page counting: a lone centred "References" heading (ACL-style
  single-column papers) no longer reads the reference entries below it as
  main text; lines to the heading's left now count only on a page with a
  real second column.
- Two `prebuttal run` processes finishing at the same moment on one project
  no longer get the same run number: history numbering takes a brief
  cross-process lock (best-effort: a stale or busy lock never blocks
  archiving a finished run).
- `note` / `rm` / `projects rename` rewrite the whole history file; a run
  archived in that same moment is no longer lost to the rewrite — they take
  the same cross-process lock as archiving.
- Ollama's URL is normalised in one place: `localhost` and `0.0.0.0` both
  show as and are called on `127.0.0.1`, in listings and errors alike.
- Indicative price table: claude-haiku-5-5 added at its launch pricing
  ($0.10/$0.50 per 1M; 5x over 100k prompt tokens).

## [0.5.0] — 2026-10-28

"Nothing leaks before submission": the paper must not leak its authors, and
the tool must not leak your keys.

### Added
- **`prebuttal check <paper>`** — a deterministic desk-reject pre-flight: no
  model, no cost; `--venue` as for `run` (else `prebuttal.toml`, else neurips).
  Anonymity (author names in the PDF metadata, e-mails on page 1, a
  camera-ready, NeurIPS `[preprint]` or `[nonanonymous]` build, a visible acknowledgements
  section, links to your own repository, "our previous work [12]"), format
  (main-text pages over the venue's limit, a missing NeurIPS checklist / ICML
  impact statement / ARR limitations section) and leftovers (`??`, `[?]`,
  TODO, hidden text). LaTeX projects are checked without compiling: every
  `\ref` needs a `\label` and every `\cite` a bibliography entry (macro
  parameters like `\ref{#1}` and `\nocite{*}` aside), and a named
  `\author{...}` is flagged unless a venue style in submission mode
  (`neurips_*`, `iclr*_conference`, `icml*`, a `[review]` / `[anonymous]`
  option) hides it. Two-column pages count
  when their left column is still main text. Exit code 6
  when something can get the paper desk-rejected.
- `prebuttal run` performs the same check on your own draft (a local PDF
  or LaTeX project) and lists its findings in the report's notes; arXiv
  papers are public and camera-ready, so they are not checked there.
- Venues carry their check rules (page limit, uncounted sections such as
  References or ICML's impact statement, required sections, camera-ready
  markers), each with the URL of the call it came from; custom venues set
  theirs in a `[checks]` table (`double_blind`, `page_limit`,
  `required_sections`, which don't count toward the limit), and
  `prebuttal venues new` writes one.

### Changed
- **`prebuttal backends` is the one setup view**: every backend, whether
  it's ready, where its access comes from (CLI login, env var or stored key,
  masked) and its default model. `prebuttal backends <name>` lists that
  backend's models. `prebuttal models` and `prebuttal key status` still work
  as hidden aliases (with a notice) and will be removed in 0.6.
- **One command per thing you look at** (17 → 14 commands): `show` is a
  run's report — printed, `--open` in the browser (was `prebuttal open`),
  or saved with `-o FILE`, the extension picking the format (was
  `prebuttal export`); `projects --open` is the HTML overview of every
  paper (was `prebuttal dashboard`). `--open` means the same thing on both.
  `run` loses `--stdout` (`prebuttal show` after the run) and `--format`
  (`[output] formats` in `prebuttal.toml`; `--json PATH` stays). The old
  names keep working as hidden aliases with a notice until 0.6. `plan`,
  `diff`, `note`, `retry` and `projects` / `runs` stay apart: each does one
  job, and merging them needed a flag or an argument with two meanings.
- `prebuttal rm mamba` deleted the newest run of `mamba` — one word away
  from `prebuttal projects rm mamba`, which deletes them all. `rm` now
  refuses a bare project name and asks for the run (`mamba#3`, `mamba~1`).
- The `prebuttal.toml` that `prebuttal init` writes no longer triggers the
  "use this file's settings?" question on the first run (it still comes
  back once the file is edited). Help texts now say what a run reference
  looks like, which venue `check` defaults to, where the run history lives
  (`$PREBUTTAL_HOME`) and how projects are named.
- Report and share-page notes are labelled "Notes" instead of "Ingestion
  warnings", since they now include the pre-flight check.

### Security
- **Codex can no longer read files**, so it can't read stored API keys
  either. Its read-only sandbox still let a shell read any file the user can
  on macOS and Linux (Windows rejects the shell outright); `codex exec` now
  runs with its shell, code mode, browser, computer-use and apps features
  switched off and web search disabled. Claude already ran with no tools at
  all. A codex that no longer knows one of these features stops with an
  error instead of running with it on. The threat model is in SECURITY.md:
  isolation, not output filtering — and why an OS keyring would not help.
- A custom `[agents.*]` reviewer gets a one-line notice when keys are stored,
  since prebuttal can't remove its tools.

### Fixed
- `--backend` (and `PREBUTTAL_BACKEND`) kept the models `prebuttal.toml` set
  for other backends — `--backend api-gemini` sent `sonnet` to Gemini. A
  role moved to another backend now gets that backend's default model,
  unless `--model` names one.
- A local folder named like an arXiv id (an unpacked source tarball,
  `2312.00752/`) was reviewed by downloading the public PDF instead of
  reading the local, possibly revised copy. A local path now always wins.
- LaTeX: every section took the level of the document's last section
  command, and `\section*` headings were numbered, shifting every number
  after them away from the PDF's.
- Ollama: `OLLAMA_HOST` as Ollama documents it (`0.0.0.0:11434`, no
  scheme) made Ollama look unreachable; it is now read the way Ollama does.
- The dry run showed default seeds even where a reviewer sets its own.
- Diff: one new weakness could count as "persists" for two old ones;
  matching is one-to-one.
- A report folder is created race-free when two runs finish in the same
  minute.
- Stored API keys are loaded only for commands that reach a backend, and
  "using stored keys" is printed only when a model is about to be called —
  not on `check`, `runs`, `venues` and the other commands that call none.

## [0.4.1] — 2026-10-27

### Security
- **Relay**: a request could be answered by a stale `.ans.md` left in the
  spool by an earlier run whose process id happened to be reused, silently
  attaching a review of a different paper. Request names now carry a random
  part, and any old answer under the same name is removed first.
- **LaTeX ingestion**: a symlinked `main.tex` or `main.bbl` in an unpacked
  source tree could still pull a file from outside the paper's folder into
  the text sent to the model provider (`\input` was already contained). Both
  are now held to the same boundary.
- **Agent CLIs**: model ids and effort levels must look like model ids. One
  from a discovered `prebuttal.toml` could otherwise turn into a CLI flag
  (`--dangerously-…`) or, through npm's `.cmd` launchers on Windows, a
  `cmd.exe` operator (`& …`).
- **Stored keys**: only the four API-key variables in `keys.env` are applied
  (a hand-edited `PYTHONPATH=` line no longer reaches the environment), and
  a key containing spaces or line breaks is refused rather than written as
  extra entries.
- **Share page**: the repository link is dropped unless it is `http(s)://`
  (`repo_url` can come from a discovered config; no `javascript:` links).

### Fixed
- A rating of `NaN` / `Infinity` in a model's JSON (Python's parser accepts
  both) is treated as missing instead of poisoning the panel mean; a
  non-numeric `Retry-After` such as `nan` no longer crashes the retry wait.
- An agent CLI that doesn't know the model id (e.g. `claude` given `haiku-5.5`
  instead of `claude-haiku-5-5` / `haiku`, or codex's `model_not_found`) now
  fails at once with a "check the model id" message, instead of being retried
  twice as if it were a transient error.
- The `diff` footer no longer calls the comparison "heuristic", which
  contradicted the "matched by …" line under `diff --llm`.

### Changed
- Pillow is now a declared dependency (`--figures` imports it directly); it
  was already installed through pdfplumber, so installs don't change.
- The roadmap moved to `ROADMAP.md`: 0.5 "nothing leaks before submission"
  (`prebuttal check`, keys out of reach of agent CLIs, a smaller CLI), 0.6
  "a revision loop you can trust", 0.7 "reach".

## [0.4.0] — 2026-10-27

### Added
- **`prebuttal retry [run]`** re-runs only the reviewers that failed (an
  overloaded backend, a timeout) plus the area chair, on the exact text the
  others reviewed, and archives the result as a new run of the project — the
  finished reviews are not paid for twice. No options: the same backends,
  models, seeds and figures as the original run (a different model is a new
  run). Runs now archive their reviewer text (`pack.md`, in the private run
  store); runs from 0.3.1 and earlier can't be retried.
- **Ctrl-C keeps finished reviews.** Interrupting a run archives the reviews
  that already finished (note `interrupted`, exit code 130), so
  `prebuttal retry` can complete it instead of starting over.
- **Hidden-text check.** Text a human reader cannot see — white glyphs (not
  on a coloured box), microscopic (< 1pt) or off-page text in a PDF, and
  `\textcolor{white}{...}` / `{\color{white} ...}` in LaTeX — is reported as
  the first ingestion warning, flagged as **likely prompt injection** when it
  addresses reviewers or AI systems, and quoted to the reviewers in a tool
  note so protocol rule 6 can apply. No false alarms on the Transformer, ViT,
  LoRA, DPO and Mamba PDFs. The HTML share page shows it as a
  red alert at the top (other ingestion notes folded below it).
- **`prebuttal diff --llm`** matches the previous run's revision plan
  against the new run by meaning, with one call to the configured AC
  backend: an issue reworded in round B no
  longer shows up as both "not re-detected" and "new". Word overlap stays the
  default and the fallback when the model's answer is unusable.
- **Relay protocol: atomic answers.** Responders are told (README.txt, each
  request file, SKILL.md) to write `<stem>.ans.md.tmp` and rename it to
  `<stem>.ans.md`, so the CLI never reads a half-written answer; in-place
  writers still work through the completeness/stability check. A spool's
  README.txt from an older version is refreshed.
- **Figures as images (`--figures`, or `figures = true`).** Reviewers on
  vision-capable API backends (Anthropic, OpenAI, Gemini, OpenRouter) also
  see the figures: PDF/arXiv pages that hold a figure caption, or each LaTeX
  figure's first `\includegraphics` (inside the project folder only), at most
  `max_figures` (default 6). Off by default; a text-only model is retried
  without images; each review records how many images it saw, and `retry`
  re-sends the archived images.

### Changed
- **Upgrade note — a `prebuttal.toml` found in the current directory** (not passed with
  `--config`) now also needs a yes before it can send the paper to a backend
  it pins, or write reports / the relay spool outside the current directory
  — not only before running `[agents.*]` commands. The yes is remembered per
  file content; non-interactive runs refuse as before (pass `--config`).
  An all-`auto` config like the one `prebuttal init` writes is unaffected.
- **Site samples re-run on 0.4** with one panel (claude sonnet · codex
  gpt-6-luna · gemini-3.8-flash, AC claude opus), seed 42. The Mamba
  revision page is rewritten honestly: with three seeds per version the score
  does not move (7.22 → 7.33, inside the noise) and every v1 plan item is
  raised again against v2 (matched by meaning). The old page's single-run
  "7.0 → 7.3" and "naming inconsistency fixed by the revision" claims are
  withdrawn. DPO 4.33/6, weak paper 1.33/10.
- **Design commitment: fewer parameters.** CONTRIBUTING.md now asks every
  new command to work with no options and every flag to earn its place
  (defaults, values derived from the run or config, or a `prebuttal.toml`
  setting come first).
- CI fails on any text I/O without an explicit `encoding=`
  (`PYTHONWARNDEFAULTENCODING=1` + `EncodingWarning` as an error), the bug
  class that only shows on non-UTF-8 Windows locales.

### Fixed
- PDF titles: a stray large glyph (a math symbol, a figure's lettering) no
  longer becomes the title — the Mamba PDF was titled "M".
- `scripts/build_site.py` added a blank line to every curated page on each
  rebuild.

## [0.3.1] — 2026-10-27

### Fixed
- **Reviewer pack:** the title and the `## Abstract` heading were glued onto
  one line (`# Submission under review — T## Abstract...`).
- **`compress = true`** summarized each cut section many times over (every
  budget pass re-ran the paid summarizer); it now runs once per section.
- **LaTeX `\input`/`\include` can no longer read files outside the paper's
  folder** (e.g. `\input{../../.ssh/id_rsa}` in someone else's source); such
  inputs are skipped with a warning. The brace-less `\input file` form is now
  inlined too instead of silently dropped.
- **Ctrl-C** during a run exits at once instead of waiting for in-flight
  calls (up to the 30-minute relay timeout).
- An unexpected error in one reviewer or the area chair no longer crashes the
  run and loses the other (paid) reviews; Ollama 5xx are retried and a
  non-JSON Ollama response is a clean error.
- **Relay:** a half-written `.ans.md` is no longer read; the answer is taken
  once it is a complete JSON object or stops changing.
- Custom agents with `stdin = false` refuse Windows `.cmd`/`.bat` launchers,
  where cmd.exe would interpret `&`, `|`, `%VAR%` in the paper text.
- **Config:** wrong value types are reported as config errors instead of a
  traceback; `[agents.x]` without `command` is rejected; `seed` in
  `[[reviewer]]` is now honoured; `--reviewers N` keeps the configured
  reviewers (backends, models) and only adds or drops some.
- `prebuttal note` / `rename` / `rm` no longer delete unreadable lines from
  the run history; `prebuttal diff` keeps reviewers that share a persona.

## [0.3.0] — 2026-10-26

### Added
- **Revision plan.** The area chair now also returns a prioritised plan
  (must / should / could, the issue, the concrete fix, which reviewers raised
  it, rough effort) — in the same call, no extra cost. It opens the Markdown
  and HTML reports and the JSON (`meta.action_plan`); the run prints the top
  items as `Fix first:`; `prebuttal plan [run]` prints it as a `- [ ]`
  checklist (`--json` for scripts); `prebuttal diff` checks the previous
  run's plan against the new run (not re-detected / still raised / new —
  matched by wording, and it says so when rewording may be involved).
- **Custom venues.** Any review form and scale — CVPR, AAAI, a journal, a
  revised ICML form, a lab's mock review — as one TOML file plus the form
  text, used with `--venue NAME` or `--venue path/to/venue.toml` (also in
  `prebuttal.toml`, relative to it). Looked up in `./.prebuttal/venues/`, then
  `~/.prebuttal/venues/`. `prebuttal venues` lists built-in and custom venues
  (flagging invalid files), `prebuttal venues new NAME [--from icml] [--here]`
  writes a commented template, `prebuttal venues show NAME` prints the scores
  and form reviewers will see. Files are validated before any model is
  called; reports store the venue definition so archived runs keep rendering.
- **Site samples on 0.3.0.** The weak-paper sample page is a fresh 0.3.0 run
  of the same fictional paper with the cross-model panel (claude sonnet,
  codex, gemini-3.8-flash; AC opus) — the first public sample showing the
  revision-plan section. DPO's sample is pinned to its published run so
  later re-runs can't silently replace it; the Mamba pages re-rendered with
  the v0.3 template.

### Fixed
- **Reviewer protocol guards: PDF-extraction artifacts and double-blind
  review.** Every reviewer and the area chair now get two more rules.
  Garbled table markup, misaligned columns, stray numbers and lost
  subscripts are extraction artifacts of the tool, not the authors' writing
  — never listed as a weakness, never a lower rating. And the submission is
  reviewed double-blind: no credit for the work's fame, citations or
  publication history, and no penalty either. Verified by A/B re-runs with
  identical packs: the adversarial reviewer had dropped Mamba v2 a full
  point while citing garbled tables among the weaknesses — restored; and a
  reviewer gave DPO a point of reputation credit — removed.
- **LaTeX conversion no longer manufactures presentation flaws.** List
  environments leaked their names into the text (`itemize - a - b itemize`),
  every math command was deleted (`\sigma(g_h)` became `(g_h)`), display
  equations lost their numbers and footnotes were printed twice. Reviewers
  then reported "broken itemize markup" and an "unnumbered equation" the
  paper did not have. Math is now kept as LaTeX, display equations carry
  their numbers, list items stay one per line, and protocol rule 7 covers
  LaTeX conversion as well as PDF extraction.
- OpenAI models after gpt-5 (`gpt-6-luna`, …) are recognised as reasoning
  models: no `temperature`, `max_completion_tokens`, and `--effort` applies.
  Before, they were sent the classic chat parameters.

## [0.2.1] — 2026-10-26

### Fixed
- **PDF table extraction, much more of it.** On ten well-known arXiv papers
  the tables recovered cell by cell went from 53 to 146 and those reduced to
  a bare caption from 99 to 10, with no unnamed tables left (there were 115);
  on Mamba v1/v2 every table now has its cells.
  - Booktabs rules are grouped by exact width before they are split
    vertically, so a table is no longer cut apart by the neighbouring
    column's rules, a full-width table no longer swallows column tables, and
    tables stacked in one column are separated at captions and empty gaps.
  - Captions are matched one-to-one to the nearest table *edge* (a tall
    table keeps its caption), on the side the paper uses for captions;
    side-by-side panels under one caption become one table; a boxed plot
    next to a figure caption is no longer taken for a table.
  - Ruled blocks with no caption are dropped instead of appearing as unnamed
    `t7` tables.
  - Captions numbered `3.1`, `A.2` or `S1` are recognised (GPT-3-style
    papers previously lost every table), and pifont check marks read as
    ✓ / ✗ instead of `(cid:51)`.
  - Columns are found from whitespace shared by nearly every row, so a
    `\multicolumn` header no longer glues the columns under it together;
    subscripts (`BERT_BASE`) join their word instead of adding a row; words
    in tightly set LaTeX are separated (`SSM Layer`, not `SSMLayer`).
  - A ruled block of prose (prompt examples, model outputs) is kept as text
    instead of being reduced to its caption.
- A table whose cells could not be extracted is now marked
  `[numbers not extracted]` in the reviewer pack, with a note that this is a
  tool limitation and not a flaw of the paper, and listed in the ingestion
  warnings.

## [0.2.0] — 2026-10-26

### Added
- **Projects.** Every paper gets a project, found from its source (PDF path,
  LaTeX folder or arXiv id — stable across title changes; `--project NAME`
  to choose), and every run a number within it (`mamba#3`).
- **Report folders that never overwrite.** By default each run writes
  `prebuttal-reports/<project>/<date>_<time>_<venue>/report.md` and
  `report.html`, plus `latest.md` / `latest.html`; the folder gets a
  `.gitignore` so reviews of unpublished work stay out of git. Configure with
  `--out-dir`, `--format md,html,json` or an `[output]` section.
- `prebuttal projects` (list / `rename` / `rm`), `prebuttal open` (HTML report
  in the browser), `prebuttal note`, `prebuttal rm`, `prebuttal export`, and
  `prebuttal dashboard` — a local, offline HTML overview of every project
  with score trends and links to each report.
- Run references everywhere: `latest`, `<project>`, `<project>#N`,
  `<project>~N`, or an id prefix. `show`, `open`, `export` and `diff` default
  to the newest run; `diff` with no arguments compares it with the run before.
- `run --note "what changed"`; `run` prints the change against the previous
  run of the same paper.
- **Reasoning effort** (`--effort low|medium|high`, `effort =` under
  `[default]`, `[[reviewer]]` or `[ac]`), mapped to each backend's own
  control: `claude --effort`, codex `model_reasoning_effort`, Anthropic
  `output_config.effort`, OpenAI `reasoning_effort`, Gemini
  `thinkingLevel` / `thinkingBudget`, OpenRouter `reasoning.effort`, Ollama
  `think`. Unset (the default) leaves every model at its provider's default;
  reports and `--dry-run` show the effort each role actually used.

### Removed
- `run --out` and `run --share`. Every run writes its own report folder
  (HTML included) instead; for a file at a fixed path use `--json PATH` or
  `prebuttal export -o PATH`. Passing either flag prints what replaces it.

### Changed
- `run` no longer writes `prebuttal-report.md` into the current directory
  (each run overwrote the last); HTML is produced by default and archived
  runs always include `report.html`.
- `prebuttal runs` shows `<project>#N` labels, dates and notes, and takes an
  optional project name.

### Fixed
- Overloaded backends (HTTP 503 / 502 / 504 / 529, as free Gemini tiers
  return under load) get the patient retry curve 429 already had — at least
  four retries over ~3 minutes, honoring `Retry-After` — instead of giving up
  after ~9 s. Each wait is announced on stderr, and a run that loses a
  reviewer says which one, why, and that the report uses the rest.
- `api-anthropic` no longer sends `temperature`: current Claude models
  accept only their default sampling and reject other values with a 400
  (the default model, Claude Sonnet 5.5, among them). `max_tokens` is raised
  to at least 16k so default-on thinking can't cut a review short.
- `api-openai` with a reasoning model (gpt-5 family, o-series — including the
  default model) sends `max_completion_tokens` and no `temperature`, both of
  which those models require.
- Reports no longer show a temperature or seed the backend never applied.
  Agent CLIs (`claude`, `codex`, custom `[agents.*]`) and relay expose
  neither and the Anthropic API has no seed; those cells now read `n/a` with
  a footnote, `report.json` gains `temperature_applied` / `seed_applied`, the
  share page omits the seed when no role used it, and `--dry-run` says which
  backends ignore it.
- `prebuttal export -o FILE` now follows the file's extension: `-o x.md`
  exports Markdown (it wrote HTML into `.md` files). `--format` still wins
  when given explicitly.
- `--dry-run` prices a backend's default model instead of printing
  `unknown price — add [pricing.""]` when no model is pinned.
- Runs archived before 0.2.0 get their rating scale back-filled from the
  venue, so they show `x/10`-style scores and join trends and the dashboard;
  the project trend column skips comparisons across different rating scales
  (e.g. iclr /10 vs neurips /6).

## [0.1.0] — 2026-10-25

First public release.

### Security

- Prompt-injection hardening — the paper is untrusted input. `agent-claude`
  now runs `claude -p --tools "" --strict-mcp-config` (no tools, no MCP),
  `agent-codex` runs `codex exec --sandbox read-only --ignore-user-config
  --ephemeral` (no user MCP servers, no session files holding the paper),
  and both start in an empty temporary directory instead of your project. Every prompt fences the
  paper in `<submission>…</submission>` as data and asks reviewers to report
  embedded instructions as a weakness. An outdated CLI that rejects the new
  flags fails fast with an "update the CLI" message. See SECURITY.md.
- Reports, JSON, share pages and run history no longer record the paper's
  absolute local path (it leaked user names when shared); local sources are
  shown relative to the working directory, else `~`, else by name.
- A `prebuttal.toml` merely found in the current directory can no longer run
  its `[agents.*]` commands silently (it could, e.g. inside someone else's
  paper repo): the commands are shown and need a yes; non-interactive runs
  refuse unless the file is passed with `--config`.
- `~/.prebuttal` (run history with paper text, `keys.env`) is user-only
  (0700); it used to be world-readable on shared machines.

### Added

- Release workflow: pushing a `v*` tag builds, tests and publishes to PyPI
  via Trusted Publishing (no API token stored anywhere).
- Python 3.14 and 3.15 in the CI matrix and classifiers; a CI job tests the
  oldest supported dependency versions.
- Synthetic weak-paper example (`examples/weak-paper/`, fictional, deliberately
  flawed) with a real 1/10 run, published on the site; real-paper sample pages
  carry an "unofficial, not endorsed by the authors" banner with CC BY 4.0
  attribution.
- GitHub Pages site (`site/`): landing page + curated sample reports (the
  Mamba and DPO full runs, regenerated from run history by
  `scripts/build_site.py`), deployed by the standard `pages` workflow —
  enable once in repo Settings → Pages → Source: GitHub Actions. The web
  quick-scan (drag-drop PDF + BYOK key, browser-only) is a v0.2+ roadmap
  item; hosted/public review services are explicitly out of scope.
- Privacy & data-custody disclaimer (README "Honesty & policy" + SECURITY.md):
  manuscript text sent to a backend is governed solely by that provider's
  terms; Prebuttal is an integration layer, not a data custodian. Local-only
  paths (`ollama`, `relay`) and what the tool itself stores (local disk only)
  are spelled out.
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
  saturation-style throttling (HTTP 429) backs off on a long curve
  (15/30/60s per call) since shared free pools stay closed for minutes.
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

- **PDF parsing moved from PyMuPDF (AGPL-3.0) to pdfminer.six + pdfplumber
  (MIT)**, so installing the MIT-licensed package no longer pulls in a
  copyleft dependency. Booktabs-style tables (horizontal rules only) get a
  dedicated detector; cell-accurate numbers, two-column layout and the real
  LaTeX regression fixture are covered by tests.
- Wording: scores are no longer described as "calibrated" — the calibration
  pipeline ships, published results are pending.
- README installs with plain `pip install prebuttal` (pipx / `uv tool` as
  the isolated alternative); share pages and the site say the same.
- Classifier `Development Status :: 3 - Alpha` (was Beta) to match pre-release.
- Machine-specific scripts moved to the gitignored `scripts/dev/`.
- Default models brought up to the current mid-tier generation (verified
  against live model listings, 2026-10): `api-gemini` → **gemini-3.5-flash-lite**
  (latest flash-lite; cheapest long-context tier for the free-quota path),
  `api-openai` → **gpt-5.6-terra** (the GPT-5.6 balanced tier),
  `api-anthropic` → **claude-sonnet-5-5**. Old ids still work when pinned
  explicitly; pricing table extended accordingly. `prebuttal models` filters
  more non-chat noise (gemma / lyria / omni / robotics / nano-banana).

### Fixed

- Windows: redirected output (`> log.txt`, pipes, CI) no longer crashes with
  `UnicodeEncodeError`; stdout/stderr are switched to UTF-8.
- The sdist now carries `tests/conftest.py`, the PDF fixture and the
  calibration script, so the test suite runs from the source tarball.
- `--out` / `--json` in a directory that doesn't exist yet no longer crashes
  after the reviews ran; parent dirs are created, and the run is archived
  before the outputs are written so a write error can't lose a paid review.
- arXiv downloads are streamed and capped at 100 MB.
- The relay spool directory writes its own `.gitignore` (it holds paper text).
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

[Unreleased]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/GuoYuKai-SaMuEl/prebuttal/releases/tag/v0.1.0
