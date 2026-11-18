"""Core data structures shared across ingestion, orchestration and reporting."""

from __future__ import annotations

import hashlib
import platform
import re
import sys
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from typing import Any

from . import __version__


def token_count(v: Any) -> int:
    if isinstance(v, bool):
        return 0
    try:
        n = int(v)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(n, 0)


@dataclass
class Usage:
    """Token accounting. Agent-CLI backends do not report usage (0/0)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __post_init__(self) -> None:
        # a provider may report null, a string or a float: token counts must
        # never be what stops a finished (and paid) run from being written
        self.prompt_tokens = token_count(self.prompt_tokens)
        self.completion_tokens = token_count(self.completion_tokens)

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
    source: str = ""  # "latex-tabular" | "pdf-table" | "pdf-text" | "pdf-caption-block"
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

        # a row with more cells than the header widens the table: no number is lost
        width = max(len(header), *(len(r) for r in body)) if body else len(header)
        header = header + [""] * (width - len(header))
        lines = [
            "| " + " | ".join(esc(c) for c in header) + " |",
            "|" + "---|" * width,
        ]
        for row in body:
            row = row + [""] * (width - len(row))
            lines.append("| " + " | ".join(esc(c) for c in row) + " |")
        return "\n".join(lines)


@dataclass
class Figure:
    number: str
    caption: str
    section: str = ""
    page: int = 0  # PDF page (from 1) of the caption; 0 = unknown
    graphic: str = ""  # LaTeX: the first \includegraphics path


@dataclass
class FigureImage:
    """A figure as an image for vision-capable reviewers (never in report.json)."""

    label: str  # e.g. "page 3 (Figures 1, 2)" or "Figure 4"
    png: bytes = field(repr=False)


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
    # text a human reader cannot see (white / microscopic / off-page)
    hidden_text: list[str] = field(default_factory=list)
    # rendered figures, only when figures are enabled (figures = true)
    figure_images: list[FigureImage] = field(default_factory=list, repr=False)
    # counts from a stored report.json, whose summary has no section bodies
    stored_counts: dict[str, int] = field(default_factory=dict, repr=False)

    def summary_dict(self) -> dict[str, Any]:
        def count(name: str, items: list) -> int:
            return len(items) if items else self.stored_counts.get(name, 0)

        return {
            "title": self.title,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "sections": count("sections", self.sections),
            "tables": count("tables", self.tables),
            "figures": count("figures", self.figures),
            "warnings": list(self.warnings),
        }


EFFORT_LEVELS = ("low", "medium", "high")


def openai_reasoning_model(model: str) -> bool:
    """gpt-5 and later / o-series: no sampling parameters, reasoning_effort instead."""
    m = model.lower().rsplit("/", 1)[-1]
    return bool(re.match(r"(gpt-([5-9]|[1-9]\d)|o[1-9])", m)) and "chat" not in m


def param_support(backend: str, model: str = "") -> tuple[bool, bool]:
    """Whether ``backend`` (with ``model``) really applies (temperature, seed).

    Agent CLIs (``claude -p``, ``codex exec``, ``agy -p``, custom
    ``[agents.*]``) expose neither, the relay responder is an outside agent, current Claude API
    models accept only their default sampling and have no seed, and OpenAI
    reasoning models (gpt-5, o-series) take no temperature. Reports show the
    configured value only where it took effect.
    """
    if backend.startswith("agent-") or backend in ("relay", "api-anthropic"):
        return False, False
    if backend == "api-openai" and openai_reasoning_model(model):
        return False, True
    return True, True


_CLAUDE_VERSION = re.compile(r"claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-(?:\d{8}|latest))?$")


def anthropic_effort_model(model: str) -> bool:
    """The Messages API takes ``output_config.effort`` from Claude 4.6 on, and
    on Opus 4.5; older models answer it with a 400. Unknown ids get it."""
    model = model.lower()
    if re.match(r"claude-\d", model):  # the version before the tier: Claude 3.x and older
        return False
    m = _CLAUDE_VERSION.match(model)
    if not m:
        return True
    version = (int(m[2]), int(m[3] or 0))
    return version >= (4, 6) or (m[1] == "opus" and version == (4, 5))


def effort_support(backend: str, model: str = "") -> bool:
    """Whether ``backend`` (with ``model``) has a reasoning-effort control we can set."""
    if backend == "api-anthropic":
        return anthropic_effort_model(model)
    if backend in ("agent-claude", "agent-codex", "agent-agy", "api-gemini", "api-openrouter"):
        return True
    if backend == "api-openai":
        return openai_reasoning_model(model)
    if backend == "ollama":
        return "gpt-oss" in model.lower()  # the Ollama models with think levels
    return False


@dataclass
class Review:
    reviewer_id: str
    persona: str
    backend: str
    model: str
    temperature: float
    seed: int | None
    repeat: int = 0  # which round of this reviewer (`repeats` in prebuttal.toml)
    effort: str = ""  # reasoning effort actually sent; "" = the model's default
    images: int = 0  # figure images this reviewer was shown
    fields: dict[str, Any] = field(default_factory=dict)
    rating: float | None = None
    confidence: float | None = None
    parse_ok: bool = False
    raw_output: str = ""
    error: str | None = None
    usage: Usage = field(default_factory=Usage)
    duration_s: float = 0.0
    started_at: str = ""

    @property
    def slot(self) -> tuple[str, int]:
        """Which review this is: (reviewer id, round)."""
        return (self.reviewer_id, self.repeat)

    @property
    def label(self) -> str:
        return slot_label(self.reviewer_id, self.repeat)


def slot_label(reviewer_id: str, repeat: int = 0) -> str:
    """``R1`` for a reviewer's first round, ``R1·2`` for its second, ..."""
    return reviewer_id if repeat == 0 else f"{reviewer_id}·{repeat + 1}"


PRIORITIES = ("must", "should", "could")


CHECK = "check"  # raised_by of the plan items `prebuttal check` adds, not the AC


@dataclass
class ActionItem:
    """One entry of the AC's revision plan: what to fix before submitting."""

    priority: str  # must | should | could
    issue: str
    action: str
    raised_by: list[str] = field(default_factory=list)  # reviewer ids
    effort: str = ""  # small | medium | large ("" = not estimated)
    id: str = ""  # P1, P2, ... in plan order, unique within the run ("" before 0.6.1)


@dataclass
class MetaReview:
    backend: str
    model: str
    temperature: float
    effort: str = ""
    meta_review: str = ""
    estimated_rating: float | None = None
    confidence: float | None = None
    recommendation: str = ""
    disagreements: str = ""
    action_plan: list[ActionItem] = field(default_factory=list)
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
    # the panel mean of each round (`repeats`), in round order; one entry for
    # a single run, none in runs archived before 0.7
    round_means: list[float] = field(default_factory=list)

    @property
    def spread(self) -> float | None:
        if self.min is None or self.max is None:
            return None
        return round(self.max - self.min, 2)

    @property
    def rounds_note(self) -> str:
        """``3 rounds: 5.33-6`` (an en dash) for a run of several rounds, else empty."""
        rm = self.round_means
        if len(rm) < 2:
            return ""
        return f"{len(rm)} rounds: {min(rm):g}–{max(rm):g}"  # noqa: RUF001


def _ratings(reviews: list[Review]) -> list[float]:
    return [float(r.rating) for r in reviews if r.parse_ok and r.rating is not None]


def make_aggregate(reviews: list[Review]) -> Aggregate:
    ratings = _ratings(reviews)
    agg = Aggregate(ratings=ratings, n=len(ratings))
    if ratings:
        mean = sum(ratings) / len(ratings)
        var = sum((x - mean) ** 2 for x in ratings) / len(ratings)
        agg.mean = round(mean, 2)
        agg.std = round(var**0.5, 2)
        agg.min = min(ratings)
        agg.max = max(ratings)
    for k in sorted({r.repeat for r in reviews}):
        in_round = _ratings([r for r in reviews if r.repeat == k])
        if in_round:  # a round with no rating has no mean
            agg.round_means.append(round(sum(in_round) / len(in_round), 2))
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
    # the figure images shown to the reviewers (labels and bytes); "" in runs
    # archived before 0.7.0, a value (also for no images) since
    figures_sha256: str = ""
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
    # the exact text every reviewer received; archived as pack.md so failed
    # reviewers can be retried later (never part of report.json)
    pack: str = field(default="", repr=False)


def dataclass_to_dict(obj: Any) -> Any:
    """Recursively convert dataclasses (nested in dicts/lists) to plain data."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: dataclass_to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: dataclass_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [dataclass_to_dict(v) for v in obj]
    return obj


def figures_digest(images: list[FigureImage]) -> str:
    """One hash over every figure image a reviewer saw, in order."""
    return sha256_text(
        "\n".join(f"{im.label}\t{hashlib.sha256(im.png).hexdigest()}" for im in images)
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
