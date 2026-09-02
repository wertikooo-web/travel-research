import asyncio
from datetime import date

import httpx
import pytest

from app.research.weather import (
    OpenMeteoWeatherProvider,
    WeatherProviderError,
    _historical_ranges,
    _resolve_period,
)
from app.schemas import Dates, TripBrief


def test_resolve_period_prefers_exact_dates():
    brief = TripBrief(dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 31), month=10))
    assert _resolve_period(brief) == (10, 20, 10, 31)


def test_resolve_period_falls_back_to_month_only():
    brief = TripBrief(dates=Dates(month=2))
    assert _resolve_period(brief) == (2, 1, 2, 28)


def test_resolve_period_none_when_nothing_stated():
    assert _resolve_period(TripBrief(dates=Dates())) is None
    assert _resolve_period(TripBrief(dates=None)) is None


def test_historical_ranges_uses_past_years_only():
    ranges = _historical_ranges((10, 20, 10, 31), years_back=3)
    assert len(ranges) == 3
    this_year = date.today().year
    for start, end in ranges:
        assert start.year < this_year
        assert start.month == 10 and start.day == 20
        assert end.month == 10 and end.day == 31


def _mock_transport(archive_ok=True, marine_ok=True):
    def handler(request: httpx.Request) -> httpx.Response:
        if "archive-api" in str(request.url):
            if not archive_ok:
                return httpx.Response(503, json={"error": "unavailable"})
            return httpx.Response(
                200,
                json={
                    "daily": {
                        "time": ["2025-10-20", "2025-10-21"],
                        "temperature_2m_max": [24.0, 26.0],
                        "temperature_2m_min": [16.0, 18.0],
                        "precipitation_sum": [0.0, 2.0],
                    }
                },
            )
        if "marine-api" in str(request.url):
            if not marine_ok:
                return httpx.Response(503, json={"error": "unavailable"})
            return httpx.Response(200, json={"daily": {"sea_surface_temperature_max": [23.0, 23.5]}})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_weather_success_with_sea_temp():
    brief = TripBrief(dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 21)))

    async def run():
        async with httpx.AsyncClient(transport=_mock_transport()) as client:
            return await OpenMeteoWeatherProvider().research(28.3, -16.5, brief, client)

    facts, evidence = asyncio.run(run())
    assert facts.period_basis == "historical_climate"
    assert facts.day_temp_c.status == "known"
    assert facts.day_temp_c.value == 25.0
    assert facts.sea_temp_c.status == "known"
    assert len(facts.day_temp_c.evidence) == 1
    assert facts.day_temp_c.evidence[0].source_type == "weather_provider"


def test_weather_sea_temp_unavailable_not_invented_when_marine_fails():
    brief = TripBrief(dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 21)))

    async def run():
        async with httpx.AsyncClient(transport=_mock_transport(marine_ok=False)) as client:
            return await OpenMeteoWeatherProvider().research(28.3, -16.5, brief, client)

    facts, _ = asyncio.run(run())
    assert facts.day_temp_c.status == "known"  # air data still fine
    assert facts.sea_temp_c.status == "unavailable"
    assert facts.sea_temp_c.value is None


def test_weather_all_sources_fail_raises_not_silently_empty():
    brief = TripBrief(dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 21)))

    async def run():
        async with httpx.AsyncClient(transport=_mock_transport(archive_ok=False)) as client:
            return await OpenMeteoWeatherProvider().research(28.3, -16.5, brief, client)

    with pytest.raises(WeatherProviderError):
        asyncio.run(run())


def test_weather_unknown_when_brief_has_no_period_and_makes_no_requests():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"daily": {}})

    brief = TripBrief(dates=None)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await OpenMeteoWeatherProvider().research(28.3, -16.5, brief, client)

    facts, _ = asyncio.run(run())
    assert facts.day_temp_c.status == "unknown"
    assert facts.sea_temp_c.status == "unknown"
    assert calls == []  # never invented a period to query for
