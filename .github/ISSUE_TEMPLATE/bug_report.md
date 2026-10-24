---
name: Bug report
about: Something broke or reviewed wrong
labels: bug
---

**What happened?** A clear description of the problem.

**How to reproduce**

```bash
prebuttal run <paper> --venue <venue> <flags>
```

Steps, paper source (arXiv link is ideal — don't upload unpublished work to a
public issue!), and the `prebuttal.toml` you used (redact nothing needed —
keys live in env vars and never belong in the file).

**Environment**

- prebuttal version (`prebuttal --version`):
- OS + Python version:
- Backends involved (`prebuttal backends` output):

**Evidence** — the report Markdown or `--json` output (the interesting parts),
plus stderr from the run. If parsing failed, include the "Raw model output"
section of the report.

**Ingestion check** (if tables/sections came out wrong): does the paper use a
standard LaTeX class or a journal template? Are tables `tabular`/`booktabs`
or images?
