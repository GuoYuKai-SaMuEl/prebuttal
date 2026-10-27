# Roadmap

Tentative — priorities shift with usage and feedback. Versioning while
pre-1.0: **patch** releases are fixes and small additions; **minor** releases
are substantial new features. Every item below has to respect the
[design commitments](CONTRIBUTING.md#design-commitments-dont-break-these-in-a-pr),
in particular *fewer parameters, simpler commands*.

## Released

- **0.2** — the core: ingestion (PDF / LaTeX / arXiv), real venue forms,
  three independent reviewers + an area chair, every backend (agent CLIs,
  APIs, Ollama, relay), reports + JSON + share page, projects and run history.
- **0.3** — custom venues (any review form as a TOML file) and the revision
  plan, checked against the next run by `prebuttal diff`.
- **0.4** — robustness: `prebuttal retry`, partial runs saved on Ctrl-C,
  hidden-text / prompt-injection warnings, `diff --llm`, a trust gate for
  discovered configs, figures for vision backends; 0.4.1 hardened relay,
  LaTeX ingestion, agent-CLI arguments and key storage.
- **0.5** — nothing leaks before submission: `prebuttal check`, agent CLIs
  without any tool that reads files, and `backends` as the one setup view.
  Details below, kept as the record of what was planned.

## 0.5 — nothing leaks before submission (released)

The paper must not leak its authors; the tool must not leak your keys.

- **`prebuttal check <paper>`** — a deterministic desk-reject pre-flight, no
  LLM, no cost, `--venue` as for `run`:
  - *anonymity*: PDF author metadata, acknowledgements, personal GitHub /
    homepage links, self-revealing citations ("our previous work [12]");
  - *format*: page limit and required sections per venue (NeurIPS checklist,
    limitations, broader impact) — added as rules to the venue forms;
  - *leftovers*: unresolved `??` references, `[?]` citations, TODO comments.
  
  `run` performs the same check first and puts its findings at the top of
  the report, like the hidden-text warning.
- **Agent CLIs can't read stored API keys.** Isolation, not output
  detection (a prompted model can encode a key past any filter). Starts with
  a written threat model: `claude` already runs with no tools; the exposure
  is codex's read-only sandbox and custom agents, and an OS keyring alone
  does not stop a same-user process.
- **A smaller CLI.** Today there are 17 top-level commands, and three of
  them answer one question — *what can I run with?* (`backends`, `models`,
  `key status`). Tools in this space fold that into a single status view
  (`gh auth status`, `llm models` listing every provider's models). Plan:
  - `prebuttal backends` becomes the one setup view: per backend, whether
    it's available, where its auth comes from (CLI login / env / stored key),
    and the default model; `prebuttal backends <name>` lists that backend's
    models. `models` and `key status` become hidden aliases for one minor
    version, then go.
  - `key set` / `key unset` stay (like `llm keys set`, `gh auth login`):
    writing a secret deserves its own explicit verb.
  - Review the run-history commands (`runs`, `projects`, `show`, `plan`,
    `open`, `export`, `note`, `rm`) the same way; candidates are `plan` as a
    section of `show` and `projects` folded into `runs`. Merge only where
    the result is simpler, not just shorter.

Done when: `check` raises no false alarms on the sample papers and catches
every planted problem in deliberately broken ones; the key threat model is
written down with tests; the command list is shorter with no lost function.

Outcome: as planned, except the run-history commands, which stayed — each
does one job, and every merge tried needed a new flag or an overloaded
argument. `models` and `key status` are hidden aliases until 0.6. `check`
got one option after all, `--venue`: most users have no `prebuttal.toml`,
and checking a paper against the wrong venue's rules is worse than a flag.

## 0.6 — a revision loop you can trust

The Mamba demo showed that single-run score changes are mostly noise and
that word-overlap matching misleads.

- **Repeated reviews**: `repeats = 3` in `prebuttal.toml` (a setting, not a
  flag); the report shows the mean and the run-to-run range.
- **Noise-aware diff**: when a change is smaller than the measured
  run-to-run variation, `diff` says it can't be told apart from noise.
- **Meaning-based diff by default** whenever an AC backend is available,
  word overlap only as the offline fallback — `--llm` can then go.
- **Plan tracking across versions**: each revision-plan item marked
  resolved / raised again across v1 → v2 → v3 of a project, on the dashboard.

Done when: on Mamba v1 → v2 the tool itself reports "no measurable change".

## 0.7 — reach

- More venue forms (CVPR, AAAI, ARR, TMLR, COLM, KDD), each linked to its
  official source; community personas.
- A GitHub Action — CI for papers: `prebuttal check` on every push to a
  LaTeX repo, an optional full review with the user's own secrets.
- Maybe: a browser-only quick scan on GitHub Pages (drop a PDF, bring your
  own key, no server — we stay a non-custodian). Only if usage asks for it.

## Separate track: calibration

How simulated scores relate to real OpenReview outcomes. Kept apart from
the core and started after 0.6, because without repeated reviews there is
no variance to compare against. Reads public OpenReview data only. Could
grow into a public benchmark.

## 1.0

The CLI, `prebuttal.toml` and `report.json` schemas frozen and versioned,
with migration notes for any later break; tested on Windows, macOS and
Linux in CI; at least one round of feedback from outside users.

## Not planned

- **Rebuttal drafting** (reviews → response letter): outside the product's
  purpose, a pre-submission stress test, and it gains nothing from
  independent reviewers.
- **Submitting to OpenReview** on the user's behalf: irreversible and
  outward-facing; reading public reviews for calibration is enough.
