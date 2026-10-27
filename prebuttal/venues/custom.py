"""User-defined venues: one TOML file (+ the form text) per venue.

Looked up by name in, first to last::

    ./.prebuttal/venues/<key>.toml      (project-local — commit it for the lab)
    ~/.prebuttal/venues/<key>.toml      (personal; $PREBUTTAL_HOME moves it)

or used directly as ``--venue path/to/venue.toml``.  ``prebuttal venues new``
writes a commented template.  A file looks like::

    name = "CVPR 2027"
    form = "cvpr.md"              # review-form text, relative to this file
    rating = "rating"             # which score is the overall rating
    confidence = "confidence"     # optional

    [[fields]]
    key = "summary"
    label = "Paper summary"
    kind = "text"                 # text | list | score

    [[fields]]
    key = "rating"
    label = "Overall recommendation"
    kind = "score"
    max = 6                       # scores run from 1 to max
    anchors = { "1" = "Reject", "6" = "Strong accept" }

    [checks]                      # optional: what `prebuttal check` holds it to
    double_blind = true
    page_limit = 8                # main-text pages
    required_sections = ["Limitations"]

The form text is shown to reviewers verbatim, exactly like the built-in forms;
the fields drive the JSON reviewers must return and every report.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

from . import VENUES, CheckRules, Venue, VenueError, VenueField

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
KINDS = ("text", "list", "score")
MAX_FORM_CHARS = 20_000

_TOP_KEYS = {"name", "form", "form_text", "rating", "confidence", "fields", "checks"}
_CHECK_KEYS = {"double_blind", "page_limit", "required_sections", "uncounted"}
_FIELD_KEYS = {"key", "label", "kind", "required", "max", "half_steps", "anchors"}


def home_dir() -> Path:
    base = os.environ.get("PREBUTTAL_HOME")
    return (Path(base) if base else Path.home() / ".prebuttal") / "venues"


def search_dirs() -> list[Path]:
    return [Path.cwd() / ".prebuttal" / "venues", home_dir()]


def looks_like_path(name: str) -> bool:
    return name.endswith(".toml") or "/" in name or "\\" in name


def find_venue_file(key: str) -> Path | None:
    for d in search_dirs():
        p = d / f"{key}.toml"
        if p.is_file():
            return p
    return None


def load_venue_file(path: str | Path) -> Venue:
    """Parse and validate one venue file; errors name the file and the problem."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise VenueError(f"venue file not found: {path}")
    key = path.stem.lower()
    if not KEY_RE.match(key):
        raise VenueError(
            f"{path}: file name must be a short lowercase key like 'cvpr.toml' or 'lab-review.toml'"
        )
    if key in VENUES:
        raise VenueError(
            f"{path}: '{key}' is a built-in venue — give your version its own name "
            f"(e.g. '{key}-2027.toml'; `prebuttal venues new {key}-2027 --from {key}`)"
        )
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise VenueError(f"{path}: cannot read venue file: {e}") from e
    form = raw.get("form_text")
    if form is None and "form" in raw:
        form_path = (path.parent / str(raw["form"])).resolve()
        if not form_path.is_relative_to(path.parent.resolve()):
            # the form text is sent to the model provider: a venue file (maybe
            # from a cloned repo) must not be able to point at ~/.ssh or similar
            raise VenueError(f"{path}: form must be a file in the same folder (or below)")
        try:
            form = form_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise VenueError(f"{path}: cannot read form file {form_path}: {e}") from e
    try:
        venue = venue_from_spec(key, raw, form=form, origin=str(path))
    except VenueError as e:
        raise VenueError(f"{path}: {e}") from None
    return venue


def venue_from_spec(key: str, spec: dict[str, Any], *, form: str | None, origin: str = "") -> Venue:
    """Build a Venue from its TOML/JSON description (validated)."""
    unknown = set(spec) - _TOP_KEYS
    if unknown:
        raise VenueError(f"unknown setting(s) {', '.join(sorted(unknown))}")
    name = spec.get("name")
    if not isinstance(name, str) or not name.strip():
        raise VenueError('missing name = "..."')
    if form is not None:
        if not isinstance(form, str) or not form.strip():
            raise VenueError("the review-form text is empty")
        if len(form) > MAX_FORM_CHARS:
            raise VenueError(f"the review-form text is over {MAX_FORM_CHARS} characters")
    raw_fields = spec.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise VenueError("no [[fields]] defined")
    fields: list[VenueField] = []
    for i, f in enumerate(raw_fields, 1):
        fields.append(_field(f, i))
    keys = [f.key for f in fields]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise VenueError(f"field key(s) used twice: {', '.join(dup)}")
    by_key = {f.key: f for f in fields}
    rating = spec.get("rating")
    if rating not in by_key or by_key[rating].kind != "score":
        scores = [f.key for f in fields if f.kind == "score"] or ["(none)"]
        raise VenueError(
            f"rating = {rating!r} must name a score field (score fields: {', '.join(scores)})"
        )
    confidence = spec.get("confidence")
    if confidence is not None and (confidence not in by_key or by_key[confidence].kind != "score"):
        raise VenueError(f"confidence = {confidence!r} must name a score field")
    if form is None:
        raise VenueError('no review form: add form = "<file>.md" (or form_text = """...""")')
    return Venue(
        key=key,
        name=name.strip(),
        rating_key=rating,
        confidence_key=confidence,
        fields=fields,
        form_file="",
        form_body=form,
        origin=origin,
        rules=_checks(spec.get("checks", {})),
    )


def _checks(c: Any) -> CheckRules:
    if not isinstance(c, dict):
        raise VenueError("[checks] must be a table")
    unknown = set(c) - _CHECK_KEYS
    if unknown:
        raise VenueError(f"[checks]: unknown setting(s) {', '.join(sorted(unknown))}")
    blind = c.get("double_blind", True)
    if not isinstance(blind, bool):
        raise VenueError("[checks]: double_blind must be true or false")
    limit = c.get("page_limit")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise VenueError("[checks]: page_limit must be a whole number of pages")
    lists = {}
    for k in ("required_sections", "uncounted"):
        v = c.get(k, [])
        if not isinstance(v, list) or not all(isinstance(s, str) and s.strip() for s in v):
            raise VenueError(f'[checks]: {k} must be a list of headings, e.g. ["Limitations"]')
        lists[k] = tuple(s.strip() for s in v)
    base = CheckRules()
    return CheckRules(
        double_blind=blind,
        page_limit=limit,
        required_sections=lists["required_sections"],
        # the venue's own uncounted headings come on top of References & co.
        uncounted=base.uncounted + lists["uncounted"],
    )


def _field(f: Any, i: int) -> VenueField:
    where = f"field #{i}"
    if not isinstance(f, dict):
        raise VenueError(f"{where} is not a table")
    key = f.get("key")
    if isinstance(key, str):
        where = f"field '{key}'"
    unknown = set(f) - _FIELD_KEYS
    if unknown:
        raise VenueError(f"{where}: unknown setting(s) {', '.join(sorted(unknown))}")
    if not isinstance(key, str) or not FIELD_RE.match(key):
        raise VenueError(f"{where}: key must be lowercase letters, digits and _ (got {key!r})")
    label = f.get("label")
    if not isinstance(label, str) or not label.strip():
        raise VenueError(f"{where}: missing label")
    kind = f.get("kind")
    if kind not in KINDS:
        raise VenueError(f"{where}: kind must be one of {', '.join(KINDS)} (got {kind!r})")
    required = f.get("required", True)
    if not isinstance(required, bool):
        raise VenueError(f"{where}: required must be true or false")
    if kind != "score":
        for k in ("max", "half_steps", "anchors"):
            if k in f:
                raise VenueError(f"{where}: '{k}' only applies to kind = \"score\"")
        return VenueField(key, label.strip(), kind, required=required)
    maximum = f.get("max")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 2 <= maximum <= 100:
        raise VenueError(f"{where}: max must be a whole number from 2 to 100 (scores start at 1)")
    half = f.get("half_steps", False)
    if not isinstance(half, bool):
        raise VenueError(f"{where}: half_steps must be true or false")
    anchors_raw = f.get("anchors", {})
    if not isinstance(anchors_raw, dict):
        raise VenueError(f'{where}: anchors must look like {{ "1" = "Reject", ... }}')
    anchors: dict[str, str] = {}
    for k, v in anchors_raw.items():
        try:
            score = float(k)
        except ValueError:
            raise VenueError(f"{where}: anchor {k!r} is not a number") from None
        if not 1 <= score <= maximum:
            raise VenueError(f"{where}: anchor {k} is outside 1-{maximum}")
        if not isinstance(v, str) or not v.strip():
            raise VenueError(f"{where}: anchor {k} needs a label")
        anchors[f"{score:g}"] = v.strip()
    return VenueField(
        key,
        label.strip(),
        "score",
        max=float(maximum),
        anchors=anchors,
        allow_float=half,
        required=required,
    )


def venue_to_spec(venue: Venue) -> dict[str, Any]:
    """The JSON-able definition a report keeps, so it renders without the file."""
    fields = []
    for f in venue.fields:
        d: dict[str, Any] = {"key": f.key, "label": f.label, "kind": f.kind}
        if not f.required:
            d["required"] = False
        if f.kind == "score":
            d["max"] = int(f.max or 0)
            if f.allow_float:
                d["half_steps"] = True
            if f.anchors:
                d["anchors"] = dict(f.anchors)
        fields.append(d)
    spec: dict[str, Any] = {"name": venue.name, "rating": venue.rating_key, "fields": fields}
    if venue.confidence_key:
        spec["confidence"] = venue.confidence_key
    return spec


def list_custom() -> list[tuple[Path, Venue | None, str]]:
    """Every venue file on the search path: (path, venue or None, error)."""
    out: list[tuple[Path, Venue | None, str]] = []
    seen: set[str] = set()
    for d in search_dirs():
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.toml")):
            if p.stem.lower() in seen:
                continue  # shadowed by a project-local file of the same name
            seen.add(p.stem.lower())
            try:
                out.append((p, load_venue_file(p), ""))
            except VenueError as e:
                out.append((p, None, str(e)))
    return out


# ------------------------------------------------------------------ templates


def _q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # a valid TOML basic string


def render_template(key: str, base: Venue | None = None) -> tuple[str, str]:
    """(venue TOML, form markdown) for ``prebuttal venues new``."""
    rules = base.rules if base is not None else CheckRules(page_limit=None)
    if base is not None:
        name = f"{base.name} (custom)"
        fields = base.fields
        rating, confidence = base.rating_key, base.confidence_key
        form = base.form_text()
        intro = f"# Copied from the built-in '{base.key}' venue; edit freely."
    else:
        name = key.upper()
        fields = [
            VenueField("summary", "Summary", "text"),
            VenueField("strengths", "Strengths", "list"),
            VenueField("weaknesses", "Weaknesses", "list"),
            VenueField("questions", "Questions to the Authors", "list"),
            VenueField(
                "rating",
                "Overall Rating",
                "score",
                max=10.0,
                anchors={
                    "1": "Strong reject",
                    "4": "Borderline reject",
                    "6": "Borderline accept",
                    "10": "Strong accept",
                },
            ),
            VenueField(
                "confidence",
                "Confidence",
                "score",
                max=5.0,
                anchors={"1": "Educated guess", "5": "Absolutely certain"},
            ),
        ]
        rating, confidence = "rating", "confidence"
        form = (
            f"# {name} review form\n\n"
            "You are filling in the official review form for this submission.\n"
            "Paste the venue's real reviewer guidelines here: reviewers read this\n"
            "text verbatim, so wording and score descriptions matter.\n\n"
            "## Form fields\n\n"
            "- **Summary**: the paper's claims and contributions in your own words.\n"
            "- **Strengths** / **Weaknesses**: bullet lists, each point citing the paper.\n"
            "- **Questions to the Authors**: what you would ask in the rebuttal.\n"
            "- **Overall Rating** (1-10): 1 strong reject … 10 strong accept.\n"
            "- **Confidence** (1-5): 1 educated guess … 5 absolutely certain.\n"
        )
        intro = "# A custom review form for prebuttal; edit freely."
    lines = [
        intro,
        "# Use it with:  prebuttal run paper.pdf --venue " + key,
        "# Scores run from 1 to max; `half_steps = true` allows 3.5 etc.",
        "# kind: text (one paragraph) | list (bullet points) | score",
        "",
        f"name = {_q(name)}",
        f"form = {_q(key + '.md')}  # the review-form text reviewers read, next to this file",
        f"rating = {_q(rating)}  # the score that is the overall recommendation",
    ]
    if confidence:
        lines.append(f"confidence = {_q(confidence)}")
    for f in fields:
        lines += ["", "[[fields]]", f"key = {_q(f.key)}", f"label = {_q(f.label)}"]
        lines.append(f"kind = {_q(f.kind)}")
        if not f.required:
            lines.append("required = false")
        if f.kind == "score":
            lines.append(f"max = {int(f.max or 0)}")
            if f.allow_float:
                lines.append("half_steps = true")
            if f.anchors:
                lines.append("[fields.anchors]")
                for k in sorted(f.anchors, key=float):
                    lines.append(f"{_q(k)} = {_q(f.anchors[k])}")
    lines += [
        "",
        "# What `prebuttal check` holds a submission to (all optional).",
        "[checks]",
        f"double_blind = {'true' if rules.double_blind else 'false'}",
    ]
    if rules.page_limit:
        lines.append(f"page_limit = {rules.page_limit}  # main-text pages")
    else:
        lines.append("# page_limit = 8  # main-text pages")
    extra = [s for s in rules.uncounted if s not in CheckRules().uncounted]
    lines.append(f"required_sections = [{', '.join(_q(s) for s in rules.required_sections)}]")
    lines.append(
        f"uncounted = [{', '.join(_q(s) for s in extra)}]  "
        "# headings after which pages stop counting (References always do)"
    )
    return "\n".join(lines) + "\n", form
