import asyncio

import httpx
import pytest

from app.research.destination_basics import DestinationBasicsError, research_destination_basics


def _mock_transport(results):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": results})

    return httpx.MockTransport(handler)


def test_basics_success_picks_matching_country_code():
    results = [
        {"name": "Malta", "latitude": 10.0, "longitude": 10.0, "country_code": "US", "country": "United States"},
        {"name": "Malta", "latitude": 35.9, "longitude": 14.4, "country_code": "MT", "country": "Malta", "timezone": "Europe/Malta"},
    ]

    async def run():
        async with httpx.AsyncClient(transport=_mock_transport(results)) as client:
            return await research_destination_basics("Malta", "MT", client)

    identity, evidence = asyncio.run(run())
    assert identity.country_code == "MT"
    assert identity.coordinates.lat == 35.9
    assert evidence.source_type == "geo_provider"
    assert evidence.confidence == "high"


def test_basics_no_results_raises_not_a_guess():
    async def run():
        async with httpx.AsyncClient(transport=_mock_transport([])) as client:
            return await research_destination_basics("Nowhereville", None, client)

    with pytest.raises(DestinationBasicsError):
        asyncio.run(run())


def test_basics_falls_back_to_country_centroid_when_name_not_indexed():
    # e.g. an LLM-generated Cyrillic destination name Open-Meteo's index has
    # nothing for — losing the whole identity is worse than a coarser,
    # still-sourced country-centroid fallback
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        name = httpx.QueryParams(request.url.query).get("name")
        calls.append(name)
        if name == "Egypt":
            return httpx.Response(
                200,
                json={"results": [{"name": "Egypt", "latitude": 26.0, "longitude": 30.0, "country_code": "EG", "country": "Egypt"}]},
            )
        return httpx.Response(200, json={"results": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await research_destination_basics("Египет", "EG", client)

    identity, evidence = asyncio.run(run())
    assert calls == ["Египет", "Egypt"]  # tried the given name first, then the country fallback
    assert identity.country_code == "EG"
    assert identity.coordinates.lat == 26.0
    assert evidence.confidence == "medium"  # coarser than a direct match, not silently "high"
    assert "fallback" in evidence.title.lower()


def test_basics_no_country_code_means_no_fallback_attempted():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(httpx.QueryParams(request.url.query).get("name"))
        return httpx.Response(200, json={"results": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await research_destination_basics("Египет", None, client)

    with pytest.raises(DestinationBasicsError):
        asyncio.run(run())
    assert calls == ["Египет"]  # no country_code to fall back with — one attempt only


def test_basics_http_failure_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await research_destination_basics("Tenerife", "ES", client)

    with pytest.raises(DestinationBasicsError):
        asyncio.run(run())
