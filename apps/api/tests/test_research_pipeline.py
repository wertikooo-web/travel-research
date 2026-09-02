import asyncio
from datetime import date

import httpx

from app.research.research_pipeline import research_candidate, summarize_run_status
from app.schemas import Candidate, Dates, DestinationResearch, Preferences, Traveller, TripBrief

WIKITEXT_TH = """
==Visa requirements==
{| class="sortable wikitable"
|-
| {{flag|Thailand}}
| {{yes2|eVisa}}<ref>x</ref>
| 30 days
|
|}
"""

WIKITEXT_RO_TH = """
==Visa requirements==
{| class="sortable wikitable"
|-
| {{flag|Thailand}}
| {{yes|Visa not required}}<ref>x</ref>
| 90 days
|
|}
"""

GEO_RESULT = [{"name": "Phuket", "latitude": 7.88, "longitude": 98.39, "country_code": "TH", "country": "Thailand", "timezone": "Asia/Bangkok"}]
WEATHER_RESULT = {
    "daily": {
        "time": ["2026-10-20"],
        "temperature_2m_max": [31.0],
        "temperature_2m_min": [25.0],
        "precipitation_sum": [0.0],
    }
}
MARINE_RESULT = {"daily": {"sea_surface_temperature_max": [29.0]}}


def _make_transport(*, weather_fails=False, wikipedia_fails=False):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "geocoding-api" in url:
            return httpx.Response(200, json={"results": GEO_RESULT})
        if "archive-api" in url:
            if weather_fails:
                return httpx.Response(503)
            return httpx.Response(200, json=WEATHER_RESULT)
        if "marine-api" in url:
            if weather_fails:
                return httpx.Response(503)
            return httpx.Response(200, json=MARINE_RESULT)
        if "en.wikipedia.org" in url:
            if wikipedia_fails:
                return httpx.Response(503)
            if "Moldovan" in url:
                return httpx.Response(200, json={"parse": {"wikitext": WIKITEXT_TH}})
            if "Romanian" in url:
                return httpx.Response(200, json={"parse": {"wikitext": WIKITEXT_RO_TH}})
            return httpx.Response(200, json={"parse": {"wikitext": WIKITEXT_TH}})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _candidate():
    return Candidate(
        id="cand_1", destination_name="Phuket", country_code="TH", reason_to_check="beach", source="llm", candidate_category="core"
    )


def test_full_success_all_components():
    brief = TripBrief(
        dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 20)),
        travellers=[Traveller(id="t1", type="adult", citizenships=["MD"], travel_passport="MD")],
    )

    async def run():
        async with httpx.AsyncClient(transport=_make_transport()) as client:
            return await research_candidate(_candidate(), brief, client)

    result = asyncio.run(run())
    assert result.basics_status == "success"
    assert result.weather_status == "success"
    assert result.visa_status == "success"
    assert result.visa_results[0].entry_methods.status == "known"
    assert [m.method for m in result.visa_results[0].entry_methods.value] == ["evisa"]


def test_weather_failure_does_not_sink_basics_or_visa():
    brief = TripBrief(
        dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 20)),
        travellers=[Traveller(id="t1", type="adult", citizenships=["MD"], travel_passport="MD")],
    )

    async def run():
        async with httpx.AsyncClient(transport=_make_transport(weather_fails=True)) as client:
            return await research_candidate(_candidate(), brief, client)

    result = asyncio.run(run())
    assert result.basics_status == "success"
    assert result.weather_status == "failed"
    assert any("weather" in e for e in result.errors)
    assert result.visa_status == "success"  # unaffected by the weather failure


def test_visa_source_failure_does_not_sink_basics_or_weather():
    brief = TripBrief(
        dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 20)),
        travellers=[Traveller(id="t1", type="adult", citizenships=["MD"], travel_passport="MD")],
    )

    async def run():
        async with httpx.AsyncClient(transport=_make_transport(wikipedia_fails=True)) as client:
            return await research_candidate(_candidate(), brief, client)

    result = asyncio.run(run())
    assert result.basics_status == "success"
    assert result.weather_status == "success"
    assert result.visa_results[0].entry_methods.status == "unavailable"


def test_missing_passport_is_unknown_not_inferred_and_does_not_crash():
    brief = TripBrief(
        dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 20)),
        travellers=[Traveller(id="t1", type="adult")],  # no citizenships, no travel_passport
    )

    async def run():
        async with httpx.AsyncClient(transport=_make_transport()) as client:
            return await research_candidate(_candidate(), brief, client)

    result = asyncio.run(run())
    assert len(result.visa_results) == 1
    assert result.visa_results[0].entry_methods.status == "unknown"
    assert result.visa_results[0].passport_country is None
    assert any("no passport info" in w for w in result.warnings)


def test_mixed_travellers_get_independent_visa_results():
    brief = TripBrief(
        dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 20)),
        travellers=[
            Traveller(id="t1", type="adult", citizenships=["MD"], travel_passport="MD"),
            Traveller(id="t2", type="adult", citizenships=["RO"], travel_passport="RO"),
        ],
    )

    async def run():
        async with httpx.AsyncClient(transport=_make_transport()) as client:
            return await research_candidate(_candidate(), brief, client)

    result = asyncio.run(run())
    assert len(result.visa_results) == 2
    md_result = next(v for v in result.visa_results if v.passport_country == "MD")
    ro_result = next(v for v in result.visa_results if v.passport_country == "RO")
    md_methods = [m.method for m in md_result.entry_methods.value]
    ro_methods = [m.method for m in ro_result.entry_methods.value]
    assert md_methods == ["evisa"]  # MD needs eVisa for Thailand
    assert ro_methods == ["visa_free"]  # RO doesn't
    assert md_methods != ro_methods  # no global trip-level shortcut


def test_dual_passport_traveller_gets_a_result_per_passport():
    brief = TripBrief(
        dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 20)),
        travellers=[Traveller(id="t1", type="adult", citizenships=["MD", "RO"], travel_passport="RO")],
    )

    async def run():
        async with httpx.AsyncClient(transport=_make_transport()) as client:
            return await research_candidate(_candidate(), brief, client)

    result = asyncio.run(run())
    assert {v.passport_country for v in result.visa_results} == {"MD", "RO"}


def test_summarize_run_status_all_success():
    results = [
        DestinationResearch(candidate_id="c1", basics_status="success", weather_status="success", visa_status="success")
    ]
    assert summarize_run_status(results) == "completed"


def test_summarize_run_status_partial_when_one_component_degraded():
    results = [
        DestinationResearch(candidate_id="c1", basics_status="success", weather_status="failed", visa_status="success")
    ]
    assert summarize_run_status(results) == "partial"


def test_summarize_run_status_empty_results_is_failed():
    assert summarize_run_status([]) == "failed"
