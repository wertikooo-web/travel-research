"""Destination identity + basics — Open-Meteo's free geocoding API.

Deterministic HTTP lookup, zero LLM involvement. This *is* the destination
identity step Milestone 3 needs: coordinates, resolved country, timezone —
real, evidence-backed, not string-matched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from ..schemas import Coordinates, DestinationIdentity, Evidence

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


class DestinationBasicsError(Exception):
    """Geocoding failed or returned nothing usable — never guess an identity."""


async def research_destination_basics(
    destination_name: str, country_code: Optional[str], client: httpx.AsyncClient
) -> tuple[DestinationIdentity, Evidence]:
    params = {"name": destination_name, "count": 5, "language": "en", "format": "json"}
    try:
        resp = await client.get(GEOCODING_URL, params=params, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        raise DestinationBasicsError(f"geocoding request failed: {e}") from e

    results = data.get("results") or []
    if not results:
        raise DestinationBasicsError(f"no geocoding match for {destination_name!r}")

    # prefer a result matching the country_code the candidate already carries,
    # so "Malta" doesn't accidentally resolve to a same-named place elsewhere
    match = results[0]
    if country_code:
        for r in results:
            if r.get("country_code", "").upper() == country_code.upper():
                match = r
                break

    retrieved_at = datetime.now(timezone.utc).isoformat()
    identity = DestinationIdentity(
        display_name=match.get("name", destination_name),
        country_code=(match.get("country_code") or country_code or None),
        parent_country_name=match.get("country"),
        coordinates=Coordinates(lat=match["latitude"], lon=match["longitude"]),
        timezone=match.get("timezone"),
        aliases=[destination_name] if destination_name != match.get("name") else [],
    )
    evidence = Evidence(
        source_type="geo_provider",
        provider="Open-Meteo Geocoding",
        url=f"{GEOCODING_URL}?name={destination_name}",
        retrieved_at=retrieved_at,
        title=f"Geocoding result for {destination_name}",
        raw_excerpt=f"{match.get('name')}, {match.get('admin1', '')}, {match.get('country', '')} ({match['latitude']}, {match['longitude']})",
        confidence="high",
    )
    return identity, evidence
