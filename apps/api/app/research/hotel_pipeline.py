"""Orchestration: ResearchRun identities + confirmed brief -> per-candidate
HotelSearchPlan(s) -> Duffel Stays search -> deep-inspect a bounded shortlist
-> DestinationHotelResearch.

Same failure-isolation and concurrency-bounding philosophy as
flight_pipeline.py: one destination's provider failure never touches
another's, one property's fetch_all_rates failure never sinks its search,
and a full-rates fetch never fans out to every returned property. Hotel and
flight date semantics are the same bounded, deterministic date-plan strategy
(flight_dates.resolve_date_plans) — no independent hotel date search.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx

from ..schemas import (
    Candidate,
    DestinationHotelResearch,
    DestinationIdentity,
    DestinationResearch,
    Evidence,
    HotelGuest,
    HotelPropertyResult,
    HotelSearchOutcome,
    HotelSearchPlan,
    Traveller,
    TripBrief,
)
from .flight_dates import resolve_date_plans
from .hotel_provider import DuffelStaysError, DuffelStaysProvider

MAX_CONCURRENT_SEARCHES = 5
MAX_TOTAL_SEARCHES_PER_RUN = 60  # defensive ceiling, mirrors flight_pipeline

# V0 geography policy: a conservative radius around the resort/area itself,
# not "the whole island" or "the whole region" — a beach resort and an
# island are not the same search area. Explicit constant, never
# progressively widened.
DEFAULT_SEARCH_RADIUS_KM = 15.0

# V0 room policy: exactly one room per search. TripBrief has no explicit
# room-count field and no seat/room assignment model, so inventing a
# multi-room split would mean guessing who sleeps where — out of scope this
# milestone. If a future brief field states an explicit room count, this is
# the one place that needs to change.
DEFAULT_ROOM_COUNT = 1

# V0 request-budget policy: retain a bounded shortlist of summary results,
# deep-inspect (fetch_all_rates) only a small slice of it per date variant,
# and cap total deep-fetches for the whole run. Selection is neutral and
# deterministic — provider order + a usable price — never M6 fit scoring.
MAX_SUMMARY_PROPERTIES_PER_SEARCH = 15
MAX_DEEP_INSPECT_PER_DATE_VARIANT = 5
MAX_TOTAL_DEEP_FETCHES_PER_RUN = 60


def _map_guests(travellers: List[Traveller]) -> List[HotelGuest]:
    """Deterministic, using only what the brief actually states — mirrors
    flight_pipeline._map_passenger's refusal to invent an age band."""
    if not travellers:
        return [HotelGuest(type="adult")]
    return [HotelGuest(type=t.type, age=t.age) for t in travellers]


def resolve_hotel_search_plans(
    identity: Optional[DestinationIdentity], brief: TripBrief
) -> Tuple[List[HotelSearchPlan], Optional[str]]:
    """Mirrors flight_pipeline's destination-place resolution rule: verified
    coordinates are required, never a display string and never a country
    centroid substitute. Reuses the exact same bounded date-plan strategy
    flights use — no independent hotel date combinatorics."""
    if identity is None or identity.coordinates is None:
        return [], "insufficient_input: no verified destination coordinates"

    plans, reason = resolve_date_plans(brief.dates, brief.nights)
    if not plans:
        return [], reason

    guests = _map_guests(brief.travellers)
    return (
        [
            HotelSearchPlan(
                centre=identity.coordinates,
                radius_km=DEFAULT_SEARCH_RADIUS_KM,
                check_in=p.outbound_date,
                check_out=p.return_date,
                nights=p.nights,
                date_variant=p.variant,
                rooms=DEFAULT_ROOM_COUNT,
                guests=guests,
            )
            for p in plans
        ],
        None,
    )


class _Budget:
    """Shared, synchronous counter — safe across concurrently-gathered
    coroutines, mirrors flight_pipeline._Budget."""

    def __init__(self, limit: int):
        self.limit = limit
        self.remaining = limit

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def _select_for_deep_inspection(properties: List[HotelPropertyResult]) -> List[HotelPropertyResult]:
    """Neutral, deterministic shortlist selection — provider search order and
    a usable price. No star/review weighting, no M6 fit scoring."""
    usable = [p for p in properties if p.cheapest_total_amount is not None]
    return usable[:MAX_DEEP_INSPECT_PER_DATE_VARIANT]


async def _deep_inspect(
    prop: HotelPropertyResult, nights: int, provider: DuffelStaysProvider, client: httpx.AsyncClient
) -> HotelPropertyResult:
    try:
        rooms, rates, meta = await provider.fetch_all_rates(prop.search_result_id, nights, client)
    except DuffelStaysError as e:
        # this property's own fetch failure — the property stays visible
        # with its summary data intact, never dropped, never faked as fetched
        prop.inspection_status = "rates_fetch_failed"
        prop.rates_fetch_error = str(e)
        return prop

    prop.rooms = rooms
    prop.rates = rates
    prop.inspection_status = "rates_fetched"
    prop.rates_evidence = Evidence(
        source_type="structured_travel_provider",
        provider="Duffel Stays",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        title=f"fetch_all_rates for {prop.property.name or prop.search_result_id}",
        raw_excerpt=f"search_result_id={prop.search_result_id} -> {meta.get('raw_room_count')} room categories",
        confidence="high",
    )
    return prop


async def _run_hotel_search_for_plan(
    plan: HotelSearchPlan,
    provider: DuffelStaysProvider,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    deep_fetch_budget: _Budget,
) -> HotelSearchOutcome:
    try:
        async with semaphore:
            properties, meta = await provider.search(plan, client)
    except DuffelStaysError as e:
        # a provider failure — structurally distinct from a successful
        # zero-property response, never interpreted as "no hotels exist"
        return HotelSearchOutcome(plan=plan, status="failed", error=str(e))

    properties = properties[:MAX_SUMMARY_PROPERTIES_PER_SEARCH]
    evidence = Evidence(
        source_type="structured_travel_provider",
        provider="Duffel Stays",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        title=f"Stays search {plan.check_in}->{plan.check_out} near ({plan.centre.lat}, {plan.centre.lon})",
        raw_excerpt=f"radius_km={plan.radius_km} rooms={plan.rooms} guests={len(plan.guests)} -> {meta.get('raw_count')} properties",
        confidence="high",
    )

    shortlist = _select_for_deep_inspection(properties)
    for prop in shortlist:
        if not deep_fetch_budget.take():
            break
        async with semaphore:
            await _deep_inspect(prop, plan.nights, provider, client)

    note = None if properties else "no properties returned for this exact search — not the same as provider failure"
    return HotelSearchOutcome(plan=plan, status="success", properties=properties, evidence=evidence, note=note)


def _aggregate_overall_status(geography_status: str, date_status: str, searches: List[HotelSearchOutcome]) -> str:
    if geography_status != "success":
        return geography_status
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


async def research_candidate_hotels(
    candidate: Candidate,
    destination_research: Optional[DestinationResearch],
    brief: TripBrief,
    provider: DuffelStaysProvider,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    search_budget: _Budget,
    deep_fetch_budget: _Budget,
) -> DestinationHotelResearch:
    result = DestinationHotelResearch(candidate_id=candidate.id or candidate.destination_name)

    identity = destination_research.identity if destination_research else None
    plans, reason = resolve_hotel_search_plans(identity, brief)

    if identity is None or identity.coordinates is None:
        result.geography_status = "unknown"
        result.warnings.append(reason or "insufficient_input: no destination identity from research")
        result.overall_status = "unknown"
        return result
    result.geography_status = "success"

    if not plans:
        result.date_status = "unknown"
        result.warnings.append(reason or "insufficient_input: no usable stay dates")
        result.overall_status = "unknown"
        return result
    result.date_status = "success"

    outcomes: List[HotelSearchOutcome] = []
    for plan in plans:
        if not search_budget.take():
            result.warnings.append(f"request budget reached ({search_budget.limit}) — remaining searches for this run were skipped")
            break
        outcomes.append(await _run_hotel_search_for_plan(plan, provider, client, semaphore, deep_fetch_budget))

    result.searches = outcomes
    result.overall_status = _aggregate_overall_status(result.geography_status, result.date_status, outcomes)
    return result


async def run_hotel_research(
    candidates: List[Candidate],
    destination_research_by_candidate: Dict[str, DestinationResearch],
    brief: TripBrief,
    provider: DuffelStaysProvider,
) -> List[DestinationHotelResearch]:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)
    search_budget = _Budget(MAX_TOTAL_SEARCHES_PER_RUN)
    deep_fetch_budget = _Budget(MAX_TOTAL_DEEP_FETCHES_PER_RUN)

    async with httpx.AsyncClient() as client:
        tasks = [
            research_candidate_hotels(
                c, destination_research_by_candidate.get(c.id), brief, provider, client, semaphore, search_budget, deep_fetch_budget
            )
            for c in candidates
        ]
        return list(await asyncio.gather(*tasks))


def summarize_hotel_run_status(results: List[DestinationHotelResearch]) -> str:
    if not results:
        return "failed"
    statuses = {r.overall_status for r in results}
    if statuses <= {"success"}:
        return "completed"
    if statuses & {"success", "partial"}:
        return "partial"
    return "failed"
