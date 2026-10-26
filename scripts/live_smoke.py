"""Live smoke test of the API backends with real keys and the cheapest models.

Runs one reviewer + the area chair on the bundled demo paper for every backend
whose key is set, once with default settings and once with ``--effort low``
(the code paths that only a real API can confirm: request shape, reasoning
parameters, token limits, JSON parsing).  Nothing is archived.

    ANTHROPIC_API_KEY=... OPENAI_API_KEY=... python scripts/live_smoke.py
    python scripts/live_smoke.py api-openai          # just one backend

With a network secret (the proxy injects the real key), set the variable to
any placeholder, e.g. OPENAI_API_KEY=injected, so the backend is enabled.

Costs a few cents per backend.  Exit code 0 only if every attempted run passed.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from prebuttal import cli

PAPER = REPO / "tests" / "fixtures" / "demo-paper.pdf"

# (backend, key variable, model, extra flags) — a cheap current model per family
CASES = [
    ("api-anthropic", "ANTHROPIC_API_KEY", "claude-haiku-5-5", []),
    ("api-anthropic", "ANTHROPIC_API_KEY", "claude-haiku-5-5", ["--effort", "low"]),
    ("api-openai", "OPENAI_API_KEY", "gpt-6-luna", []),
    ("api-openai", "OPENAI_API_KEY", "gpt-6-luna", ["--effort", "low"]),
    ("api-gemini", "GEMINI_API_KEY", "gemini-3.5-flash-lite", []),
    ("api-gemini", "GEMINI_API_KEY", "gemini-3.5-flash-lite", ["--effort", "low"]),
    ("api-openrouter", "OPENROUTER_API_KEY", "", []),  # default :free model
]


def run_case(backend: str, model: str, extra: list[str]) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.json"
        argv = ["run", str(PAPER), "--backend", backend, "--reviewers", "1", "--no-save",
                "--out-dir", str(Path(tmp) / "reports"), "--json", str(out), *extra]  # fmt: skip
        if model:
            argv += ["--model", model]
        rc = cli.main(argv)
        if rc != 0 or not out.is_file():
            return False, f"exit code {rc}"
        data = json.loads(out.read_text(encoding="utf-8"))
        rev, meta = data["reviewers"][0], data["meta"]
        if not rev.get("parse_ok") or rev.get("rating") is None:
            return False, f"reviewer output not parsed: {rev.get('error')}"
        if meta.get("estimated_rating") is None:
            return False, "area chair gave no rating"
        usage = data.get("usage_total", {})
        return True, (
            f"rating {rev['rating']:g}, AC {meta['estimated_rating']:g}, "
            f"{usage.get('prompt_tokens', 0):,} in / {usage.get('completion_tokens', 0):,} out, "
            f"model {rev.get('model')}"
        )


def main() -> int:
    only = set(sys.argv[1:])
    results = []
    for backend, var, model, extra in CASES:
        if only and backend not in only:
            continue
        label = f"{backend} {model or '(default)'} {' '.join(extra)}".strip()
        if not os.environ.get(var):
            results.append((label, None, f"skipped: {var} not set"))
            continue
        print(f"\n=== {label}", flush=True)
        try:
            ok, detail = run_case(backend, model, extra)
        except Exception as e:  # report and continue with the next backend
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append((label, ok, detail))
    print("\n--- live smoke summary")
    for label, ok, detail in results:
        mark = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        print(f"{mark}  {label}: {detail}")
    tried = [ok for _l, ok, _d in results if ok is not None]
    return 0 if tried and all(tried) else 1


if __name__ == "__main__":
    sys.exit(main())
