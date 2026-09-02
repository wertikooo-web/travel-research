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


def test_basics_http_failure_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await research_destination_basics("Tenerife", "ES", client)

    with pytest.raises(DestinationBasicsError):
        asyncio.run(run())
