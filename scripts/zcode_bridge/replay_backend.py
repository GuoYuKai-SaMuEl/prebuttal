#!/usr/bin/env python3
"""Replay backend: answers prompts from pre-generated answer files.

Registered as a custom agent backend ([agents.zcode]) so the real CLI pipeline
runs end-to-end while ZCode subagents act as the reviewer models. Classifies
the incoming prompt by persona keyword and prints the matching answer.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    prompt = sys.stdin.read()
    answers = Path(sys.argv[1])
    if "estimated_rating" in prompt:
        key = "ac"
    elif "Reviewer 2" in prompt:
        key = "adversarial"
    elif "detail-obsessed" in prompt:
        key = "detail"
    else:
        key = "senior"
    path = answers / f"{key}.txt"
    sys.stdout.write(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
