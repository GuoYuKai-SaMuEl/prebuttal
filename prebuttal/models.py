"""Core data structures shared across ingestion, orchestration and reporting."""

from __future__ import annotations

import hashlib
import platform
import sys
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from typing import Any

from . import __version__


@dataclass
class Usage:
    """Token accounting. Agent-CLI backends do not report usage (0/0)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens

    @property
    def known(self) -> bool:
        return (self.prompt_tokens or self.completion_tokens) > 0

    def describe(self) -> str:
        if not self.known:
            return "usage n/a (backend reports no tokens)"
        return f"{self.prompt_tokens:,} in / {self.completion_tokens:,} out"


@dataclass
class Section:
    level: int  # 1 = top level
    number: str  # "3" / "3.2" / "A.1" / "" for unnumbered
    title: str
    text: str
    appendix: bool = False

    @property
    def heading(self) -> str:
        prefix = f"{self.number} " if self.number else ""
        return f"{prefix}{self.title}".strip()


@dataclass
class Table:
    """One table of the paper, kept cell-accurate when possible.

    ``header``/``rows`` are filled by table detection (PDF) or tabular parsing
    (LaTeX).  ``raw`` always holds a verbatim text fallback so experimental
    numbers are never lost even when cell detection fails.
    """

    number: str
    caption: str
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    raw: str = ""
    source: str = ""  # "latex-tabular" | "pdf-table" | "pdf-caption-block"
    section: str = ""  # section heading where the table appears

    @property
    def cell_text(self) -> str:
        return " | ".join(" ".join(r) for r in ([self.header, *self.rows]) if r)

    def to_markdown(self) -> str:
        if not self.rows:
            return self.raw.strip()
        header = self.header or self.rows[0]
        body = self.rows if self.header else self.rows[1:]

        def esc(c: str) -> str:
            return c.replace("|", "\\|").replace("\n", " ").strip()

        lines = [
            "| " + " | ".join(esc(c) for c in header) + " |",
            "|" + "---|" * len(header),
        ]
        for row in body:
            if len(row) < len(header):
                row = row + [""] * (len(header) - len(row))
            lines.append("| " + " | ".join(esc(c) for c in row[: len(header)]) + " |")
        return "\n".join(lines)


@dataclass
class Figure:
    number: str
    caption: str
    section: str = ""


@dataclass
class StructuredPaper:
    title: str
    abstract: str
    sections: list[Section] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    source_type: str = ""  # "pdf" | "latex" | "arxiv"
    source_path: str = ""
    warnings: list[str] = field(default_factory=list)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "sections": len(self.sections),
            "tables": len(self.tables),
            "figures": len(self.figures),
            "warnings": list(self.warnings),
        }


def param_support(backend: str) -> tuple[bool, bool]:
    """Whether ``backend`` really applies (temperature, seed).

    Agent CLIs (``claude -p``, ``codex exec``, custom ``[agents.*]``) expose
    neither, the relay responder is an outside agent, and the Anthropic API
    has no seed. Reports show the configured value only where it took effect.
    """
    if backend.startswith("agent-") or backend == "relay":
        return False, False
    if backend == "api-anthropic":
        return True, False
    return True, True


@dataclass
class Review:
    reviewer_id: str
    persona: str
    backend: str
    model: str
    temperature: float
    seed: int | None
    fields: dict[str, Any] = field(default_factory=dict)
    rating: float | None = None
    confidence: float | None = None
    parse_ok: bool = False
    raw_output: str = ""
    error: str | None = None
    usage: Usage = field(default_factory=Usage)
    duration_s: float = 0.0
    started_at: str = ""


@dataclass
class MetaReview:
    backend: str
    model: str
    temperature: float
    meta_review: str = ""
    estimated_rating: float | None = None
    confidence: float | None = None
    recommendation: str = ""
    disagreements: str = ""
    parse_ok: bool = False
    raw_output: str = ""
    error: str | None = None
    usage: Usage = field(default_factory=Usage)
    duration_s: float = 0.0


@dataclass
class Aggregate:
    ratings: list[float] = field(default_factory=list)
    mean: float | None = None
    std: float | None = None
    min: float | None = None
    max: float | None = None
    n: int = 0

    @property
    def spread(self) -> float | None:
        if self.min is None or self.max is None:
            return None
        return round(self.max - self.min, 2)


def make_aggregate(reviews: list[Review]) -> Aggregate:
    ratings = [float(r.rating) for r in reviews if r.parse_ok and r.rating is not None]
    agg = Aggregate(ratings=ratings, n=len(ratings))
    if ratings:
        mean = sum(ratings) / len(ratings)
        var = sum((x - mean) ** 2 for x in ratings) / len(ratings)
        agg.mean = round(mean, 2)
        agg.std = round(var**0.5, 2)
        agg.min = min(ratings)
        agg.max = max(ratings)
    return agg


@dataclass
class RunInfo:
    venue: str
    seed: int
    generated_at: str = ""
    prebuttal_version: str = __version__
    python_version: str = sys.version.split()[0]
    platform: str = platform.platform()
    source: str = ""
    source_type: str = ""
    pack_chars: int = 0
    pack_sha256: str = ""
    config_path: str | None = None

    @staticmethod
    def now_iso() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class ReviewReport:
    paper: StructuredPaper
    venue_key: str
    reviews: list[Review]
    meta: MetaReview
    aggregate: Aggregate
    run: RunInfo
    usage_total: Usage = field(default_factory=Usage)


def dataclass_to_dict(obj: Any) -> Any:
    """Recursively convert dataclasses (nested in dicts/lists) to plain data."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: dataclass_to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: dataclass_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [dataclass_to_dict(v) for v in obj]
    return obj


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
