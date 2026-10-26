"""Venue registry: real conference review forms, as editable plain-text files.

Each venue is defined here programmatically (fields, scales, anchors) while the
human-readable form text lives in ``venues/forms/<key>.md`` so the community can
PR wording updates without touching code.  The form file is injected verbatim
into every reviewer prompt; the field spec drives JSON parsing and rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

FORMS_DIR = Path(__file__).parent / "forms"


class VenueError(KeyError):
    """Unknown venue, or a custom venue file that does not validate."""

    def __str__(self) -> str:  # KeyError would repr() the message
        return str(self.args[0]) if self.args else ""


@dataclass(frozen=True)
class VenueField:
    key: str
    label: str
    kind: str  # "text" | "list" | "score"
    max: float | None = None  # for scores
    allow_float: bool = False  # ARR half-steps
    anchors: dict[str, str] = field(default_factory=dict)  # "1" -> label
    required: bool = True

    @property
    def min(self) -> float:
        return 1.0

    def anchor_for(self, value: float) -> str:
        best = ""
        best_delta = None
        for k, label in self.anchors.items():
            delta = abs(float(k) - value)
            if best_delta is None or delta < best_delta:
                best, best_delta = label, delta
        return best


@dataclass(frozen=True)
class Venue:
    key: str
    name: str
    rating_key: str
    confidence_key: str | None
    fields: list[VenueField]
    form_file: str
    form_body: str = ""  # custom venues: the form text itself
    origin: str = ""  # custom venues: the TOML file it came from ("" = built-in)

    @property
    def custom(self) -> bool:
        return not self.form_file

    @property
    def rating_field(self) -> VenueField:
        return self.field(self.rating_key)

    def field(self, key: str) -> VenueField:
        for f in self.fields:
            if f.key == key:
                return f
        raise KeyError(key)

    def form_text(self) -> str:
        if self.form_body:
            return self.form_body
        path = FORMS_DIR / self.form_file
        if not path.is_file():
            raise FileNotFoundError(f"missing venue form file: {path}")
        return path.read_text(encoding="utf-8")

    def json_spec(self) -> str:
        """Machine-facing description of the JSON object reviewers must emit."""
        lines = ["Return ONLY a JSON object with exactly these keys:"]
        for f in self.fields:
            if f.kind == "text":
                lines.append(f'  "{f.key}": string  // {f.label}')
            elif f.kind == "list":
                req = "" if f.required else " (optional, may be empty)"
                lines.append(f'  "{f.key}": [string, ...]  // {f.label}{req}')
            else:
                rng = (
                    f"{f.min:g} to {f.max:g} (integers"
                    + (" or half-steps" if f.allow_float else "")
                    + ")"
                )
                lines.append(f'  "{f.key}": number  // {f.label}, scale {rng}')
                if f.anchors:
                    for k in sorted(f.anchors, key=float):
                        lines.append(f"      {k} = {f.anchors[k]}")
        return "\n".join(lines)


def _text(key: str, label: str, required: bool = True) -> VenueField:
    return VenueField(key, label, "text", required=required)


def _list(key: str, label: str, required: bool = True) -> VenueField:
    return VenueField(key, label, "list", required=required)


def _score(
    key: str,
    label: str,
    maximum: float,
    anchors: dict[str, str] | None = None,
    allow_float: bool = False,
) -> VenueField:
    return VenueField(
        key, label, "score", max=maximum, anchors=anchors or {}, allow_float=allow_float
    )


_NEURIPS_RATING = {
    "1": "Trivial or wrong",
    "2": "Reject",
    "3": "Borderline reject",
    "4": "Borderline accept",
    "5": "Accept",
    "6": "Strong accept",
}
_CONFIDENCE_5 = {
    "5": "Absolutely certain",
    "4": "Confident but not absolutely certain",
    "3": "Fairly confident",
    "2": "Willing to defend, but not sure",
    "1": "My best guess",
}

NEURIPS = Venue(
    key="neurips",
    name="NeurIPS",
    rating_key="rating",
    confidence_key="confidence",
    form_file="neurips.md",
    fields=[
        _text("summary", "Paper Summary"),
        _list("strengths", "Strengths"),
        _list("weaknesses", "Weaknesses"),
        _list("questions", "Questions to the Authors"),
        _list("suggestions", "Suggestions and Typos", required=False),
        _score("rating", "Rating", 6, _NEURIPS_RATING),
        _score("confidence", "Confidence", 5, _CONFIDENCE_5),
    ],
)

_ICLR_RATING = {
    "1": "Reject — technically flawed",
    "3": "Reject — not good enough",
    "5": "Marginally below acceptance threshold",
    "6": "Marginally above acceptance threshold",
    "8": "Accept — good paper",
    "10": "Award quality — award candidate",
}

ICLR = Venue(
    key="iclr",
    name="ICLR",
    rating_key="rating",
    confidence_key="confidence",
    form_file="iclr.md",
    fields=[
        _text("summary", "Summary"),
        _list("strengths", "Strengths"),
        _list("weaknesses", "Weaknesses"),
        _list("questions", "Questions to the Authors"),
        _text(
            "limitations", "Limitations — every ICLR review must comment on the stated limitations"
        ),
        _score("rating", "Rating", 10, _ICLR_RATING),
        _score("confidence", "Confidence", 5, _CONFIDENCE_5),
    ],
)

_ICML_RATING = {
    "1": "Trivial or wrong",
    "2": "Trivial or wrong",
    "3": "Clear reject",
    "4": "Reject — not good enough",
    "5": "Marginally below publication threshold",
    "6": "Marginally above publication threshold",
    "7": "Accept — good paper",
    "8": "Accept — top 50% of accepted papers",
    "9": "Strong accept — top 15%",
    "10": "Award quality",
}

ICML = Venue(
    key="icml",
    name="ICML",
    rating_key="rating",
    confidence_key="confidence",
    form_file="icml.md",
    fields=[
        _text("summary", "Summary"),
        _list("strengths", "Strengths"),
        _list("weaknesses", "Weaknesses"),
        _list("questions", "Questions to the Authors"),
        _list("suggestions", "Suggestions and Typos", required=False),
        _score("rating", "Rating", 10, _ICML_RATING),
        _score("confidence", "Confidence", 5, _CONFIDENCE_5),
    ],
)

_ARR_SOUNDNESS = {
    "5": "Excellent — one of the most thorough studies of its type",
    "4": "Strong — sufficient support for all claims",
    "3": "Acceptable — sufficient support for main claims",
    "2": "Poor — some main claims not sufficiently supported",
    "1": "Major issues — not sufficiently thorough",
}
_ARR_EXCITEMENT = {
    "5": "Highly exciting",
    "4": "Exciting",
    "3": "Interesting",
    "2": "Potentially interesting",
    "1": "Not exciting",
}
_ARR_OVERALL = {
    "5": "Consider for award",
    "4": "Conference — accept to an *ACL conference",
    "3": "Findings — accept to Findings of the ACL",
    "2": "Resubmit next cycle — needs substantial revisions",
    "1": "Do not resubmit",
}

ARR = Venue(
    key="acl",
    name="ACL Rolling Review",
    rating_key="overall_assessment",
    confidence_key="confidence",
    form_file="acl.md",
    fields=[
        _text("summary", "Paper Summary"),
        _list("strengths", "Summary of Strengths"),
        _list("weaknesses", "Summary of Weaknesses"),
        _list("comments", "Comments, Suggestions and Typos", required=False),
        _score("soundness", "Soundness", 5, _ARR_SOUNDNESS, allow_float=True),
        _score("excitement", "Excitement", 5, _ARR_EXCITEMENT, allow_float=True),
        _score("overall_assessment", "Overall Assessment", 5, _ARR_OVERALL, allow_float=True),
        _score("confidence", "Reviewer Confidence", 5, _CONFIDENCE_5),
    ],
)

VENUES: dict[str, Venue] = {v.key: v for v in (NEURIPS, ICLR, ICML, ARR)}
VENUE_KEYS = list(VENUES)


def get_venue(name: str) -> Venue:
    """A built-in venue, a custom one by name, or a venue file by path.

    Custom venues live in ``./.prebuttal/venues/`` or ``~/.prebuttal/venues/``
    (see :mod:`prebuttal.venues.custom`).  Raises VenueError (a KeyError).
    """
    from . import custom

    raw = (name or "").strip()
    if custom.looks_like_path(raw):
        return custom.load_venue_file(raw)
    key = raw.lower()
    if key in VENUES:
        return VENUES[key]
    path = custom.find_venue_file(key)
    if path is not None:
        return custom.load_venue_file(path)
    extra = [p.stem for p, v, _e in custom.list_custom() if v is not None]
    names = ", ".join(VENUE_KEYS + extra)
    raise VenueError(
        f"unknown venue '{key}' — available: {names}. Add your own with "
        f"`prebuttal venues new {key or 'myvenue'}` (see `prebuttal venues`)"
    )


def venue_from_report(d: dict) -> Venue:
    """The venue a stored ``report.json`` was written for.

    Custom venues are rebuilt from the definition the report carries, so an
    archived report still renders after its venue file is moved or edited."""
    from . import custom

    v = d.get("venue")
    key = (v.get("key", "") if isinstance(v, dict) else str(v or "")).lower()
    if key in VENUES:
        return VENUES[key]
    spec = v.get("definition") if isinstance(v, dict) else None
    if isinstance(spec, dict):
        # the form text is not stored: it is only needed to run a review
        return custom.venue_from_spec(key, spec, form="(review form not stored in the report)")
    return get_venue(key)
