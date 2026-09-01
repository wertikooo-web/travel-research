import pytest
from pydantic import ValidationError

from app.schemas import Traveller, TripBrief


def test_brief_defaults_to_empty_not_invented():
    brief = TripBrief()
    assert brief.travellers == []
    assert brief.origin is None
    assert brief.budget is None
    assert brief.hotel is None


def test_traveller_iso_codes_normalized():
    t = Traveller(citizenships=["md", " ro "], travel_passport="ro")
    assert t.citizenships == ["MD", "RO"]
    assert t.travel_passport == "RO"


def test_traveller_multiple_passports_all_kept():
    t = Traveller(citizenships=["MD", "RO"], travel_passport=None)
    assert t.citizenships == ["MD", "RO"]
    assert t.travel_passport is None


def test_traveller_unspecified_fields_are_null():
    t = Traveller(type="adult")
    assert t.citizenships is None
    assert t.travel_passport is None
    assert t.passport_type is None


def test_invalid_traveller_type_rejected():
    with pytest.raises(ValidationError):
        Traveller(type="robot")


def test_child_with_age():
    t = Traveller(type="child", age=8)
    assert t.type == "child"
    assert t.age == 8
