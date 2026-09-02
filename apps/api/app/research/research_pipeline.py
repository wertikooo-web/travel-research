"""Orchestration: Candidate -> basics -> weather -> visa -> DestinationResearch.

Predictable, not an agent: a fixed pipeline of three independently-testable,
independently-rerunnable steps, run concurrently across candidates. One
component failing (say, weather) never takes down the whole destination —
see the DoD's "partial research succeeds safely" requirement directly.
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

import httpx

from ..schemas import Candidate, DestinationResearch, FactResult, TripBrief, VisaResult
from .destination_basics import DestinationBasicsError, research_destination_basics
from .visa import VisaExtractionProvider, research_visa
from .weather import OpenMeteoWeatherProvider, WeatherProviderError


def _traveller_passports(traveller) -> List[str]:
    if traveller.citizenships:
        return list(dict.fromkeys(traveller.citizenships))  # dedup, keep order
    if traveller.travel_passport:
        return [traveller.travel_passport]
    return []


def _aggregate_visa_status(visa_results: List[VisaResult]) -> str:
    if not visa_results:
        return "unknown"
    statuses = {v.status.status for v in visa_results}
    if statuses == {"known"}:
        return "success"
    if "known" in statuses:
        return "partial"
    if statuses & {"unavailable"}:
        return "failed" if not (statuses - {"unavailable"}) else "partial"
    return "unknown"


async def research_candidate(
    candidate: Candidate,
    brief: TripBrief,
    client: httpx.AsyncClient,
    *,
    weather_provider: Optional[OpenMeteoWeatherProvider] = None,
    visa_extraction_provider: Optional[VisaExtractionProvider] = None,
) -> DestinationResearch:
    weather_provider = weather_provider or OpenMeteoWeatherProvider()
    result = DestinationResearch(candidate_id=candidate.id or candidate.destination_name)

    try:
        identity, _basics_evidence = await research_destination_basics(candidate.destination_name, candidate.country_code, client)
        result.identity = identity
        result.basics_status = "success"
    except DestinationBasicsError as e:
        result.basics_status = "failed"
        result.errors.append(f"basics: {e}")

    if result.identity and result.identity.coordinates:
        try:
            weather_facts, _evidence = await weather_provider.research(
                result.identity.coordinates.lat, result.identity.coordinates.lon, brief, client
            )
            result.weather = weather_facts
            known_fields = [
                weather_facts.day_temp_c.status,
                weather_facts.night_temp_c.status,
                weather_facts.sea_temp_c.status,
                weather_facts.rainy_day_ratio.status,
            ]
            result.weather_status = "success" if all(s == "known" for s in known_fields) else "partial"
        except WeatherProviderError as e:
            result.weather_status = "failed"
            result.errors.append(f"weather: {e}")
    else:
        result.weather_status = "unknown"
        result.warnings.append("weather skipped — no verified coordinates for this destination")

    dest_code = (result.identity.country_code if result.identity else None) or candidate.country_code
    visa_results: List[VisaResult] = []
    for traveller in brief.travellers:
        passports = _traveller_passports(traveller)
        if not passports:
            visa_results.append(
                VisaResult(
                    traveller_id=traveller.id or "unknown",
                    passport_country=None,
                    destination_country=dest_code,
                    status=FactResult(status="unknown", note="no passport/citizenship information for this traveller"),
                )
            )
            result.warnings.append(f"{traveller.id}: no passport info — visa left unknown, not inferred")
            continue
        for passport in passports:
            try:
                vr = await research_visa(traveller.id or "unknown", passport, dest_code, client, visa_extraction_provider)
            except Exception as e:  # a single passport lookup must not sink the destination
                vr = VisaResult(
                    traveller_id=traveller.id or "unknown",
                    passport_country=passport,
                    destination_country=dest_code,
                    status=FactResult(status="unavailable", note=f"visa research error: {e}"),
                )
            visa_results.append(vr)

    result.visa_results = visa_results
    result.visa_status = _aggregate_visa_status(visa_results)

    return result


async def run_research(
    candidates: List[Candidate],
    brief: TripBrief,
    *,
    weather_provider: Optional[OpenMeteoWeatherProvider] = None,
    visa_extraction_provider: Optional[VisaExtractionProvider] = None,
) -> List[DestinationResearch]:
    # Wikimedia rejects generic/undescriptive User-Agents with a 403 — their
    # policy requires app name, a contact URL and purpose, so this is not
    # optional decoration. See https://meta.wikimedia.org/wiki/User-Agent_policy
    headers = {
        "User-Agent": (
            "TripMatchResearchBot/0.1 "
            "(https://github.com/wertikooo-web/travel-research; research pipeline, evidence-backed destination facts)"
        )
    }
    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [
            research_candidate(c, brief, client, weather_provider=weather_provider, visa_extraction_provider=visa_extraction_provider)
            for c in candidates
        ]
        return list(await asyncio.gather(*tasks))


def summarize_run_status(results: List[DestinationResearch]) -> str:
    if not results:
        return "failed"
    statuses = set()
    for r in results:
        statuses.update([r.basics_status, r.weather_status, r.visa_status])
    if statuses <= {"success"}:
        return "completed"
    if statuses & {"success", "partial"}:
        return "partial"
    return "failed"
