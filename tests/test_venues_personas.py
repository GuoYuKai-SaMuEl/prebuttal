import pytest

from prebuttal.personas import available_personas, load_persona
from prebuttal.venues import VENUES, get_venue


def test_all_four_venues():
    assert set(VENUES) == {"neurips", "iclr", "icml", "acl"}
    for _key, venue in VENUES.items():
        assert venue.rating_field.max >= 5
        assert venue.confidence_key is not None
        # form files exist and describe the scale
        form = venue.form_text()
        assert len(form) > 200
        assert "Rating" in form or "Overall Assessment" in form
        # JSON spec mentions every field key
        spec = venue.json_spec()
        for f in venue.fields:
            assert f'"{f.key}"' in spec


def test_rating_scales():
    assert VENUES["neurips"].rating_field.max == 6
    assert VENUES["neurips"].rating_field.anchors["1"] == "Trivial or wrong"
    assert VENUES["iclr"].rating_field.max == 10
    assert "Award quality" in VENUES["iclr"].rating_field.anchors["10"]
    assert VENUES["icml"].rating_field.max == 10
    assert VENUES["acl"].rating_key == "overall_assessment"
    assert VENUES["acl"].rating_field.allow_float  # ARR half-steps
    assert VENUES["acl"].field("soundness").max == 5


def test_get_venue_unknown():
    with pytest.raises(KeyError):
        get_venue("cvpr")


def test_personas():
    personas = available_personas()
    assert set(personas) >= {
        "senior_kind",
        "adversarial",
        "detail_obsessive",
        "area_chair",
        "paper_roast",
    }
    for p in personas:
        text = load_persona(p)
        assert len(text) > 200
    with pytest.raises(KeyError):
        load_persona("does_not_exist")
