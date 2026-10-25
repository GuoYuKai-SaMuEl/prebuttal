import json
import threading
import time
from pathlib import Path

import pytest

from prebuttal import cli
from prebuttal.providers.base import ProviderError
from prebuttal.providers.relay import RelayProvider

ANSWER = json.dumps({"rating": 5, "confidence": 4})


class Responder(threading.Thread):
    """Watches a spool dir and answers every .req.md with the given payload."""

    def __init__(self, spool: Path, payload_for=None, delay: float = 0.05):
        super().__init__(daemon=True)
        self.spool = spool
        self.payload_for = payload_for or (lambda req_text: ANSWER)
        self.delay = delay
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            for req in list(self.spool.glob("*.req.md")):
                ans = req.with_name(req.name.replace(".req.md", ".ans.md"))
                if not ans.exists():
                    ans.write_text(
                        self.payload_for(req.read_text(encoding="utf-8")), encoding="utf-8"
                    )
            time.sleep(self.delay)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *a):
        self.stop.set()
        self.join(timeout=2)


def test_relay_roundtrip(tmp_path):
    spool = tmp_path / "spool"
    with Responder(spool):
        provider = RelayProvider(spool_dir=spool, timeout_s=5, poll_s=0.05)
        comp = provider.complete(system="SYS-INSTR", user="USER-PAPER", retries=0)
    assert comp.text == ANSWER
    reqs = list(spool.glob("*.req.md"))
    assert len(reqs) == 1
    body = reqs[0].read_text(encoding="utf-8")
    assert "SYS-INSTR" in body and "USER-PAPER" in body
    assert ".ans.md" in body  # protocol note names the answer file
    assert (spool / "README.txt").exists()
    # the spool holds paper text: it must ignore itself in git
    assert (spool / ".gitignore").read_text(encoding="utf-8").splitlines()[-1] == "*"


def test_relay_timeout(tmp_path):
    provider = RelayProvider(spool_dir=tmp_path / "s", timeout_s=0.3, poll_s=0.05)
    with pytest.raises(ProviderError) as exc:
        provider.complete(system="s", user="u", retries=0)
    assert "no answer" in str(exc.value)


def test_relay_unique_stems_for_parallel_reviewers(tmp_path):
    spool = tmp_path / "spool"
    provider_a = RelayProvider(spool_dir=spool, timeout_s=5, poll_s=0.05)
    provider_b = RelayProvider(spool_dir=spool, timeout_s=5, poll_s=0.05)
    with Responder(spool):
        ca = provider_a.complete(system="senior prompt", user="paper", retries=0)
        cb = provider_b.complete(system="senior prompt too", user="paper", retries=0)
    assert ca.text == cb.text == ANSWER
    stems = {p.name.split(".")[0] for p in spool.glob("*.req.md")}
    assert len(stems) == 2  # same persona, distinct slots


def test_cli_relay_end_to_end(tmp_path, monkeypatch, latex_project):
    monkeypatch.chdir(tmp_path)
    spool = tmp_path / "bridge"
    cfg_path = tmp_path / "prebuttal.toml"
    cfg_path.write_text(
        f"""
[default]
venue = "iclr"
seed = 7

[[reviewer]]
id = "R1"
persona = "senior_kind"
backend = "relay"

[[reviewer]]
id = "R2"
persona = "adversarial"
backend = "relay"

[[reviewer]]
id = "R3"
persona = "detail_obsessive"
backend = "relay"

[ac]
backend = "relay"

[relay]
dir = "{spool.as_posix()}"
timeout_s = 30
""",
        encoding="utf-8",
    )

    def iclr_payload(req_text: str) -> str:
        if "estimated_rating" in req_text:
            return json.dumps(
                {
                    "meta_review": "AC synthesis.",
                    "estimated_rating": 4.5,
                    "confidence": 4,
                    "recommendation": "borderline",
                    "disagreements": "R1 vs R2 on baselines.",
                }
            )
        if "Reviewer 2" in req_text:
            rating = 3
        elif "detail-obsessed" in req_text:
            rating = 5
        else:
            rating = 6
        return json.dumps(
            {
                "summary": "A summary.",
                "strengths": ["s1"],
                "weaknesses": ["w1"],
                "questions": ["q1"],
                "limitations": "none stated",
                "rating": rating,
                "confidence": 4,
            }
        )

    with Responder(spool, payload_for=iclr_payload):
        rc = cli.main(
            [
                "run",
                str(latex_project),
                "--config",
                str(cfg_path),
                "--out",
                "report.md",
                "--json",
                "out.json",
            ]
        )
    assert rc == cli.EXIT_OK

    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Predicted outcome" in md
    assert "relay" in md
    assert "(4.67 / 10)" in md or "**4.67 / 10**" in md  # mean of 6, 3, 5

    data = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert data["aggregate"]["mean"] == 4.67
    assert all(r["backend"] == "relay" for r in data["reviewers"])
