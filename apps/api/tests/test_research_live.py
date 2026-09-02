"""Live Milestone 3 validation against real Open-Meteo + Wikipedia (+ Claude
for the deterministic-classifier fallback, when needed). Skipped without
ANTHROPIC_API_KEY for consistency with the other live suites, even though
most of this module doesn't strictly require it.
"""

import asyncio
import os
from datetime import date

import httpx
import pytest

from app.research.research_pipeline import research_candidate
from app.schemas import Candidate, Dates, Traveller, TripBrief

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live research validation",
)

HEADERS = {"User-Agent": "TripMatchResearchBot/0.1 (https://github.com/wertikooo-web/travel-research; tests)"}


def _run(candidate, brief):
    async def go():
        async with httpx.AsyncClient(headers=HEADERS) as client:
            return await research_candidate(candidate, brief, client)

    return asyncio.run(go())


def test_case_a_eu_beach_destination_fully_researched():
    """Tenerife (EU/Spain) — a straightforward case."""
    candidate = Candidate(
        id="c1", destination_name="Tenerife", country_code="ES", reason_to_check="x", source="llm", candidate_category="core"
    )
    brief = TripBrief(
        dates=Dates(month=10),
        travellers=[Traveller(id="t1", type="adult", citizenships=["MD"], travel_passport="MD")],
    )
    result = _run(candidate, brief)

    assert result.basics_status == "success"
    assert result.identity.country_code == "ES"
    assert result.weather_status in ("success", "partial")
    assert result.weather.period_basis == "historical_climate"
    assert result.weather.day_temp_c.status == "known"
    assert len(result.weather.day_temp_c.evidence) >= 1
    assert result.weather.day_temp_c.evidence[0].url  # a real, checkable URL

    md_visa = result.visa_results[0]
    assert md_visa.entry_methods.status in ("known", "unknown", "unavailable")
    if md_visa.entry_methods.status == "known":
        assert md_visa.entry_methods.evidence[0].source_type == "secondary_travel_site"
        assert "wikipedia.org" in md_visa.entry_methods.evidence[0].url


def test_case_b_non_eu_beach_destination_thailand():
    candidate = Candidate(
        id="c1", destination_name="Phuket", country_code="TH", reason_to_check="x", source="llm", candidate_category="core"
    )
    brief = TripBrief(
        dates=Dates(start=date(2026, 12, 1), end=date(2026, 12, 10)),
        travellers=[Traveller(id="t1", type="adult", citizenships=["MD"], travel_passport="MD")],
    )
    result = _run(candidate, brief)

    assert result.basics_status == "success"
    assert result.weather.sea_temp_c.status in ("known", "unavailable")  # never invented either way


def test_case_c_md_vs_ro_passport_diverge_for_the_same_destination():
    """The exact case the product spec flags: MD and RO must NOT collapse
    into one group verdict — they can, and here do, disagree."""
    candidate = Candidate(
        id="c1", destination_name="Thailand", country_code="TH", reason_to_check="x", source="llm", candidate_category="core"
    )
    brief = TripBrief(
        dates=Dates(month=11),
        travellers=[
            Traveller(id="t1", type="adult", citizenships=["MD"], travel_passport="MD"),
            Traveller(id="t2", type="adult", citizenships=["RO"], travel_passport="RO"),
        ],
    )
    result = _run(candidate, brief)

    md = next(v for v in result.visa_results if v.passport_country == "MD")
    ro = next(v for v in result.visa_results if v.passport_country == "RO")
    assert md.entry_methods.status == "known" and ro.entry_methods.status == "known"
    md_methods = {m.method for m in md.entry_methods.value}
    ro_methods = {m.method for m in ro.entry_methods.value}
    assert md_methods != ro_methods, "MD and RO are expected to genuinely differ for Thailand"


def test_case_d_missing_passport_never_inferred_from_origin():
    candidate = Candidate(
        id="c1", destination_name="Malta", country_code="MT", reason_to_check="x", source="llm", candidate_category="core"
    )
    brief = TripBrief(
        origin={"text": "Chisinau"},
        dates=Dates(month=6),
        travellers=[Traveller(id="t1", type="adult")],  # no citizenship at all
    )
    result = _run(candidate, brief)

    assert len(result.visa_results) == 1
    assert result.visa_results[0].entry_methods.status == "unknown"
    assert result.visa_results[0].passport_country is None


def test_case_f_real_composite_entry_methods_both_preserved():
    """A real source stating more than one valid entry method must come back
    with both — not whichever keyword a naive scan hits first. Egypt's row
    on the Moldovan-citizens page states "Visa on arrival/eVisa"."""
    candidate = Candidate(
        id="c1", destination_name="Hurghada", country_code="EG", reason_to_check="x", source="llm", candidate_category="core"
    )
    brief = TripBrief(
        dates=Dates(month=10),
        travellers=[Traveller(id="t1", type="adult", citizenships=["MD"], travel_passport="MD")],
    )
    result = _run(candidate, brief)

    md_visa = result.visa_results[0]
    assert md_visa.entry_methods.status == "known"
    methods = {m.method for m in md_visa.entry_methods.value}
    assert methods == {"visa_on_arrival", "evisa"}, f"expected both real options preserved, got {methods}"


def test_case_e_partial_dates_use_historical_climate_not_invented_exact_dates():
    candidate = Candidate(
        id="c1", destination_name="Bali", country_code="ID", reason_to_check="x", source="llm", candidate_category="core"
    )
    brief = TripBrief(
        dates=Dates(month=2),  # "around two weeks in February" -> month known, no exact days
        travellers=[Traveller(id="t1", type="adult", citizenships=["MD"], travel_passport="MD")],
    )
    result = _run(candidate, brief)

    assert result.weather.period_basis == "historical_climate"
    assert "Feb" in result.weather.period_description
