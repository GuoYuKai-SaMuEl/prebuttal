---
name: prebuttal
description: >-
  Pre-submission AI review stress test for machine-learning papers. Use when the
  user mentions paper review, peer review, referee report, simulate review,
  review my paper, prebuttal, reviewer 2, NeurIPS / ICLR / ICML / ACL review,
  paper feedback, or wants to know how reviewers will judge their submission
  before the conference deadline.
---

# Prebuttal — simulated conference review

Prebuttal runs a paper through three independent AI reviewers (isolated
contexts, optionally different models) plus an area chair, and produces a real
conference-format review report. Orchestration lives in the `prebuttal` CLI —
do NOT role-play the reviewers yourself in this chat: shared-context
role-play produces bland, converged "persona collapse" reviews, which is
exactly what this tool exists to avoid.

## When this skill applies

- "Review my paper / draft / preprint"
- "What would reviewers say about this?"
- "Simulate a NeurIPS/ICLR/ICML/ACL review"
- "Give me a referee report before I submit"
- "Am I ready for the rebuttal / submission deadline?"

## How to run it

1. Check the CLI is installed: `prebuttal --version`.
   If missing: `pip install prebuttal` (or `pipx install prebuttal`; `uvx prebuttal ...` for a one-shot run).
2. Identify the paper source and target venue:
   - source: a PDF path, a LaTeX project directory, or an arXiv link/id
   - venue: `neurips` | `iclr` | `icml` | `acl` (ask if unclear; default neurips).
     Other venues: `prebuttal venues` lists custom ones; `prebuttal venues new <name>`
     writes a template the user fills with the venue's form and scale.
3. Run:

   ```bash
   prebuttal run <paper> --venue <venue> --json prebuttal-report.json
   ```

   The JSON output is the source of truth for interpreting results. The
   human-readable report (Markdown + HTML) lands in its own folder under
   `prebuttal-reports/<project>/`; the CLI prints the paths.
4. If the user has no API keys: Prebuttal auto-detects subscription CLIs
   (`claude -p`, `codex exec`) and local Ollama — zero-key paths. Check
   `prebuttal backends`. For unpublished work, suggest Ollama (nothing leaves
   the machine). Use `--dry-run` first if the user asks about cost.
5. Leave `--effort` unset (each model's default) unless the user asks for a
   deeper or a cheaper/faster review: `--effort high` or `--effort low`.

## Before submitting: `prebuttal check`

When the user is about to submit ("is my paper ready?", "check anonymity",
"am I over the page limit?"), run `prebuttal check <paper> --venue <venue>` — no model, no
cost, seconds. It checks anonymity, the venue's page limit and required
sections (NeurIPS checklist, ICML impact statement, ARR limitations), and
leftovers (`??`, `[?]`, TODO, hidden text). Exit code 6 = something can get
the paper desk-rejected; present those `[x]` lines first, then the `[!]`
warnings. Check the PDF they will upload (a LaTeX folder is checked without
compiling, so it can't count pages). Pass the same `--venue` as for `run`
(without it: `prebuttal.toml`, else neurips); limits change yearly, so tell the user to confirm against
this year's call. `prebuttal run` includes the same findings in the report's
notes.

## Relay mode (zero API key, zero CLI install)

When the user has no API key and no agent CLI, the reviewers can be YOUR OWN
subagents — the CLI still orchestrates (persona prompts, venue forms, parsing,
aggregation) but dispatches through a file protocol:

1. Start the run in the background — it blocks until every answer exists, so
   a foreground run deadlocks you (you can't write answers while waiting):
   `prebuttal run <paper> --venue <venue> --backend relay --json out.json`
   If your environment should always work this way, set
   `PREBUTTAL_BACKEND=relay` once instead of passing `--backend relay` each
   time (an explicit `--backend` flag still overrides it). Relay is never
   picked automatically; the CLI's "running inside <agent>" hint is just a
   reminder that this mode exists.
2. Watch the spool directory (default `relay/`). For every `<stem>.req.md`
   that has no matching `<stem>.ans.md`: read it, spawn ONE subagent whose
   entire instructions are that file's content, and have the subagent return
   ONLY the JSON object; write that JSON to `<stem>.ans.md.tmp`, then
   rename it to `<stem>.ans.md` (an atomic rename: the CLI never sees a
   half-written answer).
3. The CLI picks up answers automatically and produces the report. Never let
   one subagent answer two requests, and never answer them in your own context
   — independence is the point.

Human-in-the-loop works the same way: a human can fill the `.ans.md` files.

## Revision loop (run history & diffing)

Every run is archived automatically (`~/.prebuttal`; `--no-save` to skip).
After the user revises the paper:

1. Re-run with the same `--venue` and `--seed` so results are comparable, and
   label the revision: `--note "what changed"`. The same paper source lands
   in the same project automatically.
2. `prebuttal diff` — the newest run vs the one before it in the same project:
   score deltas per reviewer plus weakness movement (gone / persists / new,
   heuristic word-overlap matching), and the previous run's revision plan
   checked against the new run (not re-detected / still raised / new).
   Matching is by wording: before calling a "gone" or "not re-detected" item
   fixed, check it is not simply reworded among the "new" ones — or run
   `prebuttal diff --llm`, which matches plan items by meaning with one model
   call. Present real fixes as wins and the rest as the user's TODO. A score
   that moves by about a point between single runs may be noise, not the
   revision: say so rather than celebrating it.
3. `prebuttal runs <project>` lists a paper's runs; reference one as
   `<project>#3`, `<project>~1` (one before the newest) or by id prefix.
   `prebuttal projects` lists every paper.

## Interpreting `--json`

- `aggregate.mean / rating_scale` — predicted rating (e.g. `5.2 / 10`)
- `aggregate.std`, `aggregate.min`/`max` — reviewer disagreement; high σ means
  the paper is polarizing: show both the positive and negative case to the user
- `reviewers[].fields` — venue-form answers (summary, strengths, weaknesses,
  questions, limitations, ...); `rating`/`confidence` are scores
- `reviewers[].backend` / `model` — which backend produced each review (always
  disclose this to the user)
- `meta.meta_review` — the area chair's synthesis and recommendation
- `meta.action_plan[]` — the revision plan, most important first: `priority`
  (must / should / could), `issue`, `action`, `raised_by` (reviewer ids),
  `effort` (small / medium / large). `prebuttal plan` prints it as a checklist.

## Presenting results to the user

1. Lead with the aggregate score and disagreement.
2. Walk through the revision plan (`meta.action_plan`), "must" items first —
   items raised by ≥2 reviewers are the real risks — each with its citation
   to a table/section and the suggested action.
3. Pull out the questions reviewers would ask in rebuttal.
4. Give the AC recommendation verbatim.
5. If a reviewer failed (exit code 4, e.g. an overloaded backend), offer
   `prebuttal retry`: it re-runs only the failed reviewers and the AC on the
   same text, so the finished reviews are not paid for twice.
6. Offer next steps: fix specific weaknesses, re-run after revision with the
   same `--seed` to compare, or open the HTML report (`prebuttal open`) /
   the overview of every run (`prebuttal dashboard`).

## Honesty rules

- Always say these are simulated reviews (a stress test), not predictions.
- Always name the models/backends that produced each review.
- Never auto-post anything to OpenReview or email; the user decides what to do
  with the report.
