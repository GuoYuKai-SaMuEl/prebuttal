"""Relay backend: the CLI spools prompts to files; anyone answers them.

This turns Prebuttal into an open protocol while keeping orchestration in the
CLI (parallel fan-out, parsing, aggregation, seeds).  The responder behind a
request can be:

- a human (expert as one reviewer, or a zero-install manual mode),
- the host agent's subagents (see SKILL.md "Relay mode") — reviewers with
  fully independent contexts and zero API keys,
- any external system watching the spool directory.

Protocol: for every ``<stem>.req.md`` write ONLY the requested JSON object to
``<stem>.ans.md``.  The CLI polls and continues automatically.
"""

from __future__ import annotations

import itertools
import json
import os
import time
from pathlib import Path

from ..models import Usage
from .base import BaseProvider, ProviderError

_SEQ = itertools.count(1)

README_TXT = """\
Prebuttal relay spool
====================
For every *.req.md file here:
  1. Read it — it contains a complete reviewer prompt (persona + venue review
     form + JSON schema + the submission itself).
  2. Produce the review and write ONLY the JSON object to the matching
     <stem>.ans.md file (same stem, .ans.md instead of .req.md).

The CLI polls this directory and continues automatically when answers appear.
Responders can be a human, host-agent subagents, or any external system.
Timeouts and the spool location are configurable via [relay] in prebuttal.toml.
"""

_PROTOCOL_NOTE = """

---
[relay protocol] This file is a review request. Write your answer — ONLY the
JSON object the instructions above ask for — to the file: {ans_name}
"""


def _is_json_object(text: str) -> bool:
    try:
        return isinstance(json.loads(text), dict)
    except ValueError:
        return False


def _classify(prompt: str) -> str:
    if "estimated_rating" in prompt:
        return "ac"
    if "roast master" in prompt:
        return "roast"
    if "Reviewer 2" in prompt:
        return "adversarial"
    if "detail-obsessed" in prompt:
        return "detail"
    return "senior"


class RelayProvider(BaseProvider):
    kind = "relay"

    def __init__(
        self,
        backend: str = "relay",
        model: str = "",
        *,
        spool_dir: str | Path = "relay",
        timeout_s: float = 1800.0,
        poll_s: float = 1.0,
        **kw,
    ):
        super().__init__(backend, model, timeout_s=timeout_s, **kw)
        self.spool = Path(spool_dir)
        self.poll_s = poll_s
        self.spool.mkdir(parents=True, exist_ok=True)
        readme = self.spool / "README.txt"
        if not readme.exists():
            readme.write_text(README_TXT, encoding="utf-8")
        # the spool holds full paper text: never let it be committed by accident
        ignore = self.spool / ".gitignore"
        if not ignore.exists():
            ignore.write_text(
                "# prebuttal relay spool (contains paper text)\n*\n", encoding="utf-8"
            )

    def _complete(self, *, system, user, temperature, seed, max_tokens) -> tuple[str, Usage]:
        # pid keeps stems unique even when two prebuttal processes share one spool dir
        stem = f"{_classify(system + chr(10) + user)}-{os.getpid()}-{next(_SEQ)}"
        req = self.spool / f"{stem}.req.md"
        ans = self.spool / f"{stem}.ans.md"
        req.write_text(
            system + "\n\n---\n\n" + user + _PROTOCOL_NOTE.format(ans_name=ans.name),
            encoding="utf-8",
        )
        deadline = time.monotonic() + self.timeout_s
        prev: str | None = None
        while time.monotonic() < deadline:
            if ans.is_file():
                text = ans.read_text(encoding="utf-8", errors="replace")
                # A responder may still be writing: take the answer once it is a
                # complete JSON object, or once it stopped changing between polls.
                if text.strip() and (text == prev or _is_json_object(text)):
                    return text, Usage()
                prev = text
            time.sleep(self.poll_s)
        raise ProviderError(
            f"relay: no answer for {req.name} within {self.timeout_s:.0f}s — "
            f"write the JSON review to {ans}"
        )
