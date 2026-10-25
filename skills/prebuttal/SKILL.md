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
   - venue: `neurips` | `iclr` | `icml` | `acl` (ask if unclear; default neurips)
3. Run:

   ```bash
   prebuttal run <paper> --venue <venue> --json prebuttal-report.json --share
   ```

   The JSON output is the source of truth for interpreting results.
4. If the user has no API keys: Prebuttal auto-detects subscription CLIs
   (`claude -p`, `codex exec`) and local Ollama — zero-key paths. Check
   `prebuttal backends`. For unpublished work, suggest Ollama (nothing leaves
   the machine). Use `--dry-run` first if the user asks about cost.

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
   ONLY the JSON object; write that JSON to `<stem>.ans.md`.
3. The CLI picks up answers automatically and produces the report. Never let
   one subagent answer two requests, and never answer them in your own context
   — independence is the point.

Human-in-the-loop works the same way: a human can fill the `.ans.md` files.

## Revision loop (run history & diffing)

Every run is archived automatically (`~/.prebuttal`; `--no-save` to skip).
After the user revises the paper:

1. Re-run with the same `--venue` and `--seed` so results are comparable.
2. `prebuttal runs` — list archived runs (id prefix is enough to reference one).
3. `prebuttal diff <old-run-id> <new-run-id>` — score deltas per reviewer plus
   weakness movement (gone / persists / new, heuristic word-overlap matching).
   Present the "gone" list as wins and "persists" as the user's TODO.

## Interpreting `--json`

- `aggregate.mean / rating_scale` — predicted rating (e.g. `5.2 / 10`)
- `aggregate.std`, `aggregate.min`/`max` — reviewer disagreement; high σ means
  the paper is polarizing: show both the positive and negative case to the user
- `reviewers[].fields` — venue-form answers (summary, strengths, weaknesses,
  questions, limitations, ...); `rating`/`confidence` are scores
- `reviewers[].backend` / `model` — which backend produced each review (always
  disclose this to the user)
- `meta.meta_review` — the area chair's synthesis and recommendation

## Presenting results to the user

1. Lead with the aggregate score and disagreement.
2. List the recurring weaknesses across reviewers (things ≥2 reviewers agree on
   are the real risks), each with its citation to a table/section.
3. Pull out the questions reviewers would ask in rebuttal.
4. Give the AC recommendation verbatim.
5. Offer next steps: fix specific weaknesses, re-run after revision with the
   same `--seed` to compare, or generate the shareable HTML page.

## Honesty rules

- Always say these are simulated reviews (a stress test), not predictions.
- Always name the models/backends that produced each review.
- Never auto-post anything to OpenReview or email; the user decides what to do
  with the report.
