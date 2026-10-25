from __future__ import annotations

import json
from pathlib import Path

import pytest

from prebuttal.config import load_config
from prebuttal.ingestion import ingest
from prebuttal.models import Usage
from prebuttal.orchestrator import run_report
from prebuttal.providers.base import BaseProvider
from prebuttal.venues import get_venue


@pytest.fixture(autouse=True)
def isolated_prebuttal_home(tmp_path, monkeypatch):
    """Never touch the developer's real ~/.prebuttal from the test suite."""
    monkeypatch.setenv("PREBUTTAL_HOME", str(tmp_path / "prebuttal-home"))
    return tmp_path / "prebuttal-home"


@pytest.fixture(autouse=True)
def neutral_host_env(monkeypatch):
    """Same results whether the suite runs in CI, a terminal or a coding agent."""
    for var in ("PREBUTTAL_BACKEND", "CLAUDECODE", "GEMINI_CLI"):
        monkeypatch.delenv(var, raising=False)


def make_report(latex_project, *, venue_key: str = "iclr", rating_shift: int = 0):
    """Full fake-backend report for output-layer tests (also used by run tests)."""
    cfg = load_config(None)
    venue = get_venue(venue_key)
    paper = ingest(str(latex_project))
    providers = {r.id: PersonaFakeProvider() for r in cfg.reviewers}
    ac = PersonaFakeProvider()
    report = run_report(paper, cfg, venue, providers, ac, log=lambda m: None)
    if rating_shift:
        import statistics

        for rev in report.reviews:
            if rev.rating is not None:
                rev.rating += rating_shift
        ratings = [r.rating for r in report.reviews if r.rating is not None]
        report.aggregate.mean = round(statistics.mean(ratings), 2)
    return report, venue


# ------------------------------------------------- shared CLI-test fixtures

FAKE_TOML = """
[default]
venue = "iclr"
seed = 7

[[reviewer]]
id = "R1"
persona = "senior_kind"
backend = "fake"

[[reviewer]]
id = "R2"
persona = "adversarial"
backend = "fake"

[[reviewer]]
id = "R3"
persona = "detail_obsessive"
backend = "fake"

[ac]
backend = "fake"
"""


@pytest.fixture(autouse=True)
def register_fake_backend():
    from prebuttal.providers import register_backend

    register_backend(
        "fake", lambda model, cfg, timeout_s: PersonaFakeProvider(model=model or "fake-m")
    )
    yield


@pytest.fixture
def fake_statuses(monkeypatch):
    from prebuttal import cli
    from prebuttal.providers.detect import BackendStatus

    statuses = [
        BackendStatus("agent-claude", "agent", True, "claude CLI"),
        BackendStatus("agent-codex", "agent", False, "not found"),
        BackendStatus("api-gemini", "api", False, "no key"),
        BackendStatus("api-openai", "api", False, "no key"),
        BackendStatus("api-anthropic", "api", False, "no key"),
        BackendStatus("ollama", "ollama", False, "down"),
        BackendStatus("relay", "relay", True, "always available"),
    ]
    monkeypatch.setattr(cli, "scan_backends", lambda cfg=None: statuses)
    return statuses


@pytest.fixture
def fake_config(tmp_path):
    p = tmp_path / "prebuttal.toml"
    p.write_text(FAKE_TOML, encoding="utf-8")
    return p


# ------------------------------------------------------------------ fakes


def review_payload(persona_hint: str, venue_key: str = "iclr") -> dict:
    ratings = {"senior": 8, "adversarial": 4, "detail": 6}
    rating = 6
    for key, val in ratings.items():
        if key in persona_hint.lower():
            rating = val
            break
    return {
        "summary": f"Summary from {persona_hint}: the paper proposes X and evaluates on Y.",
        "strengths": ["Clear contribution (Section 3).", "Strong results in Table 1: 97.3."],
        "weaknesses": ["Baseline set is thin (Table 1 misses [cite])."],
        "questions": ["What is the variance across seeds (Table 2)?"],
        "limitations": "Authors state none; retrieval-heavy failure mode exists.",
        "rating": rating,
        "confidence": 4,
    }


META_PAYLOAD = {
    "meta_review": "The reviews agree the contribution is clear; R2 doubts the baselines.",
    "estimated_rating": 5.5,
    "confidence": 4,
    "recommendation": "borderline — accept after rebuttal",
    "disagreements": "R1 vs R2 on baseline adequacy; siding partly with R2.",
}


class PersonaFakeProvider(BaseProvider):
    """Deterministic in-process backend: persona-keyed canned JSON."""

    kind = "fake"

    def __init__(self, backend: str = "fake", model: str = "fake-1", calls: list | None = None):
        super().__init__(backend, model)
        self.calls = calls if calls is not None else []

    def _complete(self, *, system, user, temperature, seed, max_tokens):
        self.calls.append(
            {
                "system": system,
                "user": user,
                "temperature": temperature,
                "seed": seed,
                "max_tokens": max_tokens,
            }
        )
        if "estimated_rating" in system:  # AC spec
            payload = META_PAYLOAD
        else:
            hint = "senior"
            if "Reviewer 2" in system or "skeptical" in system:
                hint = "adversarial"
            elif "detail-obsessed" in system or "cell by cell" in system:
                hint = "detail"
            payload = review_payload(hint)
        return json.dumps(payload), Usage(1000, 200)


@pytest.fixture
def shared_calls() -> list:
    return []


# ------------------------------------------------------------------ fixtures

LATEX_MAIN = r"""
\documentclass{article}
\usepackage{booktabs}
% a comment line that must vanish
\title{Latent Bottleneck Transformers for Long Contexts}
\begin{document}
\maketitle
\begin{abstract}
We route tokens through a fixed-size latent pool. On LongBench we reach 97.3
overall with 61\% less memory.
\end{abstract}

\section{Introduction}\label{sec:intro}
Long inputs are expensive; our fix is in Section~\ref{sec:method}.
See Eq.~\eqref{eq:route} and Table~\ref{tab:main}.
\input{sections/method}

\section{Experiments}
Table~\ref{tab:main} shows results. % trailing comment
\begin{table}[t]
\centering
\caption{Main results on LongBench.}
\label{tab:main}
\begin{tabular}{lcc}
\toprule
Model & Score & Mem \\
\midrule
Full & 96.8 & 41.2 \\
\multicolumn{2}{c}{Ours} & 16.1 \\
\textbf{LBT} & \textbf{97.3} & \textbf{16.1} \\
\bottomrule
\end{tabular}
\end{table}

\appendix
\section{Hyperparameters}
lr $3\times10^{-4}$, 3 seeds. See Section~\ref{sec:intro}.

\bibliography{refs}
\end{document}
"""

LATEX_METHOD = r"""
\section{Method}\label{sec:method}
\subsection{Routing}
Tokens attend to $Z \in \mathbb{R}^{m \times d}$:
\begin{equation}
Z \leftarrow \mathrm{softmax}(Z W_q (X W_k)^\top / \sqrt{d}) X W_v
\label{eq:route}
\end{equation}
which is $O(nm)$.

\begin{figure}[t]
\centering
\caption{Quality vs. context length.}
\label{fig:len}
\end{figure}
"""

BBL = r"""
\begin{thebibliography}{1}
\bibitem{vaswani2017}
Vaswani et al. Attention is all you need. \emph{NeurIPS}, 2017.
\end{thebibliography}
"""


@pytest.fixture
def latex_project(tmp_path: Path) -> Path:
    (tmp_path / "main.tex").write_text(LATEX_MAIN, encoding="utf-8")
    (tmp_path / "main.bbl").write_text(BBL, encoding="utf-8")
    sec = tmp_path / "sections"
    sec.mkdir()
    (sec / "method.tex").write_text(LATEX_METHOD, encoding="utf-8")
    return tmp_path


def make_pdf_bytes(
    *,
    title: str = "Deep Widgets for Structured Prediction",
    body_extra: str = "",
) -> bytes:
    """Build a small synthetic paper PDF (headings, abstract, ruled table)."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()

    page.insert_text((72, 80), title, fontsize=18, fontname="hebo")
    page.insert_text((72, 104), "Alice Smith, Bob Jones", fontsize=10, fontname="helv")

    page.insert_text((72, 130), "Abstract", fontsize=11, fontname="hebo")
    page.insert_text(
        (72, 144),
        "We propose widgets that learn structure end to end.",
        fontsize=10,
        fontname="helv",
    )
    page.insert_text(
        (72, 156),
        "On three benchmarks we improve accuracy by 2.1 points.",
        fontsize=10,
        fontname="helv",
    )

    page.insert_text((72, 190), "1 Introduction", fontsize=12, fontname="hebo")
    page.insert_text(
        (72, 205),
        "Widgets matter for structured tasks and evaluation.",
        fontsize=10,
        fontname="helv",
    )

    page.insert_text((72, 230), "2 Experiments", fontsize=12, fontname="hebo")
    page.insert_text(
        (72, 245), "We compare against strong baselines with 3 seeds.", fontsize=10, fontname="helv"
    )

    # ruled table with caption
    x0, y0 = 72, 280
    widths = [110, 80, 80]
    rows = [
        ["Model", "Acc.", "F1"],
        ["WidgetNet", "97.3", "96.1"],
        ["Baseline", "95.2", "93.8"],
    ]
    row_h = 16
    page.insert_text(
        (x0, y0 - 6),
        "Table 1: Main results. WidgetNet reaches 97.3 accuracy.",
        fontsize=10,
        fontname="helv",
    )
    for i in range(len(rows) + 1):
        page.draw_line((x0, y0 + i * row_h), (x0 + sum(widths), y0 + i * row_h))
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)
    for x in xs:
        page.draw_line((x, y0), (x, y0 + len(rows) * row_h))
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            page.insert_text((xs[c] + 3, y0 + r * row_h + 11), cell, fontsize=9, fontname="helv")

    page.insert_text(
        (72, 420), "Figure 1: Accuracy vs. training size.", fontsize=10, fontname="helv"
    )
    # in-prose references: must NOT become a phantom table/figure
    page.insert_text(
        (72, 435),
        "Table 9 confirms that our widgets hold up. Figure 2 shows the trend.",
        fontsize=10,
        fontname="helv",
    )
    if body_extra:
        page.insert_text((72, 455), body_extra, fontsize=10, fontname="helv")

    return doc.tobytes()


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    return make_pdf_bytes()
