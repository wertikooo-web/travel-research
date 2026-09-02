import pytest
from pydantic import ValidationError

from app.schemas import DestinationPick, EntryMethod, Evidence, FactResult, Dates, Traveller, TripBrief, VisaResult


def test_brief_defaults_to_empty_not_invented():
    brief = TripBrief()
    assert brief.travellers == []
    assert brief.origin is None
    assert brief.budget is None
    assert brief.hotel is None
    assert brief.destination_picks == []


def test_old_saved_brief_json_without_destination_picks_still_loads():
    old_json = {
        "origin": {"text": "Кишинёв", "iata": None},
        "travellers": [{"id": "traveller_1", "type": "adult"}],
        "preferences": {"avoid": [], "prefer": []},
    }
    brief = TripBrief.model_validate(old_json)
    assert brief.destination_picks == []
    assert brief.origin.text == "Кишинёв"


def test_destination_pick_normalizes_country_code_and_trims_text():
    pick = DestinationPick(text="  Thailand  ", country_code="th")
    assert pick.text == "Thailand"
    assert pick.country_code == "TH"


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


def test_dates_month_accepts_1_to_12():
    d = Dates(month=10)
    assert d.month == 10


def test_dates_month_rejects_out_of_range():
    with pytest.raises(ValidationError):
        Dates(month=13)
    with pytest.raises(ValidationError):
        Dates(month=0)


def test_old_dates_json_without_month_still_loads():
    d = Dates.model_validate({"start": None, "end": None, "flex_days": None})
    assert d.month is None


def test_fact_result_unknown_has_no_value_and_no_evidence():
    fact = FactResult(status="unknown")
    assert fact.value is None
    assert fact.evidence == []


def test_fact_result_known_is_distinguishable_from_unknown():
    ev = Evidence(source_type="weather_provider", provider="Open-Meteo", retrieved_at="2026-01-01T00:00:00Z")
    known = FactResult(status="known", value=False, evidence=[ev])
    unknown = FactResult(status="unknown")
    # "verified false" must never look like "we don't know" — the whole point of FactResult
    assert known.status != unknown.status
    assert known.value is False
    assert unknown.value is None


def test_fact_result_known_sourced_fact_requires_evidence():
    with pytest.raises(ValidationError):
        FactResult(status="known", value=1)  # no evidence and not marked derived


def test_fact_result_known_derived_fact_does_not_require_evidence():
    fact = FactResult(status="known", value=1, is_derived=True)
    assert fact.value == 1
    assert fact.evidence == []


def test_fact_result_known_requires_a_value():
    with pytest.raises(ValidationError):
        FactResult(status="known", is_derived=True)  # no value at all


def test_fact_result_unknown_must_not_carry_a_value():
    with pytest.raises(ValidationError):
        FactResult(status="unknown", value=1)


def test_fact_result_conflicting_requires_evidence():
    with pytest.raises(ValidationError):
        FactResult(status="conflicting")

    ev = Evidence(source_type="secondary_travel_site", provider="Wikipedia", retrieved_at="2026-01-01T00:00:00Z")
    conflicting = FactResult(status="conflicting", evidence=[ev], note="two sources disagree")
    assert conflicting.evidence == [ev]


def test_visa_result_can_hold_multiple_distinct_entry_methods():
    ev = Evidence(source_type="secondary_travel_site", provider="Wikipedia", retrieved_at="2026-01-01T00:00:00Z")
    vr = VisaResult(
        traveller_id="t1",
        passport_country="MD",
        destination_country="EG",
        entry_methods=FactResult(
            status="known",
            value=[EntryMethod(method="visa_on_arrival", allowed_stay_days=30), EntryMethod(method="evisa", allowed_stay_days=30)],
            evidence=[ev],
        ),
    )
    methods = {m.method for m in vr.entry_methods.value}
    assert methods == {"visa_on_arrival", "evisa"}, "a composite source statement must not collapse to one method"


def test_evidence_requires_source_type_and_provider():
    with pytest.raises(ValidationError):
        Evidence(provider="Wikipedia", retrieved_at="2026-01-01T00:00:00Z")  # missing source_type

    ev = Evidence(source_type="secondary_travel_site", provider="Wikipedia", retrieved_at="2026-01-01T00:00:00Z")
    assert ev.confidence == "medium"  # sensible default, never silently "high"
