# Contributing to Prebuttal

Thanks for helping make pre-submission reviewing less of a coin flip.

## Development setup

```bash
git clone https://github.com/GuoYuKai-SaMuEl/prebuttal
cd prebuttal
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"    # Windows
# .venv/bin/pip install -e ".[dev]"      # macOS / Linux

pytest -q              # run the suite
ruff check .           # lint
ruff format .          # format (CI enforces both)
```

No API key is needed to develop: the test suite runs fully offline against
fake providers. If you add a test that needs a PDF, generate it with PyMuPDF
in the test (see `tests/conftest.py::make_pdf_bytes`).

## The three easiest contributions

### 1. Add or fix a venue form

Forms are plain text: `prebuttal/venues/forms/<venue>.md` (what the reviewer
sees) plus an entry in `prebuttal/venues/__init__.py` (fields, scales, anchor
labels — what the JSON parser and report renderer use). Scales drift every
year; PRs that re-anchor them against the official reviewer guidelines are
especially welcome (link the official page in the PR).

### 2. Add a persona

Drop `prebuttal/personas/<your_persona>.md` — the file body is the system
prompt, the filename is the persona id. Good personas demand evidence
("cite the table"), not just attitude. Include a test in
`tests/test_venues_personas.py`.

### 3. Add a backend

Implement `BaseProvider._complete()` in `prebuttal/providers/`, register it in
`providers/__init__.py`, add detection in `providers/detect.py` if it should
be auto-discovered, and cover request shape + error paths with tests (see
`tests/test_providers.py` for the mock-transport pattern).

## Pull request checklist

- [ ] Tests added or updated (`pytest -q` green)
- [ ] `ruff check .` and `ruff format --check .` clean
- [ ] `CHANGELOG.md` entry under `[Unreleased]`
- [ ] Docs updated if you touched user-facing behavior (README / SKILL.md)
- [ ] Venue/persona changes link the official source

## Design commitments (don't break these in a PR)

1. **Orchestration lives in the CLI.** The host agent drives the CLI; it never
   role-plays reviewers itself. That's what keeps reviews genuinely independent.
2. **Honesty is a feature.** Every review is labeled with its backend and
   model; disagreement is always reported; the tool never claims to predict
   scores.
3. **Tables are sacred.** The ingestion pipeline must never silently drop
   experimental numbers — if cell parsing fails, ship the verbatim fallback.

## Reporting problems

Bugs and feature requests: [open an issue](https://github.com/GuoYuKai-SaMuEl/prebuttal/issues).
Security issues: see [SECURITY.md](SECURITY.md). Conduct: see
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
