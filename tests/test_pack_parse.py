from prebuttal.models import Section, StructuredPaper, Table
from prebuttal.orchestrator import coerce_fields, extract_json_object
from prebuttal.pack import estimate_tokens, render_pack
from prebuttal.venues import get_venue


def _paper(big: bool = False) -> StructuredPaper:
    fill = " ".join(f"word{i}" for i in range(4000)) if big else "short body"
    return StructuredPaper(
        title="Pack Test",
        abstract="An abstract with numbers 91.2.",
        sections=[
            Section(1, "1", "Introduction", fill),
            Section(1, "2", "Method", fill),
            Section(1, "3", "Related Work", fill),
            Section(2, "A.1", "Extra Details", fill, appendix=True),
        ],
        tables=[
            Table(
                number="1",
                caption="Main results",
                header=["M", "Acc"],
                rows=[["a", "97.3"], ["b", "96.1"]],
                source="latex-tabular",
            ),
            Table(
                number="2",
                caption="Ablations",
                header=["k", "Acc"],
                rows=[["1", "95.0"], ["2", "97.3"]],
                source="latex-tabular",
            ),
        ],
        figures=[],
        source_type="latex",
        source_path="test",
    )


def test_pack_keeps_tables_under_tight_budget():
    paper = _paper(big=True)
    pack = render_pack(paper, budget_chars=12_000)
    assert len(pack) <= 12_000
    # tables are never truncated
    assert pack.count("97.3") >= 2
    assert "Main results" in pack and "Ablations" in pack
    assert "[float" not in pack  # markers only when float envs; latex path adds none here
    assert "chars elided" in pack  # something was elided


def test_pack_full_when_within_budget():
    pack = render_pack(_paper(big=True), budget_chars=200_000)
    assert "chars elided" not in pack
    assert "word3999" in pack  # full body kept
    assert "Complete tables" in pack


def test_pack_deterministic():
    a = render_pack(_paper(big=True), budget_chars=8_000)
    b = render_pack(_paper(big=True), budget_chars=8_000)
    assert a == b


def test_estimate_tokens():
    assert estimate_tokens(4000) == 1000


# ------------------------------------------------------------- JSON extraction


def test_extract_json_plain():
    assert extract_json_object('{"rating": 5}') == {"rating": 5}


def test_extract_json_fenced():
    text = 'Here is my review:\n```json\n{"rating": 6, "notes": "ok"}\n```\nthanks'
    assert extract_json_object(text)["rating"] == 6


def test_extract_json_with_prose_and_nested():
    text = (
        "Sure! My review follows.\n"
        '{"summary": "the paper {has braces} inside", "strengths": ["a", "b"], '
        '"nested": {"x": 1}}\n'
        "Hope this helps."
    )
    obj = extract_json_object(text)
    assert obj["nested"] == {"x": 1}
    assert obj["summary"].startswith("the paper")


def test_extract_json_takes_first_valid():
    text = '{"a": 1} then {"b": 2}'
    assert extract_json_object(text) == {"a": 1}


def test_extract_json_invalid():
    assert extract_json_object("no json here at all") is None
    assert extract_json_object("") is None
    assert extract_json_object("{broken json") is None


def test_coerce_fields():
    venue = get_venue("iclr")
    payload = {
        "summary": 123,  # coerced to string
        "strengths": "single string",  # coerced to list
        "weaknesses": ["w1", "", "w2"],
        "questions": [],
        "limitations": None,
        "rating": "7",  # numeric string
        "confidence": 99,  # clamped to 5
    }
    f = coerce_fields(payload, venue)
    assert f["summary"] == "123"
    assert f["strengths"] == ["single string"]
    assert f["weaknesses"] == ["w1", "w2"]
    assert f["rating"] == 7.0
    assert f["confidence"] == 5.0


def test_coerce_float_clamp_int():
    venue = get_venue("neurips")
    f = coerce_fields({"rating": 4.6}, venue)  # int scale -> rounds
    assert f["rating"] == 5.0
    arr = get_venue("acl")
    f2 = coerce_fields({"overall_assessment": 2.5}, arr)  # half-steps allowed
    assert f2["overall_assessment"] == 2.5
    f3 = coerce_fields({"overall_assessment": 9}, arr)
    assert f3["overall_assessment"] == 5.0
