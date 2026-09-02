"""Orchestration: ResearchRun identities + confirmed brief -> per-candidate
FlightSearchPlan(s) -> Duffel search -> DestinationFlightResearch.

Same failure-isolation and concurrency-bounding philosophy as
research_pipeline.py: one destination's Duffel failure never touches
another's, and flexible dates never explode into unbounded provider calls.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx

from ..schemas import (
    Cabin,
    Candidate,
    ConnectionPolicy,
    DestinationFlightResearch,
    DestinationResearch,
    Evidence,
    FlightPassenger,
    FlightSearchOutcome,
    FlightSearchPlan,
    Traveller,
    TripBrief,
    TransportPlace,
)
from .duffel_provider import DuffelError, DuffelFlightProvider, DuffelPlaceNotFoundError
from .flight_dates import resolve_date_plans

MAX_CONCURRENT_SEARCHES = 5
MAX_TOTAL_SEARCHES_PER_RUN = 60  # defensive ceiling; the date/candidate caps already keep this far below in practice
DEFAULT_MAX_CONNECTIONS = 1  # V0 policy: a preference is not silently promoted to a hard direct-only filter


def _map_passenger(traveller: Traveller) -> FlightPassenger:
    """Deterministic, using only what the brief actually states — never
    assumes adult, never invents an age band for an unknown-age child
    beyond Duffel's own generic 'child' category."""
    if traveller.type == "child":
        if traveller.age is not None and traveller.age < 2:
            return FlightPassenger(traveller_id=traveller.id or "unknown", type="infant_without_seat", age=traveller.age)
        return FlightPassenger(traveller_id=traveller.id or "unknown", type="child", age=traveller.age)
    return FlightPassenger(traveller_id=traveller.id or "unknown", type="adult", age=traveller.age)


def _resolve_cabin(brief: TripBrief) -> Cabin:
    if brief.flight and brief.flight.preferred_cabin:
        return brief.flight.preferred_cabin
    return "economy"  # documented V0 default — never inferred from wording like "comfortable"


def _resolve_connections(brief: TripBrief) -> Tuple[int, ConnectionPolicy]:
    flight = brief.flight
    if flight and flight.max_connections is not None:
        policy: ConnectionPolicy = "direct_required" if flight.max_connections == 0 else "max_connections_constraint"
        return flight.max_connections, policy
    if flight and flight.direct_preferred:
        # a preference, not a filter: search broader and keep the real connection
        # count on every offer so display/scoring can weigh the preference later
        return DEFAULT_MAX_CONNECTIONS, "direct_preferred"
    return DEFAULT_MAX_CONNECTIONS, "unspecified"


async def resolve_origin_place(
    brief: TripBrief, provider: DuffelFlightProvider, client: httpx.AsyncClient
) -> Tuple[Optional[TransportPlace], Optional[str]]:
    origin = brief.origin
    if origin is None or (not origin.iata and not origin.text):
        return None, "insufficient_input: no origin in the confirmed brief"
    if origin.iata:
        return TransportPlace(iata_code=origin.iata.upper(), type="airport", name=origin.text or origin.iata), None
    try:
        place = await provider.resolve_place(origin.text, None, client)
        return place, None
    except DuffelPlaceNotFoundError as e:
        return None, f"insufficient_input: {e}"
    except DuffelError as e:
        return None, f"unavailable: origin place lookup failed: {e}"


class _Budget:
    """Shared, synchronous counter — safe across concurrently-gathered
    coroutines since .take() has no await inside it (no context-switch point
    for a race to open up)."""

    def __init__(self, limit: int):
        self.limit = limit
        self.remaining = limit

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def _aggregate_overall_status(resolution_status: str, date_status: str, searches: List[FlightSearchOutcome]) -> str:
    if resolution_status != "success":
        return resolution_status
    if date_status != "success":
        return date_status
    if not searches:
        return "unknown"
    statuses = {s.status for s in searches}
    if statuses <= {"success"}:
        return "success"
    if "success" in statuses:
        return "partial"
    return "failed"


async def _run_search(
    plan: FlightSearchPlan, provider: DuffelFlightProvider, client: httpx.AsyncClient, semaphore: asyncio.Semaphore
) -> FlightSearchOutcome:
    try:
        async with semaphore:
            offers, meta = await provider.search(plan, client)
    except DuffelError as e:
        # a provider failure — structurally distinct from a successful
        # zero-offer response, never interpreted as "no flights exist"
        return FlightSearchOutcome(plan=plan, status="failed", error=str(e))

    evidence = Evidence(
        source_type="structured_travel_provider",
        provider="Duffel",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        title=f"Flight search {plan.origin.iata_code}->{plan.destination.iata_code} {plan.outbound_date}",
        raw_excerpt=f"offer_request={meta.get('offer_request_id')}, offers_returned={meta.get('raw_offer_count')}",
        confidence="high",
    )
    note = None if offers else "no offers returned for this exact search — not the same as provider failure"
    return FlightSearchOutcome(plan=plan, status="success", offers=offers, evidence=evidence, note=note)


async def research_candidate_flights(
    candidate: Candidate,
    destination_research: Optional[DestinationResearch],
    brief: TripBrief,
    origin_place: Optional[TransportPlace],
    origin_error: Optional[str],
    provider: DuffelFlightProvider,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    search_budget: _Budget,
) -> DestinationFlightResearch:
    result = DestinationFlightResearch(candidate_id=candidate.id or candidate.destination_name, origin_place=origin_place)

    if origin_place is None:
        result.resolution_status = "unknown" if origin_error and "insufficient_input" in origin_error else "failed"
        result.warnings.append(origin_error or "origin unresolved")
        result.overall_status = result.resolution_status
        return result

    identity = destination_research.identity if destination_research else None
    if identity is None:
        result.resolution_status = "unknown"
        result.warnings.append("no destination identity from research — flight place cannot be resolved")
        result.overall_status = "unknown"
        return result

    # the verified, English geocoded name from M3's own identity resolution —
    # never candidate.destination_name, which is raw (possibly non-Latin) LLM output
    query_name = identity.display_name
    try:
        async with semaphore:
            dest_place = await provider.resolve_place(query_name, identity.country_code or candidate.country_code, client)
        result.destination_place = dest_place
        result.resolution_status = "success"
    except DuffelPlaceNotFoundError as e:
        result.resolution_status = "unknown"
        result.warnings.append(f"destination place unresolved: {e}")
        result.overall_status = "unknown"
        return result
    except DuffelError as e:
        result.resolution_status = "failed"
        result.errors.append(f"destination place lookup failed: {e}")
        result.overall_status = "failed"
        return result

    plans, reason = resolve_date_plans(brief.dates, brief.nights)
    if not plans:
        result.date_status = "unknown"
        result.warnings.append(reason or "insufficient_input: no usable travel dates")
        result.overall_status = "unknown"
        return result
    result.date_status = "success"

    cabin = _resolve_cabin(brief)
    max_conn, conn_policy = _resolve_connections(brief)
    passengers = [_map_passenger(t) for t in brief.travellers] or [FlightPassenger(traveller_id="unknown", type="adult")]

    outcomes: List[FlightSearchOutcome] = []
    for date_plan in plans:
        if not search_budget.take():
            result.warnings.append(f"request budget reached ({search_budget.limit}) — remaining searches for this run were skipped")
            break

        plan = FlightSearchPlan(
            origin=origin_place,
            destination=dest_place,
            outbound_date=date_plan.outbound_date,
            return_date=date_plan.return_date,
            nights=date_plan.nights,
            date_variant=date_plan.variant,
            passengers=passengers,
            cabin=cabin,
            max_connections_sent=max_conn,
            connection_policy=conn_policy,
        )
        outcomes.append(await _run_search(plan, provider, client, semaphore))

    result.searches = outcomes
    result.overall_status = _aggregate_overall_status(result.resolution_status, result.date_status, outcomes)
    return result


async def run_flight_research(
    candidates: List[Candidate],
    destination_research_by_candidate: Dict[str, DestinationResearch],
    brief: TripBrief,
    provider: DuffelFlightProvider,
) -> List[DestinationFlightResearch]:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)
    budget = _Budget(MAX_TOTAL_SEARCHES_PER_RUN)

    async with httpx.AsyncClient() as client:
        origin_place, origin_error = await resolve_origin_place(brief, provider, client)
        tasks = [
            research_candidate_flights(
                c,
                destination_research_by_candidate.get(c.id),
                brief,
                origin_place,
                origin_error,
                provider,
                client,
                semaphore,
                budget,
            )
            for c in candidates
        ]
        return list(await asyncio.gather(*tasks))


def summarize_flight_run_status(results: List[DestinationFlightResearch]) -> str:
    if not results:
        return "failed"
    statuses = {r.overall_status for r in results}
    if statuses <= {"success"}:
        return "completed"
    if statuses & {"success", "partial"}:
        return "partial"
    return "failed"
