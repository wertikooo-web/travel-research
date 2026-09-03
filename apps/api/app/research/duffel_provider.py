"""Duffel provider boundary. Nothing outside this module ever sees raw Duffel
JSON — everything downstream works with normalized TransportPlace/FlightOffer.

Two responsibilities, kept separate the same way visa retrieval/classification
are: resolve_place() turns structured provider data into a TransportPlace
(never a raw candidate display name); search() turns a FlightSearchPlan into
normalized FlightOffers. Neither one is an LLM call — there is no LLM
anywhere in this module.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import httpx

from ..schemas import FlightItinerary, FlightOffer, FlightSearchPlan, FlightSegment, TransportPlace

DUFFEL_API_BASE = "https://api.duffel.com"
DEFAULT_DUFFEL_VERSION = "v2"

# Conservative V0 policy: one bounded radius search, no progressive expansion.
# If nothing reasonable turns up within this radius, the destination stays
# unresolved rather than guessing at an ever-wider search.
DEFAULT_RADIUS_KM = 100


class DuffelConfigError(Exception):
    """No API key configured."""


class DuffelError(Exception):
    """A Duffel request failed — a provider failure, never interpreted as
    zero availability. Callers must keep this distinct from a successful
    response that happens to contain zero offers."""


class DuffelPlaceNotFoundError(Exception):
    """Duffel had no place matching the query — never guess an airport."""


_DURATION_RE = re.compile(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?$")


def _parse_duration_minutes(value: Optional[str]) -> Optional[int]:
    """Duffel durations are ISO 8601 ("PT5H30M"). Returns None rather than
    guessing when the format doesn't match — an unparsed duration is
    unknown, not zero."""
    if not value:
        return None
    m = _DURATION_RE.match(value)
    if not m:
        return None
    days, hours, minutes = (int(g) if g else 0 for g in m.groups())
    return days * 24 * 60 + hours * 60 + minutes


def _normalize_itinerary(slice_data: dict) -> FlightItinerary:
    segments_raw = slice_data.get("segments") or []
    segments = [
        FlightSegment(
            origin_iata=(s.get("origin") or {}).get("iata_code", ""),
            destination_iata=(s.get("destination") or {}).get("iata_code", ""),
            departing_at=s.get("departing_at", ""),
            arriving_at=s.get("arriving_at", ""),
            operating_carrier=(s.get("operating_carrier") or {}).get("name"),
            marketing_carrier=(s.get("marketing_carrier") or {}).get("name"),
            duration_minutes=_parse_duration_minutes(s.get("duration")),
        )
        for s in segments_raw
    ]
    return FlightItinerary(
        segments=segments,
        duration_minutes=_parse_duration_minutes(slice_data.get("duration")),
        connections=max(0, len(segments) - 1),
    )


def _extract_cabin(slices: list) -> Optional[str]:
    """Real Duffel offers carry no offer-level cabin_class field — it lives
    per-segment, per-passenger (slices[].segments[].passengers[].cabin_class),
    confirmed against the live API during Milestone 4 acceptance testing. The
    first outbound segment's first passenger is a reasonable single
    representative value for this offer's V0 scalar `cabin` field — every
    passenger on a single-cabin economy/business search shares the same
    cabin, and mixed-cabin offers are out of scope this milestone."""
    if not slices:
        return None
    segments = slices[0].get("segments") or []
    if not segments:
        return None
    passengers = segments[0].get("passengers") or []
    if not passengers:
        return None
    return passengers[0].get("cabin_class") or passengers[0].get("cabin_class_marketing_name")


def normalize_offer(raw: dict, traveller_count: int, retrieved_at: str) -> FlightOffer:
    slices = raw.get("slices") or []
    outbound = _normalize_itinerary(slices[0]) if len(slices) >= 1 else FlightItinerary()
    return_itinerary = _normalize_itinerary(slices[1]) if len(slices) >= 2 else None
    return FlightOffer(
        id=raw["id"],
        outbound=outbound,
        return_=return_itinerary,
        total_amount=float(raw["total_amount"]),
        total_currency=raw["total_currency"],
        traveller_count=traveller_count,
        cabin=_extract_cabin(slices),
        retrieved_at=retrieved_at,
        expires_at=raw.get("expires_at"),
    )


class DuffelFlightProvider:
    def __init__(self, api_key: Optional[str] = None, api_version: Optional[str] = None):
        api_key = api_key or os.environ.get("DUFFEL_API_KEY")
        if not api_key:
            raise DuffelConfigError("DUFFEL_API_KEY is not set")
        self.api_key = api_key
        self.api_version = api_version or os.environ.get("DUFFEL_API_VERSION", DEFAULT_DUFFEL_VERSION)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Duffel-Version": self.api_version,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def resolve_place(self, query: str, country_code: Optional[str], client: httpx.AsyncClient) -> TransportPlace:
        try:
            resp = await client.get(
                f"{DUFFEL_API_BASE}/places/suggestions",
                params={"query": query},
                headers=self._headers(),
                timeout=20.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise DuffelError(f"place search failed for {query!r}: {e}") from e

        places = data.get("data") or []
        if country_code:
            filtered = [p for p in places if (p.get("iata_country_code") or "").upper() == country_code.upper()]
            if filtered:
                places = filtered
        if not places:
            raise DuffelPlaceNotFoundError(f"no Duffel place match for {query!r}")

        # a city code lets Duffel aggregate multi-airport cities server-side —
        # no need for us to fan out into per-airport searches this milestone
        match = next((p for p in places if p.get("type") == "city"), places[0])

        alt_codes: List[str] = []
        if match.get("type") == "city":
            alt_codes = [a["iata_code"] for a in (match.get("airports") or []) if a.get("iata_code")]

        return TransportPlace(
            iata_code=match["iata_code"],
            type=match.get("type", "airport"),
            name=match.get("name", query),
            country_code=match.get("iata_country_code"),
            alternate_iata_codes=alt_codes,
            resolved_via="text_query",
        )

    async def resolve_place_by_coordinates(
        self, lat: float, lon: float, radius_km: float, client: httpx.AsyncClient
    ) -> Tuple[TransportPlace, dict]:
        """Verified destination coordinates, not display-language text, drive
        this lookup — the primary destination-resolution path when
        DestinationIdentity carries trustworthy coordinates. One bounded
        radius attempt; never progressively widened.

        Duffel's `rad` parameter is documented in metres, not kilometres —
        confirmed against the live API during Milestone 4 acceptance testing
        (a km value sent as-is silently returned zero results for every real
        destination). Our own radius_km stays in kilometres everywhere else
        (the domain model, evidence, callers); only the outbound HTTP param
        is converted."""
        try:
            resp = await client.get(
                f"{DUFFEL_API_BASE}/places/suggestions",
                params={"lat": lat, "lng": lon, "rad": radius_km * 1000},
                headers=self._headers(),
                timeout=20.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise DuffelError(f"coordinate place search failed for ({lat}, {lon}): {e}") from e

        places = data.get("data") or []
        if not places:
            raise DuffelPlaceNotFoundError(f"no Duffel place within {radius_km}km of ({lat}, {lon})")

        # same deterministic selection policy as resolve_place(): prefer a
        # city (Duffel aggregates its airports server-side), else the first
        # airport-type result; other candidates are preserved as alternates,
        # not silently discarded.
        match = next((p for p in places if p.get("type") == "city"), places[0])

        alt_codes: List[str] = []
        if match.get("type") == "city":
            alt_codes = [a["iata_code"] for a in (match.get("airports") or []) if a.get("iata_code")]
        else:
            alt_codes = [p["iata_code"] for p in places if p is not match and p.get("iata_code")]

        place = TransportPlace(
            iata_code=match["iata_code"],
            type=match.get("type", "airport"),
            name=match.get("name", ""),
            country_code=match.get("iata_country_code"),
            alternate_iata_codes=alt_codes,
            resolved_via="coordinates",
            distance_km=match.get("distance"),
        )
        meta = {"radius_km": radius_km, "lat": lat, "lon": lon, "raw_count": len(places)}
        return place, meta

    async def search(self, plan: FlightSearchPlan, client: httpx.AsyncClient) -> Tuple[List[FlightOffer], dict]:
        # Duffel rejects a passenger carrying both `type` and `age` together
        # ("You may only specify an age or a type – not both") — confirmed
        # against the live API during Milestone 4 acceptance testing. When we
        # know the age, send only that and let Duffel classify the passenger
        # itself (airlines vary on where the adult/child line falls); `type`
        # is sent only when age is unknown.
        passengers_payload = []
        for p in plan.passengers:
            entry: dict = {"age": p.age} if p.age is not None else {"type": p.type}
            passengers_payload.append(entry)

        body = {
            "data": {
                "slices": [
                    {
                        "origin": plan.origin.iata_code,
                        "destination": plan.destination.iata_code,
                        "departure_date": plan.outbound_date.isoformat(),
                    },
                    {
                        "origin": plan.destination.iata_code,
                        "destination": plan.origin.iata_code,
                        "departure_date": plan.return_date.isoformat(),
                    },
                ],
                "passengers": passengers_payload,
                "cabin_class": plan.cabin,
                "max_connections": plan.max_connections_sent,
            }
        }
        try:
            resp = await client.post(
                f"{DUFFEL_API_BASE}/air/offer_requests",
                params={"return_offers": "true"},
                json=body,
                headers=self._headers(),
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise DuffelError(f"offer request failed: {e}") from e

        offer_request = data.get("data") or {}
        raw_offers = offer_request.get("offers") or []
        retrieved_at = datetime.now(timezone.utc).isoformat()
        offers = [normalize_offer(o, len(plan.passengers), retrieved_at) for o in raw_offers]
        meta = {"offer_request_id": offer_request.get("id"), "raw_offer_count": len(raw_offers)}
        return offers, meta


class FakeFlightProvider:
    """Test double: no network, canned places/offers, following the same
    pattern as FakeCandidateProvider/FakeVisaExtractionProvider."""

    def __init__(
        self,
        places: Optional[dict] = None,
        offers: Optional[List[FlightOffer]] = None,
        places_by_coordinates: Optional[dict] = None,
    ):
        self.places = places if places is not None else {}
        self.offers = offers if offers is not None else []
        # keyed by (lat, lon) tuple -> TransportPlace, mirroring resolve_place's
        # query-keyed dict so tests can exercise the coordinate-first path
        self.places_by_coordinates = places_by_coordinates if places_by_coordinates is not None else {}
        self.search_calls: List[FlightSearchPlan] = []

    async def resolve_place(self, query: str, country_code: Optional[str], client: httpx.AsyncClient) -> TransportPlace:
        place = self.places.get(query)
        if place is None:
            raise DuffelPlaceNotFoundError(f"no fake place for {query!r}")
        return place

    async def resolve_place_by_coordinates(
        self, lat: float, lon: float, radius_km: float, client: httpx.AsyncClient
    ) -> Tuple[TransportPlace, dict]:
        place = self.places_by_coordinates.get((lat, lon))
        if place is None:
            raise DuffelPlaceNotFoundError(f"no fake place within {radius_km}km of ({lat}, {lon})")
        return place, {"radius_km": radius_km, "lat": lat, "lon": lon, "raw_count": 1}

    async def search(self, plan: FlightSearchPlan, client: httpx.AsyncClient) -> Tuple[List[FlightOffer], dict]:
        self.search_calls.append(plan)
        return list(self.offers), {"offer_request_id": "orq_fake", "raw_offer_count": len(self.offers)}
