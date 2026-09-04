"""Duffel Stays provider boundary. Nothing outside this module ever sees raw
Duffel Stays JSON — everything downstream works with normalized
HotelProperty/HotelRoom/HotelRate. No LLM anywhere in this module.

IMPORTANT — schema provenance: the request/response shapes this module
assumes are DOCUMENTATION-DERIVED, not independently live-verified. Duffel
Stays returned 403 "This feature is not enabled for your account" for the
test-mode key available during Milestone 5 development — an account/product
gate, not a credential or code problem. M4 already taught this project that
documentation and real API behavior can diverge, so every field this module
reads is accessed defensively (`.get()`, never assumed present) and every
fact that can't be safely, narrowly interpreted from the documented shape is
left `unknown` rather than guessed.

`location.radius` units are documented (kilometres) and are NOT
LIVE-UNVERIFIED — deliberately different from Flights Places'
/places/suggestions?rad=... (metres, confirmed live in M4). Do not conflate
the two; radius_km goes straight through to `radius` with no conversion.
Likewise the Stays guest payload is documented to send `type` and `age`
together for a child (`{"age": 7, "type": "child"}`) — this is NOT the
Flights offer_request passenger contract, which forbids exactly that
combination; do not reapply that M4 lesson here.

One remaining unresolved-pending-live-access decision is called out at its
`# LIVE-UNVERIFIED:` comment below: `refundable`/`cancellation_deadline`
interpretation from `cancellation_timeline` (left permanently
`unknown`/`None` in this pass rather than guess at an undocumented nested
structure).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import httpx

from ..schemas import (
    Coordinates,
    Evidence,
    FactResult,
    HotelProperty,
    HotelPropertyResult,
    HotelRate,
    HotelRoom,
    HotelSearchPlan,
)

DUFFEL_API_BASE = "https://api.duffel.com"
DEFAULT_DUFFEL_VERSION = "v2"

_MEAL_PLAN_VALUES = {"room_only", "breakfast", "half_board", "full_board", "all_inclusive"}
_SEA_VIEW_KEYWORDS = ("sea view", "seaview", "ocean view")
_BALCONY_KEYWORDS = ("balcony", "terrace")
_BEACHFRONT_AMENITY_TYPES = {"private_beach", "beachfront", "beach_access", "beach"}


class DuffelStaysConfigError(Exception):
    """No API key configured."""


class DuffelStaysError(Exception):
    """A Duffel Stays request failed — a provider failure, never interpreted
    as zero availability. Callers must keep this distinct from a successful
    response that happens to contain zero properties/rates."""


def _known_or_unknown(value, evidence: Evidence):

    if value is None:
        return FactResult(status="unknown")
    return FactResult(status="known", value=value, evidence=[evidence])


def _extract_board_type(raw_value, evidence: Evidence):

    if raw_value in _MEAL_PLAN_VALUES:
        return FactResult(status="known", value=raw_value, evidence=[evidence])
    if raw_value:
        return FactResult(status="unknown", note=f"unrecognized provider board_type: {raw_value!r}")
    return FactResult(status="unknown")


def _extract_payment_timing(raw_value, evidence: Evidence):

    if raw_value == "pay_now":
        return FactResult(status="known", value="pay_now", evidence=[evidence])
    if raw_value in ("pay_at_accommodation", "pay_at_property"):
        return FactResult(status="known", value="pay_at_property", evidence=[evidence])
    if raw_value:
        return FactResult(status="unknown", note=f"unrecognized provider payment_type: {raw_value!r}")
    return FactResult(status="unknown")


def _extract_beachfront(amenities_raw, evidence: Evidence):

    for a in amenities_raw or []:
        if (a.get("type") or "").lower() in _BEACHFRONT_AMENITY_TYPES:
            return FactResult(status="known", value=True, evidence=[evidence])
    # No matching amenity is not proof of absence — Duffel's amenity list is
    # not documented as exhaustive, so this stays unknown, never False.
    return FactResult(status="unknown")


def _extract_room_text_signal(room_raw: dict, keywords: tuple, evidence: Evidence):

    text = f"{room_raw.get('name') or ''} {room_raw.get('description') or ''}".lower()
    if any(kw in text for kw in keywords):
        return FactResult(status="known", value=True, evidence=[evidence])
    return FactResult(status="unknown")


def _normalize_room(raw: dict, room_id: str, evidence: Evidence) -> HotelRoom:
    beds = raw.get("beds") or []
    bed_info = ", ".join(f"{b.get('count', '?')}x {b.get('type', '?')}" for b in beds) if beds else None
    return HotelRoom(
        provider_room_id=room_id,
        name=raw.get("name") or "",
        description=raw.get("description"),
        bed_info=bed_info,
        sea_view=_extract_room_text_signal(raw, _SEA_VIEW_KEYWORDS, evidence),
        balcony=_extract_room_text_signal(raw, _BALCONY_KEYWORDS, evidence),
    )


def _normalize_rate(raw: dict, room_id: str, nights: int, evidence: Evidence) -> HotelRate:

    total_amount = float(raw["total_amount"])
    total_currency = raw["total_currency"]
    nightly = FactResult(status="known", value=round(total_amount / nights, 2), is_derived=True) if nights > 0 else FactResult(status="unknown")
    tax = raw.get("tax_amount")
    fee = raw.get("fee_amount")
    return HotelRate(
        provider_rate_id=raw["id"],
        room_id=room_id,
        total_amount=total_amount,
        total_currency=total_currency,
        nightly_equivalent=nightly,
        board_type=_extract_board_type(raw.get("board_type"), evidence),
        # LIVE-UNVERIFIED: cancellation_timeline's real nested shape is not
        # documented in enough detail to interpret safely — refundable stays
        # unknown and cancellation_deadline stays unset rather than guess at
        # undocumented field names. Revisit once Stays access is granted.
        refundable=FactResult(status="unknown"),
        cancellation_deadline=None,
        payment_timing=_extract_payment_timing(raw.get("payment_type"), evidence),
        taxes_amount=float(tax) if tax is not None else None,
        fees_amount=float(fee) if fee is not None else None,
        quantity_available=raw.get("quantity_available"),
    )


def _normalize_property(acc: dict, evidence: Evidence) -> HotelProperty:
    loc = acc.get("location") or {}
    lat, lon = loc.get("latitude"), loc.get("longitude")
    coords = Coordinates(lat=lat, lon=lon) if lat is not None and lon is not None else None
    amenities_raw = acc.get("amenities") or []
    return HotelProperty(
        provider_id=acc.get("id") or "",
        name=acc.get("name") or "",
        coordinates=coords,
        address=loc.get("line_one"),
        country_code=loc.get("country_code"),
        star_rating=_known_or_unknown(acc.get("rating"), evidence),
        review_score=_known_or_unknown(acc.get("review_score"), evidence),
        review_count=_known_or_unknown(acc.get("review_count"), evidence),
        amenities=[a["type"] for a in amenities_raw if a.get("type")],
        photos=[p["url"] for p in (acc.get("photos") or []) if p.get("url")],
        beachfront=_extract_beachfront(amenities_raw, evidence),
    )


def _normalize_search_result(raw: dict, evidence: Evidence) -> HotelPropertyResult:
    acc = raw.get("accommodation") or {}
    cheapest = raw.get("cheapest_rate_total_amount")
    return HotelPropertyResult(
        search_result_id=raw["id"],
        property=_normalize_property(acc, evidence),
        cheapest_total_amount=float(cheapest) if cheapest is not None else None,
        cheapest_total_currency=raw.get("cheapest_rate_currency"),
        inspection_status="summary_only",
        evidence=evidence,
    )


class DuffelStaysProvider:
    def __init__(self, api_key: Optional[str] = None, api_version: Optional[str] = None):
        api_key = api_key or os.environ.get("DUFFEL_API_KEY")
        if not api_key:
            raise DuffelStaysConfigError("DUFFEL_API_KEY is not set")
        self.api_key = api_key
        self.api_version = api_version or os.environ.get("DUFFEL_API_VERSION", DEFAULT_DUFFEL_VERSION)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Duffel-Version": self.api_version,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def search(self, plan: HotelSearchPlan, client: httpx.AsyncClient) -> Tuple[List[HotelPropertyResult], dict]:
        guests_payload = []
        for g in plan.guests:
            entry: dict = {"type": g.type}
            if g.age is not None:
                entry["age"] = g.age
            guests_payload.append(entry)

        body = {
            "data": {
                "check_in_date": plan.check_in.isoformat(),
                "check_out_date": plan.check_out.isoformat(),
                "rooms": plan.rooms,
                "guests": guests_payload,
                "location": {
                    # Stays' location.radius is documented in kilometres —
                    # deliberately different from Flights Places'
                    # /places/suggestions?rad=... (metres, confirmed live in
                    # M4). Do not reapply that conversion here: radius_km
                    # goes straight through, no *1000.
                    "radius": plan.radius_km,
                    "geographic_coordinates": {"latitude": plan.centre.lat, "longitude": plan.centre.lon},
                },
            }
        }
        try:
            resp = await client.post(f"{DUFFEL_API_BASE}/stays/search", json=body, headers=self._headers(), timeout=45.0)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise DuffelStaysError(f"stays search failed: {e}") from e

        results_raw = data.get("data") or []
        evidence = Evidence(
            source_type="structured_travel_provider",
            provider="Duffel Stays",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            title=f"Stays search near ({plan.centre.lat}, {plan.centre.lon}) rad={plan.radius_km}km",
            raw_excerpt=(
                f"check_in={plan.check_in} check_out={plan.check_out} rooms={plan.rooms} "
                f"guests={len(plan.guests)} -> {len(results_raw)} properties"
            ),
            confidence="high",
        )
        properties = [_normalize_search_result(r, evidence) for r in results_raw]
        return properties, {"raw_count": len(results_raw)}

    async def fetch_all_rates(
        self, search_result_id: str, nights: int, client: httpx.AsyncClient
    ) -> Tuple[List[HotelRoom], List[HotelRate], dict]:
        try:
            resp = await client.post(
                f"{DUFFEL_API_BASE}/stays/search_results/{search_result_id}/actions/fetch_all_rates",
                headers=self._headers(),
                timeout=45.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise DuffelStaysError(f"fetch_all_rates failed for {search_result_id!r}: {e}") from e

        result = data.get("data") or {}
        accommodation = result.get("accommodation") or {}
        rooms_raw = accommodation.get("rooms") or []
        evidence = Evidence(
            source_type="structured_travel_provider",
            provider="Duffel Stays",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            title=f"Duffel Stays fetch_all_rates for {search_result_id}",
            raw_excerpt=f"search_result_id={search_result_id} -> {len(rooms_raw)} room categories",
            confidence="high",
        )

        rooms: List[HotelRoom] = []
        rates: List[HotelRate] = []
        for i, room_raw in enumerate(rooms_raw):
            # Duffel's documented Room object carries no room-level `id` —
            # synthesize a stable one rather than fabricate reading a field
            # that isn't documented to exist.
            room_id = f"{search_result_id}_room_{i}"
            rooms.append(_normalize_room(room_raw, room_id, evidence))
            for rate_raw in room_raw.get("rates") or []:
                rates.append(_normalize_rate(rate_raw, room_id, nights, evidence))

        return rooms, rates, {"raw_room_count": len(rooms_raw)}


class FakeHotelProvider:
    """Test double: no network, canned properties/rates, following the same
    pattern as FakeFlightProvider."""

    def __init__(self, properties_by_key: Optional[dict] = None, rates_by_search_result_id: Optional[dict] = None):
        self.properties_by_key = properties_by_key if properties_by_key is not None else {}
        self.rates_by_search_result_id = rates_by_search_result_id if rates_by_search_result_id is not None else {}
        self.search_calls: List[HotelSearchPlan] = []
        self.fetch_calls: List[str] = []

    async def search(self, plan: HotelSearchPlan, client: httpx.AsyncClient) -> Tuple[List[HotelPropertyResult], dict]:
        self.search_calls.append(plan)
        props = self.properties_by_key.get((plan.centre.lat, plan.centre.lon), [])
        return list(props), {"raw_count": len(props)}

    async def fetch_all_rates(
        self, search_result_id: str, nights: int, client: httpx.AsyncClient
    ) -> Tuple[List[HotelRoom], List[HotelRate], dict]:
        self.fetch_calls.append(search_result_id)
        entry = self.rates_by_search_result_id.get(search_result_id)
        if entry is None:
            raise DuffelStaysError(f"no fake rates for {search_result_id!r}")
        rooms, rates = entry
        return list(rooms), list(rates), {"raw_room_count": len(rooms)}
