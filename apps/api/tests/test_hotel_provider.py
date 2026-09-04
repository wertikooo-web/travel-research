import asyncio
from datetime import date

import httpx
import pytest

from app.research.hotel_provider import DuffelStaysError, DuffelStaysProvider, FakeHotelProvider
from app.schemas import Coordinates, HotelGuest, HotelRoom, HotelSearchPlan


def _plan(radius_km=15.0, guests=None, nights=8):
    return HotelSearchPlan(
        centre=Coordinates(lat=36.8969, lon=30.7133),
        radius_km=radius_km,
        check_in=date(2026, 10, 20),
        check_out=date(2026, 10, 28),
        nights=nights,
        date_variant="exact",
        rooms=1,
        guests=guests or [HotelGuest(type="adult")],
    )


def _search_transport(results, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if "stays/search" in str(request.url):
            return httpx.Response(status, json={"data": results})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


RAW_SEARCH_RESULT = {
    "id": "srr_0000ASVBuJVLdmqtZDJ4ca",
    "cheapest_rate_total_amount": "540.00",
    "cheapest_rate_currency": "EUR",
    "accommodation": {
        "id": "acc_0000AS",
        "name": "Beach Resort Antalya",
        "location": {
            "latitude": 36.9,
            "longitude": 30.71,
            "line_one": "Lara Beach",
            "country_code": "TR",
        },
        "rating": 5,
        "review_score": 8.7,
        "review_count": 1234,
        "amenities": [{"type": "pool", "description": "Outdoor pool"}],
        "photos": [{"url": "https://example.com/1.jpg"}],
    },
}


# --- search() request contract --------------------------------------------


def test_search_sends_radius_in_kilometres_no_conversion_and_documented_body_shape():
    # Duffel Stays' location.radius is documented in KILOMETRES — deliberately
    # different from Flights Places' /places/suggestions?rad=... (metres,
    # confirmed live in M4). radius_km must go straight through with no
    # *1000 conversion. This exercises the real provider.search() request-
    # building path, not a reimplementation of it.
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": []})

    async def run():
        provider = DuffelStaysProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await provider.search(_plan(radius_km=15.0), client)

    asyncio.run(run())
    body = captured["body"]["data"]
    assert body["check_in_date"] == "2026-10-20"
    assert body["check_out_date"] == "2026-10-28"
    assert body["rooms"] == 1
    assert body["guests"] == [{"type": "adult"}]
    assert body["location"]["radius"] == 15  # kilometres, unconverted — NOT 15000
    assert body["location"]["geographic_coordinates"] == {"latitude": 36.8969, "longitude": 30.7133}


def test_search_sends_child_guest_with_type_and_age_together():
    # Stays' documented guest contract sends type AND age together for a
    # child ({"age": 7, "type": "child"}) — the OPPOSITE of the Flights
    # offer_request passenger schema (M4), which forbids that exact
    # combination. Do not blindly reapply the Flights lesson to Stays: these
    # are two different Duffel products with two different contracts.
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": []})

    async def run():
        provider = DuffelStaysProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await provider.search(_plan(guests=[HotelGuest(type="adult"), HotelGuest(type="child", age=8)]), client)

    asyncio.run(run())
    guests = captured["body"]["data"]["guests"]
    assert guests == [{"type": "adult"}, {"type": "child", "age": 8}]


# --- search() response normalization ---------------------------------------


def test_search_normalizes_property_and_summary_fields():
    async def run():
        provider = DuffelStaysProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_search_transport([RAW_SEARCH_RESULT])) as client:
            return await provider.search(_plan(), client)

    properties, meta = asyncio.run(run())
    assert meta["raw_count"] == 1
    assert len(properties) == 1
    p = properties[0]
    assert p.search_result_id == "srr_0000ASVBuJVLdmqtZDJ4ca"
    assert p.cheapest_total_amount == 540.0
    assert p.cheapest_total_currency == "EUR"
    assert p.inspection_status == "summary_only"
    assert p.rooms == []  # summary result must never be pre-populated with room/rate facts
    assert p.rates == []
    assert p.property.name == "Beach Resort Antalya"
    assert p.property.coordinates.lat == 36.9
    assert p.property.star_rating.status == "known"
    assert p.property.star_rating.value == 5
    assert p.property.review_score.value == 8.7
    assert p.property.review_count.value == 1234
    assert p.evidence.provider == "Duffel Stays"


def test_search_missing_optional_property_fields_are_unknown_not_false():
    raw = {
        "id": "srr_2",
        "cheapest_rate_total_amount": "300.00",
        "cheapest_rate_currency": "EUR",
        "accommodation": {"id": "acc_2", "name": "No Rating Hotel", "location": {"latitude": 1.0, "longitude": 1.0}},
    }

    async def run():
        provider = DuffelStaysProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_search_transport([raw])) as client:
            return await provider.search(_plan(), client)

    properties, _ = asyncio.run(run())
    p = properties[0]
    assert p.property.star_rating.status == "unknown"
    assert p.property.review_score.status == "unknown"
    assert p.property.beachfront.status == "unknown"  # no amenity signal -> unknown, never False


def test_search_beachfront_verified_true_only_from_explicit_amenity():
    raw = dict(RAW_SEARCH_RESULT)
    raw["accommodation"] = dict(RAW_SEARCH_RESULT["accommodation"])
    raw["accommodation"]["amenities"] = [{"type": "private_beach", "description": "Private beach access"}]

    async def run():
        provider = DuffelStaysProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_search_transport([raw])) as client:
            return await provider.search(_plan(), client)

    properties, _ = asyncio.run(run())
    assert properties[0].property.beachfront.status == "known"
    assert properties[0].property.beachfront.value is True


def test_search_zero_results_is_success_not_failure():
    async def run():
        provider = DuffelStaysProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_search_transport([])) as client:
            return await provider.search(_plan(), client)

    properties, meta = asyncio.run(run())
    assert properties == []
    assert meta["raw_count"] == 0


def test_search_http_failure_raises_duffel_stays_error():
    async def run():
        provider = DuffelStaysProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_search_transport([], status=503)) as client:
            return await provider.search(_plan(), client)

    with pytest.raises(DuffelStaysError):
        asyncio.run(run())


# --- fetch_all_rates() -------------------------------------------------


RAW_FETCH_ALL_RATES = {
    "data": {
        "accommodation": {
            "id": "acc_0000AS",
            "name": "Beach Resort Antalya",
            "rooms": [
                {
                    "name": "Sea View Deluxe Room",
                    "description": "Spacious room with a private balcony",
                    "beds": [{"type": "king", "count": 1}],
                    "rates": [
                        {
                            "id": "rat_0000AS1",
                            "total_amount": "540.00",
                            "total_currency": "EUR",
                            "tax_amount": "40.00",
                            "fee_amount": "10.00",
                            "board_type": "breakfast",
                            "payment_type": "pay_now",
                            "quantity_available": 3,
                        }
                    ],
                },
                {
                    "name": "Standard Twin Room",
                    "description": "Two single beds",
                    "beds": [{"type": "single", "count": 2}],
                    "rates": [
                        {
                            "id": "rat_0000AS2",
                            "total_amount": "400.00",
                            "total_currency": "EUR",
                            "board_type": "room_only",
                            "payment_type": "pay_at_property",
                        }
                    ],
                },
            ],
        }
    }
}


def _fetch_transport(payload, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if "fetch_all_rates" in str(request.url):
            return httpx.Response(status, json=payload)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_fetch_all_rates_normalizes_rooms_and_rates_with_correct_scope():
    async def run():
        provider = DuffelStaysProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_fetch_transport(RAW_FETCH_ALL_RATES)) as client:
            return await provider.fetch_all_rates("srr_1", 8, client)

    rooms, rates, meta = asyncio.run(run())
    assert meta["raw_room_count"] == 2
    assert len(rooms) == 2
    assert len(rates) == 2

    sea_view_room = next(r for r in rooms if "Sea View" in r.name)
    assert sea_view_room.sea_view.status == "known"
    assert sea_view_room.sea_view.value is True
    assert sea_view_room.balcony.status == "known"  # "private balcony" in description
    assert sea_view_room.balcony.value is True

    twin_room = next(r for r in rooms if "Twin" in r.name)
    assert twin_room.sea_view.status == "unknown"  # no signal in name/description
    assert twin_room.balcony.status == "unknown"

    rate1 = next(r for r in rates if r.provider_rate_id == "rat_0000AS1")
    assert rate1.room_id == sea_view_room.provider_room_id
    assert rate1.total_amount == 540.0
    assert rate1.board_type.status == "known"
    assert rate1.board_type.value == "breakfast"  # a RATE fact — never promoted to the property
    assert rate1.payment_timing.value == "pay_now"
    assert rate1.nightly_equivalent.status == "known"
    assert rate1.nightly_equivalent.is_derived is True
    assert rate1.nightly_equivalent.value == 67.5  # 540 / 8, derived, never replacing the total
    assert rate1.taxes_amount == 40.0
    assert rate1.fees_amount == 10.0
    assert rate1.quantity_available == 3

    rate2 = next(r for r in rates if r.provider_rate_id == "rat_0000AS2")
    assert rate2.board_type.value == "room_only"
    assert rate2.payment_timing.value == "pay_at_property"


def test_fetch_all_rates_refundable_stays_unknown_never_guessed():
    # cancellation_timeline's real nested shape isn't documented in enough
    # detail to interpret safely — refundable must stay unknown rather than
    # guess at undocumented field names, per the same "unknown beats
    # hallucinated precision" principle used for LLM-adjacent facts.
    async def run():
        provider = DuffelStaysProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_fetch_transport(RAW_FETCH_ALL_RATES)) as client:
            return await provider.fetch_all_rates("srr_1", 8, client)

    _, rates, _ = asyncio.run(run())
    assert all(r.refundable.status == "unknown" for r in rates)
    assert all(r.cancellation_deadline is None for r in rates)


def test_fetch_all_rates_http_failure_raises_duffel_stays_error():
    async def run():
        provider = DuffelStaysProvider(api_key="test_key")
        async with httpx.AsyncClient(transport=_fetch_transport({}, status=503)) as client:
            return await provider.fetch_all_rates("srr_1", 8, client)

    with pytest.raises(DuffelStaysError):
        asyncio.run(run())


# --- FakeHotelProvider (test double) ---------------------------------------


def test_fake_hotel_provider_search_and_fetch():
    async def run():
        provider = FakeHotelProvider(
            properties_by_key={(1.0, 2.0): []},
            rates_by_search_result_id={"srr_1": ([HotelRoom(provider_room_id="r1", name="x")], [])},
        )
        plan = _plan()
        plan = plan.model_copy(update={"centre": Coordinates(lat=1.0, lon=2.0)})
        props, meta = await provider.search(plan, None)
        rooms, rates, fmeta = await provider.fetch_all_rates("srr_1", 8, None)
        return props, meta, rooms, rates, fmeta

    props, meta, rooms, rates, fmeta = asyncio.run(run())
    assert props == []
    assert meta["raw_count"] == 0
    assert len(rooms) == 1
    assert fmeta["raw_room_count"] == 1


def test_fake_hotel_provider_fetch_missing_raises():
    async def run():
        provider = FakeHotelProvider()
        return await provider.fetch_all_rates("nope", 8, None)

    with pytest.raises(DuffelStaysError):
        asyncio.run(run())
