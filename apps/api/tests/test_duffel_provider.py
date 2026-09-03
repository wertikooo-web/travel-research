import asyncio
from datetime import date

import httpx
import pytest

from app.research.duffel_provider import (
    DuffelError,
    DuffelFlightProvider,
    DuffelPlaceNotFoundError,
    FakeFlightProvider,
    _parse_duration_minutes,
    normalize_offer,
)
from app.schemas import FlightPassenger, FlightSearchPlan, TransportPlace

# --- duration parsing ---------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("PT5H30M", 330),
        ("PT45M", 45),
        ("PT2H", 120),
        ("P1DT2H", 1560),
        (None, None),
        ("garbage", None),
    ],
)
def test_parse_duration_minutes(value, expected):
    assert _parse_duration_minutes(value) == expected


# --- offer normalization (realistic Duffel-shaped fixture) --------------

RAW_OFFER_ROUND_TRIP = {
    "id": "off_00009hthhsUZ8W4LxQgocA",
    "total_amount": "652.44",
    "total_currency": "EUR",
    "cabin_class": "economy",
    "expires_at": "2026-09-05T12:00:00Z",
    "slices": [
        {
            "duration": "PT3H20M",
            "segments": [
                {
                    "origin": {"iata_code": "RMO"},
                    "destination": {"iata_code": "AYT"},
                    "departing_at": "2026-10-20T08:00:00",
                    "arriving_at": "2026-10-20T11:20:00",
                    "operating_carrier": {"name": "Turkish Airlines"},
                    "marketing_carrier": {"name": "Turkish Airlines"},
                    "duration": "PT3H20M",
                }
            ],
        },
        {
            "duration": "PT9H15M",
            "segments": [
                {
                    "origin": {"iata_code": "AYT"},
                    "destination": {"iata_code": "IST"},
                    "departing_at": "2026-10-28T13:00:00",
                    "arriving_at": "2026-10-28T14:10:00",
                    "operating_carrier": {"name": "Turkish Airlines"},
                    "marketing_carrier": {"name": "Turkish Airlines"},
                    "duration": "PT1H10M",
                },
                {
                    "origin": {"iata_code": "IST"},
                    "destination": {"iata_code": "RMO"},
                    "departing_at": "2026-10-28T16:00:00",
                    "arriving_at": "2026-10-28T18:05:00",
                    "operating_carrier": {"name": "Turkish Airlines"},
                    "marketing_carrier": {"name": "Turkish Airlines"},
                    "duration": "PT2H05M",
                },
            ],
        },
    ],
}


def test_normalize_direct_outbound_connecting_return():
    offer = normalize_offer(RAW_OFFER_ROUND_TRIP, traveller_count=2, retrieved_at="2026-09-02T00:00:00Z")
    assert offer.id == "off_00009hthhsUZ8W4LxQgocA"
    assert offer.total_amount == 652.44
    assert offer.total_currency == "EUR"
    assert offer.traveller_count == 2
    assert offer.expires_at == "2026-09-05T12:00:00Z"

    assert offer.outbound.connections == 0
    assert offer.outbound.duration_minutes == 200
    assert offer.outbound.segments[0].operating_carrier == "Turkish Airlines"

    assert offer.return_.connections == 1  # two segments -> one connection
    assert len(offer.return_.segments) == 2
    assert offer.return_.duration_minutes == 555


def test_normalize_offer_missing_segments_does_not_crash():
    raw = {"id": "off_empty", "total_amount": "100.00", "total_currency": "EUR", "slices": []}
    offer = normalize_offer(raw, traveller_count=1, retrieved_at="2026-09-02T00:00:00Z")
    assert offer.outbound.segments == []
    assert offer.return_ is None


# --- place resolution -----------------------------------------------------


def _places_transport(response_places, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if "places/suggestions" in str(request.url):
            return httpx.Response(status, json={"data": response_places})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_resolve_place_prefers_city_type_for_multi_airport_cities():
    places = [
        {"iata_code": "LGW", "type": "airport", "name": "London Gatwick", "iata_country_code": "GB"},
        {
            "iata_code": "LON",
            "type": "city",
            "name": "London",
            "iata_country_code": "GB",
            "airports": [{"iata_code": "LHR"}, {"iata_code": "LGW"}],
        },
    ]

    async def run():
        provider = DuffelFlightProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_places_transport(places)) as client:
            return await provider.resolve_place("London", None, client)

    place = asyncio.run(run())
    assert place.iata_code == "LON"
    assert place.type == "city"
    assert set(place.alternate_iata_codes) == {"LHR", "LGW"}


def test_resolve_place_disambiguates_by_country_code():
    places = [
        {"iata_code": "XYZ", "type": "airport", "name": "Somewhere", "iata_country_code": "US"},
        {"iata_code": "AYT", "type": "airport", "name": "Antalya", "iata_country_code": "TR"},
    ]

    async def run():
        provider = DuffelFlightProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_places_transport(places)) as client:
            return await provider.resolve_place("Antalya", "TR", client)

    place = asyncio.run(run())
    assert place.iata_code == "AYT"


def test_resolve_place_not_found_raises_never_guesses():
    async def run():
        provider = DuffelFlightProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_places_transport([])) as client:
            return await provider.resolve_place("Nowhereville", None, client)

    with pytest.raises(DuffelPlaceNotFoundError):
        asyncio.run(run())


def test_resolve_place_http_failure_is_duffel_error_not_not_found():
    async def run():
        provider = DuffelFlightProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_places_transport([], status=503)) as client:
            return await provider.resolve_place("Antalya", "TR", client)

    with pytest.raises(DuffelError):
        asyncio.run(run())


# --- search() -----------------------------------------------------------


def _search_transport(offers, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"data": {"id": "orq_123", "offers": offers}})

    return httpx.MockTransport(handler)


def _plan():
    return FlightSearchPlan(
        origin=TransportPlace(iata_code="RMO", type="airport", name="Chisinau"),
        destination=TransportPlace(iata_code="AYT", type="airport", name="Antalya", country_code="TR"),
        outbound_date=date(2026, 10, 20),
        return_date=date(2026, 10, 28),
        nights=8,
        date_variant="exact",
        passengers=[FlightPassenger(traveller_id="t1", type="adult")],
        cabin="economy",
        max_connections_sent=1,
        connection_policy="unspecified",
    )


# --- coordinate-based place resolution (Requirement 2/3/5) ----------------


def _coord_transport(response_places, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if "places/suggestions" in str(request.url):
            params = httpx.QueryParams(request.url.query)
            assert "lat" in params and "lng" in params and "rad" in params
            return httpx.Response(status, json={"data": response_places})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_resolve_place_by_coordinates_returns_nearby_airport():
    # test case C
    places = [{"iata_code": "HRG", "type": "airport", "name": "Hurghada", "iata_country_code": "EG", "distance": 12.4}]

    async def run():
        provider = DuffelFlightProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_coord_transport(places)) as client:
            return await provider.resolve_place_by_coordinates(27.25, 33.81, 100, client)

    place, meta = asyncio.run(run())
    assert place.iata_code == "HRG"
    assert place.resolved_via == "coordinates"
    assert place.distance_km == 12.4
    assert meta["radius_km"] == 100


def test_resolve_place_by_coordinates_sends_rad_in_metres_not_km():
    # live-Duffel regression: rad is documented (and confirmed against the
    # real API) in metres — a radius_km=100 call must send rad=100000, not
    # rad=100, or every real coordinate search silently returns zero results
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(httpx.QueryParams(request.url.query))
        return httpx.Response(200, json={"data": [{"iata_code": "HRG", "type": "airport", "name": "Hurghada", "iata_country_code": "EG"}]})

    async def run():
        provider = DuffelFlightProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await provider.resolve_place_by_coordinates(27.25, 33.81, 100, client)

    asyncio.run(run())
    assert captured["params"]["rad"] == "100000"


def test_resolve_place_by_coordinates_no_match_raises_never_guesses():
    # test case D
    async def run():
        provider = DuffelFlightProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_coord_transport([])) as client:
            return await provider.resolve_place_by_coordinates(0.0, 0.0, 100, client)

    with pytest.raises(DuffelPlaceNotFoundError):
        asyncio.run(run())


def test_resolve_place_by_coordinates_multiple_airports_deterministic_selection_preserves_alternates():
    # test case E: prefers the city aggregate and preserves the individual
    # airports as alternates rather than silently taking the first hit
    places = [
        {"iata_code": "LGW", "type": "airport", "name": "London Gatwick", "iata_country_code": "GB"},
        {
            "iata_code": "LON",
            "type": "city",
            "name": "London",
            "iata_country_code": "GB",
            "airports": [{"iata_code": "LHR"}, {"iata_code": "LGW"}],
        },
    ]

    async def run():
        provider = DuffelFlightProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_coord_transport(places)) as client:
            return await provider.resolve_place_by_coordinates(51.5, -0.1, 100, client)

    place, _ = asyncio.run(run())
    assert place.iata_code == "LON"
    assert set(place.alternate_iata_codes) == {"LHR", "LGW"}


def test_resolve_place_by_coordinates_http_failure_is_duffel_error():
    async def run():
        provider = DuffelFlightProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_coord_transport([], status=503)) as client:
            return await provider.resolve_place_by_coordinates(0.0, 0.0, 100, client)

    with pytest.raises(DuffelError):
        asyncio.run(run())


def test_resolve_place_tags_resolved_via_text_query():
    # test case F
    places = [{"iata_code": "AYT", "type": "airport", "name": "Antalya", "iata_country_code": "TR"}]

    async def run():
        provider = DuffelFlightProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_places_transport(places)) as client:
            return await provider.resolve_place("Antalya", "TR", client)

    place = asyncio.run(run())
    assert place.resolved_via == "text_query"


# --- FakeFlightProvider (test double) -------------------------------------


def test_fake_flight_provider_accepts_a_falsy_but_intentional_places_mapping():
    # `places or {}` would silently discard an empty-but-meaningful mapping
    # object (e.g. one whose .get() is overridden to answer any query) —
    # must use an explicit `is None` check instead
    class _AnyQueryPlaces(dict):
        def get(self, _key, _default=None):
            return TransportPlace(iata_code="AYT", type="airport", name="Antalya", country_code="TR")

    async def run():
        provider = FakeFlightProvider(places=_AnyQueryPlaces())
        return await provider.resolve_place("Whatever Destination Name", None, None)

    place = asyncio.run(run())
    assert place.iata_code == "AYT"


def test_fake_flight_provider_resolves_by_coordinates():
    place = TransportPlace(iata_code="HRG", type="airport", name="Hurghada", country_code="EG", resolved_via="coordinates")

    async def run():
        provider = FakeFlightProvider(places_by_coordinates={(27.25, 33.81): place})
        return await provider.resolve_place_by_coordinates(27.25, 33.81, 100, None)

    resolved, meta = asyncio.run(run())
    assert resolved.iata_code == "HRG"
    assert meta["radius_km"] == 100


def test_fake_flight_provider_coordinates_miss_raises_never_guesses():
    async def run():
        provider = FakeFlightProvider()
        return await provider.resolve_place_by_coordinates(0.0, 0.0, 100, None)

    with pytest.raises(DuffelPlaceNotFoundError):
        asyncio.run(run())


def test_search_normalizes_offers_and_reports_zero_offers_distinctly():
    async def run():
        provider = DuffelFlightProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_search_transport([])) as client:
            return await provider.search(_plan(), client)

    offers, meta = asyncio.run(run())
    assert offers == []  # a real, successful zero-result search
    assert meta["raw_offer_count"] == 0


def test_search_provider_failure_raises_duffel_error():
    async def run():
        provider = DuffelFlightProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_search_transport([], status=500)) as client:
            return await provider.search(_plan(), client)

    with pytest.raises(DuffelError):
        asyncio.run(run())


def test_search_sends_expected_slices_and_passengers():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"data": {"id": "orq_1", "offers": []}})

    async def run():
        provider = DuffelFlightProvider(api_key="test_key", api_version="v2")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await provider.search(_plan(), client)

    asyncio.run(run())
    slices = captured["body"]["data"]["slices"]
    assert slices[0] == {"origin": "RMO", "destination": "AYT", "departure_date": "2026-10-20"}
    assert slices[1] == {"origin": "AYT", "destination": "RMO", "departure_date": "2026-10-28"}
    assert captured["body"]["data"]["passengers"] == [{"type": "adult"}]
    assert captured["body"]["data"]["cabin_class"] == "economy"
    assert captured["body"]["data"]["max_connections"] == 1
    assert captured["headers"]["authorization"] == "Bearer test_key"
    assert captured["headers"]["duffel-version"] == "v2"
