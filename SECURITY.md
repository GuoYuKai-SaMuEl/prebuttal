# Security Policy

## Supported versions

Prebuttal is pre-1.0. Security fixes land on `main` and ship in the next
patch release; there are no backports to older branches yet.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅ (main)  |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use [GitHub's private vulnerability reporting](https://github.com/GuoYuKai-SaMuEl/prebuttal/security/advisories/new)
(enable it in repo Settings → Code security if it is not yet active), or
message the maintainer privately on GitHub. You will get an acknowledgement
within 72 hours. Please include reproduction steps and impact; we will
coordinate a fix and credit you in the release notes unless you prefer
to remain anonymous.

## Security model — what this tool does by design

Know what is intentional behavior before reporting it:

- **Papers leave your machine** when an API/agent-CLI backend is used — that
  is the product. For unpublished work use the `ollama` backend (local) or
  `relay` (you control the responder).
- **Subprocess execution**: configured backends run as subprocesses
  (`claude`, `codex`, or your own `[agents.<name>]` command). Commands come
  from *your own* `prebuttal.toml` or our built-in defaults — never from the
  paper being reviewed. Do not point `[agents.*]` at untrusted configs.
- **No telemetry.** Prebuttal makes network calls only to the backend you
  configured and (for arXiv input) to arxiv.org to download the paper.
- **API keys** stay in environment variables or `~/.prebuttal/keys.env`
  (user-only file created by `prebuttal key set`); they are never written to
  reports, JSON output, or share pages. Remove a stored key with
  `prebuttal key unset <name>` or by deleting the file.

## Scope

In scope: anything in this repository that could lead to code execution,
data exfiltration beyond the configured backend, or key leakage.
Out of scope: the quality of simulated reviews, and vulnerabilities in the
upstream backends themselves (report those upstream).
