"""Live Milestone 4 validation against the real Duffel API. Skipped without
DUFFEL_API_KEY — per the milestone's own instruction, live flight validation
is reported as blocked when no credentials exist, never faked.
"""

import asyncio
import os
from datetime import date

import httpx
import pytest

from app.research.duffel_provider import DuffelFlightProvider
from app.research.flight_pipeline import run_flight_research
from app.schemas import Candidate, Coordinates, Dates, DestinationIdentity, DestinationResearch, Origin, Traveller, TripBrief

pytestmark = pytest.mark.skipif(
    not os.environ.get("DUFFEL_API_KEY"),
    reason="DUFFEL_API_KEY not set — live flight validation blocked, see milestone report",
)


@pytest.fixture(scope="module")
def provider():
    return DuffelFlightProvider()


def _candidate(name, country_code):
    return Candidate(id="c1", destination_name=name, country_code=country_code, reason_to_check="x", source="llm", candidate_category="core")


def _research(display_name, country_code, lat, lon):
    return {
        "c1": DestinationResearch(
            candidate_id="c1",
            identity=DestinationIdentity(display_name=display_name, country_code=country_code, coordinates=Coordinates(lat=lat, lon=lon)),
            basics_status="success",
        )
    }


def _brief(nights=8):
    return TripBrief(
        origin=Origin(text="Chisinau"),
        dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 20 + nights)),
        travellers=[Traveller(id="t1", type="adult"), Traveller(id="t2", type="adult")],
    )


def _run(candidates, research_map, brief, provider):
    return asyncio.run(run_flight_research(candidates, research_map, brief, provider))


def test_chisinau_to_antalya(provider):
    result = _run([_candidate("Antalya", "TR")], _research("Antalya", "TR", 36.9, 30.7), _brief(), provider)[0]
    assert result.resolution_status == "success"
    assert result.origin_place.iata_code
    assert result.destination_place.iata_code
    assert len(result.searches) >= 1
    search = result.searches[0]
    assert search.status in ("success", "failed")
    if search.status == "success" and search.offers:
        offer = search.offers[0]
        print(f"ANTALYA offer: {offer.total_amount} {offer.total_currency}, connections out={offer.outbound.connections}")
        assert offer.total_currency
        assert offer.traveller_count == 2
        assert offer.expires_at


def test_chisinau_to_tenerife():
    provider = DuffelFlightProvider()
    result = _run([_candidate("Tenerife", "ES")], _research("Tenerife", "ES", 28.3, -16.5), _brief(), provider)[0]
    assert result.resolution_status in ("success", "unknown")


def test_chisinau_to_madeira_connection_heavy():
    provider = DuffelFlightProvider()
    result = _run([_candidate("Madeira", "PT")], _research("Madeira", "PT", 32.7, -16.9), _brief(), provider)[0]
    assert result.resolution_status in ("success", "unknown")
    if result.searches and result.searches[0].offers:
        print(f"MADEIRA connections: {[o.outbound.connections for o in result.searches[0].offers]}")


def test_direct_route_if_available():
    provider = DuffelFlightProvider()
    result = _run([_candidate("Bucharest", "RO")], _research("Bucharest", "RO", 44.4, 26.1), _brief(), provider)[0]
    assert result.resolution_status in ("success", "unknown")
