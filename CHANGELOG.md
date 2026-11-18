# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While pre-1.0: **patch** releases (0.1.x) are fixes and small additions; **minor**
releases (0.2, 0.3, …) are substantial new features.

## [Unreleased]

## [0.7.0] — 2026-11-18

### Changed
- **Site samples re-run on 0.7.0** with one panel on subscription CLIs
  (claude sonnet-5-5 · codex gpt-6.1-terra · gemini-4-hydrogen through agy,
  AC claude opus-5-5), seed 42. The Mamba revision page now comes from two
  runs with `repeats = 3`: 7.67 → 7.89, within the measured noise (±0.3),
  all 8 v1 plan items raised again. DPO 4.67/6, LLaVA-1.5 3.67/5, the
  fictional paper 1/10.
- `prebuttal diff` matches by meaning by default: one call pairs every
  reviewer's weaknesses, one checks the revision plan, so an issue B raises
  in other words is no longer counted as gone *and* new. The calls go to the
  backend, model and endpoint both runs' area chairs used, never to the one
  the current environment would pick: excerpts of a paper reviewed on Ollama
  stay local, and two OpenRouter models (two upstream companies) are not
  mixed. When the two differ, that backend can't be used (relay, an
  untrusted `prebuttal.toml`, its endpoint moved), or `PREBUTTAL_BACKEND` is
  set to `relay` or another backend, it falls back to word overlap and says
  why in one line.
  An answer that is incomplete or names an item that does not exist is not
  used at all, for plan items as for weaknesses (plan answers used to keep
  their valid parts). `--llm` is no longer needed: it still works, says so,
  and goes in 0.8.
- `prebuttal diff` compares reviewers by id and persona (`R1 · senior_kind`)
  rather than by persona. With `repeats`, a reviewer's rating is the mean of
  its rounds, and each weakness, merged over the rounds, says in how many
  rounds it was raised (`A: 2 of 3 rounds`): one raised once may be chance.
- `prebuttal diff` gathers its caveats in one closing `Notes` section, each
  shown only when it applies (matching by wording, a model match that fell
  back, a weakness raised in one round only, ratings not noise-checked);
  section headers just say how items were matched.
- `revdiff.Matcher` is no longer exported: the matchers are internal.
- Pillow's floor is 9.3, the first release with Python 3.11 wheels, and is
  now tested by the oldest-dependencies CI job.
- The built-in price table drops models that are shut down or retire
  within weeks: `gemini-2.0-flash`, `gemini-2.5-flash`, `claude-sonnet-4-5`,
  `gpt-4.1-mini` and `gpt-4o-mini`. A run on one of them shows "unknown
  price" in `--dry-run`, with the `[pricing."model-id"]` line that sets it.

### Added
- **`agent-agy` backend: the Antigravity CLI** (`agy`, Google's subscription
  CLI) — Gemini, and the other models agy offers, with no API key. Auto
  mode picks it after `agent-claude` and `agent-codex`, so the three CLIs
  together make a three-family panel. The paper goes in on stdin as one
  stream-json event; reports carry agy's real token counts. Locked down
  like the other agent CLIs: every file, shell, URL and MCP action denied,
  strict permissions (headless agy refuses anything that needs asking), no
  slash commands or skills, an empty temporary folder. Two limits it does not
  let prebuttal close: its web search is not covered by any permission rule
  (with no file readable, a paper can only send its own text to it), and agy
  keeps each conversation, the paper included, in
  `~/.gemini/antigravity-cli/conversations/`. `prebuttal backends agent-agy`
  lists its models; `effort` sets agy's thinking level. A model/effort pair
  agy rejects (an unknown id, a level the model lacks) stops at once with
  agy's reason. Inside Antigravity (`ANTIGRAVITY_AGENT=1`), `run` and
  `backends` print the relay hint as they do in Claude Code and Gemini CLI.
- The revision plan is followed across runs. After a run, its plan is
  checked against the project's previous run (one call to the AC's
  backend when the previous run's AC used the same backend, model and
  endpoint — the earlier plan goes nowhere that version was not sent; word
  overlap otherwise, and with relay) and the summary says `Plan: 3 of 5
  items of mamba#2 no longer raised · 1 new`. The match is kept in the run's
  folder (`plan-track.json`), as is the one `prebuttal diff` makes for two
  consecutive runs. The dashboard (`prebuttal projects --open`) lists each
  project's latest plan with the run each item first appeared in ("since
  #1", "new in #3") and the previous run's items no longer raised. It never
  calls a model: a pair with no kept match is matched by wording, and says
  so. Its score change reads "within noise" when chance alone could explain it.
  A run whose AC wrote no plan (cut short, or the AC failed) is stepped over
  rather than read as every earlier item fixed. A finished `prebuttal retry`
  replaces the run it completes (the history records it as `retry_of`; a
  retry archived by 0.6 has no such record and counts as a revision) and
  is checked against the run before that one. `prebuttal diff` of a pair the
  run already checked shows that check without a second call.
- `prebuttal diff` says whether the predicted score's change can be told
  from run-to-run noise: "within run-to-run noise (±0.99, estimated — not
  measured on this paper)", or "larger than …". A single run uses a default
  noise of 3.5% of the rating scale, measured on real runs (see
  `prebuttal/noise.py`), and suggests `repeats = 3` when the change is
  within it; runs with `repeats` use the spread of their own round means,
  so the band narrows. Individual reviewer ratings are marked as anecdotes
  and the AC estimate as not noise-checked; across rating scales nothing
  is compared, as before. The `Change:` line at the end of a run gives the
  same verdict.
- `repeats` in `prebuttal.toml` (advanced, 1–5, default 1): every reviewer
  reviews the paper that many times, to see how much its scores move by
  chance. Round *k* adds 1000·*k* to the reviewer's seed, so backends that
  honour seeds review afresh. The AC still runs once, reading every round
  grouped by reviewer (only summaries and weaknesses when they would
  outgrow `budget_chars`). `--dry-run` and the plan before a run multiply
  the reviewer cost by the rounds. Reports label rounds `R1·2`, `R1·3`, …;
  a single run is unchanged.
- `aggregate.round_means` in `report.json`: the panel mean of each round,
  in round order (one entry for a single run). With several rounds the
  report, the HTML page and the end-of-run summary add their range, e.g.
  `3 rounds: 5.33–6`, and the run history records them as `round_means`.
- Each reviewer in `report.json` (and `resolved-config.json`) carries
  `repeat`, the round its review belongs to (from 0); `resolved-config.json`
  also records `repeats`. `retry` redoes a failed review in the same round,
  with the seed it had.

### Removed
- `prebuttal key set --key KEY`: a key on the command line lands in shell
  history. `key set` asks with hidden input, or reads one line from stdin
  (`prebuttal key set gemini < keyfile`); environment variables still work.
- The names 0.6 kept as hidden aliases are gone, as their notices said. Each
  now stops with an error that names its replacement:
  - `run --seed`, `--effort`, `--figures`, `--reviewers`, `--out-dir`: set
    `seed`, `effort`, `figures`, the `[[reviewer]]` list or `[output] dir` in
    `prebuttal.toml`;
  - `run --json PATH`: `prebuttal show --json` after the run (with
    `--no-save`: `[output] formats = ["md", "html", "json"]`);
  - `prebuttal plan`: `prebuttal show --plan`;
  - `prebuttal venues show <name>`: `prebuttal venues <name>`;
  - `prebuttal runs --paper`: `prebuttal runs <project>`.

### Fixed
- A LaTeX source without its `.bbl` (an Overleaf download: `main.tex` and
  `refs.bib`) reached the reviewers with no references at all, so novelty,
  related work and baselines were judged without them. The cited entries of
  the `.bib` files the paper loads are now listed (all of them with
  `\nocite{*}`), in order of first citation; `check` and the review read
  the same files.
- `prebuttal diff` matched by wording after `prebuttal run --config
  prebuttal.toml`: `diff` has no `--config`, reads `./prebuttal.toml`, and
  found it "not trusted yet" because passing a file with `--config` trusted
  it for that run only. That trust is now remembered for the file's content,
  like a yes to the question.
- Two runs of one project archived at the same moment could be listed out
  of order (`#3` after `#4`) when their saves straddled a second: the run id
  (whose time orders the history) was taken before the history lock, the
  run number inside it. Both are now taken under the lock.
- An area chair that wrote LaTeX such as `\(O(n)\)` in its meta-review
  could lose the whole meta-review and revision plan while the run looked
  finished (and `prebuttal retry` saw nothing to redo): the JSON reader
  settled for the first revision-plan item. Since 0.6.1.
- More generally, an answer whose outer JSON object is broken (cut off at
  the token limit, an unescaped quote, a trailing comma) is no longer read
  as an object nested in it, nor as a small JSON example in the prose
  before it: the review or meta-review is repaired as intended instead of
  coming out empty and marked finished.
- A model answer with a lone `\ud800`-style escape no longer crashes the
  run at the very end, when the report is written.
- `prebuttal retry` started from another folder recorded that folder's seed
  in the run history and `resolved-config.json` instead of the run's own.
- `prebuttal check` found a required section written as a run-in heading
  (`Limitations.`, `Limitations:`), with roman numbering (`VI. Limitations`)
  or as `\paragraph{}` / `\subsubsection{}` only by reporting it missing,
  a desk-reject error.
- `prebuttal.toml` values of the wrong kind are config errors instead of
  silent surprises: `figures = "false"` read as true, `seed = true` as 1,
  `max_tokens = 2.5` as 2, and `retries = -1` made no attempt at all.
- LaTeX: a `longtable` outside a `table` float (the usual multi-page
  appendix table) was dropped without a warning, and a row with more cells
  than the header lost the extra ones: reviewers never saw those numbers.
  Both reach the pack now, as does `sidewaystable`; a longtable's head and
  foot repeated on every page count once.
- LaTeX: a `%` inside `verbatim`, `lstlisting` or `minted` was read as a
  comment (`95% (top-1)` became `95`); `\thanks{...}` ended up in the title;
  and the arguments of `\hspace`, `\includegraphics`, `\newcommand` and the
  like stayed in the text (`2em`, `fig.png`, `\setlength\tabcolsep{4pt}`);
  a table set as an image kept bits of `\includegraphics[...]`, its
  placement (`[htbp]`) and its caption twice.
- A review that is valid JSON but has no rating is asked for once more,
  then counts as a failed review, so `prebuttal retry` redoes it, instead
  of a finished one left out of the mean.
- After `prebuttal retry`, the `Change:` line and `prebuttal diff` compared
  the run with the incomplete one it completes (the same paper); they now
  use the run before, as the plan does. A retry of a retry whose AC failed
  replaces both, and a run whose AC left the plan empty is stepped over
  like one whose AC failed (the items `prebuttal check` adds do not count
  as the AC's plan). The dashboard's score change and trend line, the
  `trend` column of `prebuttal projects` and the `Next:` hint skip the
  completed run too. `prebuttal diff` against a run whose AC wrote
  no plan says so, rather than reading every earlier item as fixed.
- relay: a responder that paused mid-answer for longer than one poll had
  its half-written answer taken; a non-JSON answer now has to stay
  unchanged for 5 s.
- Scores of two venues on the same scale were compared: ICLR and ICML both
  rate out of 10, with other meanings. `prebuttal diff`, the `Change:` line,
  the dashboard and the `trend` of `prebuttal projects` now need one venue.
- `prebuttal retry` could merge reviews of different inputs into one report.
  Before any paid call it now refuses a `pack.md` whose hash differs from
  the one the report recorded, figure images missing or replaced (they used
  to be dropped silently, all of them), and a custom venue whose form text
  changed; reports record the figures' and the form's hashes from now on.
  It also runs with what the run recorded rather than the current folder's
  `prebuttal.toml`: the same `max_tokens` and `budget_chars`, a custom venue
  from the file the run used (found by its path, not only its name), and a
  custom agent only if its command is unchanged. An archive of a reviewer
  named `AC` (allowed before) can be retried. Only the custom agents it will
  run are checked, a damaged `resolved-config.json` or `pack.md` stops it
  with one line rather than being read as an old archive or a traceback, and
  a custom venue given by a relative path is found from any folder.
- A review with a score and no text (`{"rating": 8}`) counted as finished,
  and a list holding `null` was kept as the text `None`; such a review gets
  the repair pass, then counts as failed — on a form that requires text: a
  custom form whose text fields are all optional, or that has none, is
  complete with its scores. Reports name the required text fields a finished
  review left empty ("Left out by this reviewer: Questions"). A plan item whose
  issue is not text is dropped.
- A backend answering with something other than text (a list, an object)
  crashed `prebuttal diff` instead of falling back to matching by wording;
  it is a backend error now, wherever it happens.
- An area chair answer with the right key names and nothing in them
  (`{"meta_review": ""}`, `"action_plan": [null]`) counted as finished, so
  `retry` saw nothing to redo, and a null meta-review was kept as the text
  `None`; it gets the repair pass, then counts as failed.
- A provider reporting token usage as `null` or a string crashed the run
  after every review had finished, before anything was written; token
  counts of any type now read as a number or 0.
- A run whose title or note held a Unicode line separator (U+2028, U+0085)
  dropped out of the run history: the history file is now split on line
  feeds only.
- `prebuttal check` on LaTeX counted keys from any `.bib` in the folder; a
  key found only in a file the paper does not load prints as [?]. It now
  reads only the files named in `\bibliography{}` / `\addbibresource{}`, and
  the main file's `.bbl` only when none of them is there (an arXiv source):
  next to the `.bib`, a `.bbl` from an earlier build could hide a key the
  next build will not find. With neither, it warns that citations were not
  checked.
- `prebuttal check` on a PDF over the page limit with no References heading
  passed with the page count "skipped"; it now warns that the main text's
  end could not be found. A PDF that breaks while being read is a one-line
  error, not a traceback.
- A LaTeX project with `main.tex` (or `paper.tex`, …) at the root and
  another in a subfolder could be read from the subfolder's; the shallowest
  one wins, whatever its name among the usual ones. Only a file with
  `\documentclass` is taken for the paper when there is one (a `main.tex`
  that is a chapter of `manuscript.tex` is not), and a `.tex` that links
  outside the folder is not even opened to look for it.
- A PDF that opens but breaks while being read now stops with one line
  (`cannot read paper.pdf: …`) instead of a traceback.
- `prebuttal projects rename` onto a name used only by older run history
  merged two papers' runs; it is refused now. The registry and the history
  change under one lock, and a failed registry write undoes the history's;
  a run that was reviewing during the rename is archived under the new name.
- After `prebuttal rm` of a project's newest run, the next run took its
  number again, so an old `mamba#4` pointed at another report. The registry
  keeps the highest number given, also for projects registered before;
  numbers are never reused. A renamed project's old name is not given to
  another paper — automatically, by `--project` (which then means the renamed
  project) or by a rename — so a run still holding it lands in the right
  project.
- `prebuttal check` on a two-column PDF counted a page whose References start
  in the left column as main text when the right column began higher up.
- `prebuttal diff` of two runs with no reviewer in common (id · persona)
  said neither raised a weakness; it says they cannot be compared.
- A review field of the wrong type (an object as the summary) counted as
  text; a retry's archived settings of the wrong type are a damaged archive,
  not a reason to use the current ones, nor is a missing one (or one missing
  a field, or the settings of a custom agent it will run) in a run of 0.7.0
  or later; a `report.json` of the wrong shape (down to a reviewer's
  fields, their values and the plan items),
  and a custom venue's `rating` that is not a field name, are one-line
  errors instead of tracebacks.
- Writing fewer formats than the previous run left that run's `latest.json`
  (or `.html`) beside the new `latest.md`; it is removed.
- `prebuttal rm` reported a run deleted when its folder could not be (a file
  held open on Windows), and dropped it from the history, leaving no way to
  try again. A run is now listed until its files are gone, and `rm` says
  which are left. Files are deleted outside the history lock.
- The history lock is an operating-system file lock (`msvcrt` on Windows,
  `flock` elsewhere), released by the OS when its holder exits or crashes.
  It used to be a file judged stale after a minute, which a slow but live
  holder could lose to a second one, and a busy lock let some writers go on
  unlocked. Every write to the history and the project registry now holds
  it; archiving a finished run waits up to ten minutes for it.
- `prebuttal retry` could send a paper elsewhere than the run did: an
  archive recorded the backend, not where `OPENAI_BASE_URL` or the Ollama
  host pointed. Runs now record those endpoints, and a retry from a terminal
  where one points elsewhere stops before sending anything; a retry of a run
  archived before says where the paper would go and asks first. A retry
  also stops when `PREBUTTAL_BACKEND` names another backend than the run's
  (`relay` = no model from this shell): it keeps the run's backends, so it
  says to unset it or start a new run.
- The score trend of `prebuttal projects` and the dashboard's line joined
  versions rated by different panels (a reviewer on another model or
  effort, a missing round); a trend now covers only the latest versions one
  panel rated, and says "since #N" when it starts later than the first.
  `prebuttal diff` counts another effort as another reviewer too, and no
  longer checks such a change against run-to-run noise.
- A run whose reviews finished but whose report could be saved nowhere (the
  archive failed and `[output] dir = ""`) exited 0. It now prints the report
  and exits 7 — also when every reviewer failed but the area chair wrote.
- `prebuttal run --project NAME` archived under the paper's title when the
  project could not be registered; it keeps NAME and warns.
- `prebuttal projects rm` dropped a project from the registry while a run of
  it archived during the deletion was still listed; the project is kept,
  and `rm` says how many runs are left.
- Retries were counted differently by each view: two retries of one run
  were two versions in trends but one in `diff`, and a retry of v1 made after
  v2 plotted as the newest score. Trends, `diff`, the `Change:` line, the
  dashboard and the revision plan now share one rule: a run and all its
  retries are one version, the newest stands for it, and versions keep the
  order of their first run. A retry records that first run (`version` in the
  history), so deleting a retry in between keeps the others together, and
  the order holds even when that first run is deleted (a retry also keeps
  its number, for versions started within one second; retries archived
  before get both when that run is deleted). A retry of v1 follows
  no revision plan rather than v2's. The project's score (`prebuttal
  projects`, the dashboard, `--json`) is the newest version's, as its trend
  is; "last run" is still the most recent run.
- A score change between runs whose means average different ratings (a
  reviewer, or one round of it, failed in B, or gave its rating with another
  model) was checked against run-to-run noise; `diff`, the `Change:` line and the dashboard now say which ratings
  are in one run only, and give the change no direction.
- A report folder that already existed, empty, got no `.gitignore`; it does
  now. A folder that holds files is still left as it is.
- `prebuttal key set` / `unset` run under the store lock and replace the file
  atomically: two at once no longer drop a key, an interrupted write no
  longer leaves an empty file.
- A reviewer with `id = "AC"` took the area chair's effort and, in `retry`,
  its backend; the id is reserved now.
- A registry, plan-track file or model listing that is valid JSON of the
  wrong shape (`null`, a list) no longer crashes `projects`, the plan check
  or `prebuttal backends <name>`.
- The GitHub Action used in one job at two refs ran the first ref's version
  for both; each ref gets its own venv.
- `scripts/calibration/calibrate.py` refuses a `--venue` of another
  conference than `--venue-id` (a custom venue named after it, `iclr-2024`,
  counts), and an untrusted `prebuttal.toml` found in the current folder
  (pass it with `--config`). It now reviews as `prebuttal run` does, with
  each role's `effort` and `figures`.
- The dashboard's trend line joined scores of different venues; it now
  follows only the newest run's venue.
- A `prebuttal.toml` is trusted for the content its settings were parsed
  from, not the file as it is a moment later.
- Model listings and the project registry with a nested field of the wrong
  type (`supportedGenerationMethods: null`, `pricing: null`, `sources: null`)
  no longer crash.
- CI and the release workflow check the built wheel from outside the source
  tree, so a file missing from the wheel is no longer hidden by the checkout.
- `budget_chars` is described as what it is, a target for the paper text:
  tables are kept whole, so the pack can be longer. `--dry-run` says when it
  is, and that with `compress` its size is the one before summaries.

## [0.6.1] — 2026-11-09

### Added
- `report.json` carries `"schema": 1`, the layout version (bumped only when
  a field changes meaning or goes away), and each revision-plan item an `id`
  (`P1`, `P2`, ... in plan order), so later tools can refer to an item of an
  archived run.

### Fixed
- `prebuttal check` on a LaTeX project missed section headings that contained
  nested braces (`\section{\textbf{Limitations}}`, `\section{Limitations\label{...}}`,
  `\section[Short]{...}`) or macros (`\section{NeurIPS Paper \checklist}`),
  which could false-flag a missing required section. Headings (`\section`,
  `\subsection`, `\chapter`) are now read with balanced braces and stripped of
  formatting commands, `\label` and `\footnote`.
- Setting `GOOGLE_API_KEY` (without `GEMINI_API_KEY`) was accepted by the
  Gemini provider, but `prebuttal backends` and `auto` mode only checked
  `GEMINI_API_KEY` and reported `api-gemini` as unavailable.
- A custom `[agents.<name>]` backend recorded a configured `model` in the
  report and plan even though custom agent commands do not receive `--model`.
  It now records no model (`CLI default`), and `--dry-run` notes that the
  model flag belongs in `command`.
- `prebuttal diff` with one argument no longer raises `StopIteration` if the
  target run was deleted from the history between resolving it and looking up
  the run before it.
- A rating like 4.5 on an integer-only scale rounded to even (4.5 → 4 but
  5.5 → 6); it now rounds half up (4.5 → 5, 3.5 → 4) — the report's rating
  bar rounds the same way.
- A model rating written as a many-digit number (`"999…9"` as a string, or a
  400-digit integer in the JSON) no longer fails that reviewer with an
  overflow; it is treated as no parseable rating.
- Reading review JSON from a model response that contains thousands of braces
  (e.g. echoed LaTeX tables or malformed output) no longer stalls for several
  seconds per reviewer.
- `prebuttal diff` between two runs at venues with different rating scales now
  labels each run with its own scale and omits raw-mean deltas across scales.
- `prebuttal key set <backend>` without `--key` now reads a line from `stdin`
  when `stdin` is not a terminal (including `< NUL` on Windows, which is now
  treated as non-interactive across all prompts) and exits with an error if
  empty instead of blocking on `getpass`.
- A review whose JSON wrote LaTeX inside a string (`\(O(n)\)`, `\cite{x}`)
  was an invalid JSON escape, so that reviewer failed even after the repair
  pass. Such backslashes are now read as written.

## [0.6.0] — 2026-11-03

A smaller CLI: 13 commands, and `run` keeps only what changes from run to
run (9 flags, was 15).

### Added

- **A guide on the website** ([/guide/](https://guoyukai-samuel.github.io/prebuttal/guide/)):
  every command and setting, task by task. Its command reference and settings
  table are generated from the CLI and the sample config, and a test fails when
  they fall behind. The README is shorter and links to it.
- **A submission checklist page per built-in venue** (NeurIPS, ICLR, ICML, ARR,
  CVPR), generated from the rules `prebuttal check` applies and the venue's
  review form, and a CVPR sample report (LLaVA-1.5 on the CVPR form).
- The site has canonical links, Open Graph previews, a favicon, structured data
  and a sitemap.
- **`run` puts the desk-reject check into the revision plan.** On your own
  draft, each error `prebuttal check` finds is now the first `must` of the
  plan and each warning a `should`, marked `raised_by: ["check"]`, so they
  lead "Fix first" and `prebuttal diff` shows them gone once fixed. They used
  to appear only as a note above the report. The area chair is told the
  findings, as facts kept apart from the paper's text.

### Changed
- `run --seed`, `--effort`, `--figures`, `--reviewers` and `--out-dir` are
  hidden: they repeat `prebuttal.toml` settings (`seed`, `effort`,
  `figures`, one `[[reviewer]]` block per reviewer, `[output] dir`) that
  usually hold for a whole paper. `run --json PATH` is hidden too: use
  `prebuttal show --json` after the run, or, with `--no-save`,
  `[output] formats = ["md", "html", "json"]`. They still work until 0.7,
  each with a notice naming its replacement.
- `prebuttal plan` is a hidden alias of `prebuttal show --plan` until 0.7.
- `prebuttal venues <name>` prints a venue's scores and review form, like
  `prebuttal backends <name>` lists a backend's models; `venues show
  <name>` is a hidden alias until 0.7. A custom venue can't be called
  `new` or `show`.
- `prebuttal runs --paper` is hidden until 0.7: projects are named after
  the paper, so `prebuttal runs <project>` finds its runs. It was never
  documented.

### Removed
- The 0.4 aliases, as their notices said: `prebuttal open`, `export`,
  `dashboard`, `models`, `key status`, and `run --format` / `--stdout`.
  Each now fails with the command to use instead (`show --open`,
  `show -o FILE`, `projects --open`, `backends <name>`, `backends`,
  `[output] formats`, `show`).

### Fixed
- Auto mode picked an agent CLI because it was installed, signed in or
  not: a signed-out or expired `claude` came first and failed every review.
  Detection now asks `claude auth status` / `codex login status` (no model
  call, run with the same environment as a review) and skips a CLI that
  says it is signed out; `prebuttal backends` shows the command that signs
  it in. A CLI too old to have the command, or one that doesn't answer,
  counts as signed in, as before.
- Ollama's default model was the first one it listed, which can be an
  embedding model (`nomic-embed-text`, `bge-m3`) that can't write a
  review. Embedding models are now skipped — by name and family, and by the
  capabilities newer Ollama versions report — and Ollama with only
  embedding models installed is not offered as a backend.
- On Windows, an agent CLI (or a process it left running) can still hold
  its empty temp folder when the call returns; failing to delete it threw
  away the finished review (`PermissionError: [WinError 32]`). Cleanup now
  ignores a locked folder once the answer is in hand.

## [0.5.4] — 2026-11-01

### Added
- `prebuttal show --plan` prints a run's revision plan (`--json` for the
  items), so `show` is the one way to look at a run. `prebuttal plan` still
  works; 0.6 turns it into a hidden alias.

### Fixed
- Re-downloading Overleaf's source made a new project each time: the
  browser saves the second copy as `paper (1).zip` (or `paper(2).pdf`), a
  different path. A download-copy suffix is now ignored, so the run joins
  the paper's project and `diff` compares it with the last version. A
  project already registered under such a name keeps its runs.
- A PDF's abstract was read for at most 24 lines, so a two-column abstract
  was cut mid-sentence; it could also pick up the page-1 footnotes (author
  contributions, the venue line). It now runs to the first heading or page
  break, skipping footnotes (even one between two of its lines in a column)
  and a figure's labels or the arXiv stamp before it. Checked on eight
  arXiv papers, one and two columns.
- White text in LaTeX was only caught on one line and without nested
  commands: `\textcolor{white}{...}` spanning lines or holding `\textbf`
  slipped through `check` and the hidden-text warning. Groups are now read
  across lines, and white given as `[rgb]{1,1,1}`, `[RGB]{255,255,255}`,
  `[gray]{1}` or `[HTML]{FFFFFF}` counts too.
- HTML reports and share pages showed the area chair's meta-review as raw
  markdown (`## Summary`, `**...**`) in one run-on paragraph. Headings,
  lists, bold, italics and code now render (everything still escaped, no
  links), and a long meta-review is cut at a line break, not inside `**`.
  Bullets under a numbered point nest inside it, and numbering carries on
  after them or after a blank line. The site's sample reports are
  re-rendered. A run's archived `report.html` is not rewritten; delete it
  and `prebuttal show --open` renders it again from `report.json`.

## [0.5.3] — 2026-11-01

### Added
- **CVPR** as a built-in venue (`--venue cvpr`), for the CVPR 2027 deadline
  (16 November 2026). The recommendation scale (Reject → Strong accept, 1–5)
  and the fields follow the official reviewer training material, since CVPR
  does not publish its OpenReview form. `check` holds a paper to the 2027
  author guidelines: 8 pages, the LLM Usage Statement required (it and the
  references may run past the limit), and `\usepackage{cvpr}` without
  `[review]` flagged as a camera-ready build.
- **A GitHub Action** for `prebuttal check` (`uses:
  GuoYuKai-SaMuEl/prebuttal@v0.5.3`): runs on every push to a paper's
  repository, needs no secrets, fails the job on desk-reject problems, and
  shows every finding as an annotation plus the full check in the job
  summary. Outside the Action, `check` writes the annotations whenever it
  runs on GitHub Actions.
- **A LaTeX project as a .zip** — Overleaf's Menu → Download → Source — for
  `run` and `check` alike, flat or with one top folder. It is unpacked into
  a temporary folder that is removed afterwards, and never trusted: members
  that would land outside it are refused, symlinks skipped, and the unpacked
  size capped at 512 MB while writing.

### Documentation
- One-page Simplified and Traditional Chinese READMEs
  (`README.zh-CN.md`, `README.zh-TW.md`) and landing pages (`/zh-cn/`,
  `/zh-tw/`), linked from the English ones; the English README remains the
  full reference. The README and site now describe CVPR, the GitHub Action
  and .zip sources.

### Changed
- A custom venue named `cvpr` now has to be renamed (e.g. `cvpr-lab.toml`):
  built-in names can't be shadowed. Archived reports of such a venue still
  render with their own stored fields; `retry` of such a run says the name is
  now built in, since the run's review form was the old custom file.

## [0.5.2] — 2026-10-31

### Fixed
- LaTeX: a comment after a line break (`\\% ...`, common at the end of
  table rows) was kept as text and leaked into the last cell; only an
  escaped `\%` is a percent sign now.
- The area chair gets the same one JSON-repair pass as the reviewers: a
  meta-review wrapped in prose no longer loses the whole revision plan.
- `prebuttal retry` interrupted with Ctrl-C saves the reviewers that
  finished this time (marked "interrupted"), like `prebuttal run` does.
- `--effort` with an older Claude API model (Sonnet / Haiku 4.5, Claude 3)
  is no longer sent: those models answer it with an HTTP 400.
- `note`, `rm` and `projects rename|rm` stop with "the run history is busy"
  instead of rewriting it without the lock; the project registry now takes
  the same lock, so two runs of different papers finishing together both
  stay registered.
- `compress = true`: the section summaries' token usage counts in the
  report's total, and the dry run says those calls are not in its estimate.
- `retry` with only the AC to re-run says so instead of "reviewers none".
- A reviewer that crashed or a role cut off by Ctrl-C was archived without
  its `--effort`, so `retry` re-ran it at the model's default effort.

## [0.5.1] — 2026-10-29

### Changed
- Internal: dead code removed (`BackendStatus.line()`, `EFFORTS`), the
  CLI command dispatch folded into one table (with `run` listed explicitly),
  and small duplicated helpers merged (key-file serialisation and its 0600
  write path, words-in-box filter, heading-word table). No behavior change.
- Internal, second pass (−163 lines): the API providers share one constructor
  and one backend/key table, CLI errors go through one helper, `retry`
  reuses the orchestrator's report assembly. Reports and CLI output are
  byte-identical before and after.

### Fixed
- `check` page counting: a lone centred "References" heading (ACL-style
  single-column papers) no longer reads the reference entries below it as
  main text; lines to the heading's left now count only on a page with a
  real second column.
- Two `prebuttal run` processes finishing at the same moment on one project
  no longer get the same run number: history numbering takes a brief
  cross-process lock (best-effort: a stale or busy lock never blocks
  archiving a finished run).  On Windows a lock file being deleted that
  instant read as PermissionError and could skip archiving entirely — both
  are now treated as "busy" and retried.
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

[Unreleased]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.5.4...v0.6.0
[0.5.4]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.5.3...v0.5.4
[0.5.3]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/GuoYuKai-SaMuEl/prebuttal/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/GuoYuKai-SaMuEl/prebuttal/releases/tag/v0.1.0
