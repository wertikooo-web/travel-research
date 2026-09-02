import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..llm.fake_candidate_provider import FakeCandidateProvider
from ..llm.fake_provider import FakeLLMProvider
from ..llm.provider import LLMConfigError, LLMParseError
from ..research.candidate_generator import generate_candidates
from ..research.duffel_provider import DuffelConfigError, DuffelFlightProvider
from ..research.flight_pipeline import run_flight_research, summarize_flight_run_status
from ..research.research_pipeline import run_research, summarize_run_status
from ..schemas import Candidate, DestinationResearch, ParseTripRequest, TripBrief

router = APIRouter(prefix="/api/trips", tags=["trips"])


def get_llm_provider():
    if os.environ.get("TRIPMATCH_FAKE_LLM") == "1":
        return FakeLLMProvider()
    try:
        from ..llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    except LLMConfigError as e:
        raise HTTPException(status_code=500, detail=f"LLM not configured: {e}") from e


def get_candidate_provider():
    if os.environ.get("TRIPMATCH_FAKE_LLM") == "1":
        return FakeCandidateProvider()
    try:
        from ..llm.candidate_provider import AnthropicCandidateProvider

        return AnthropicCandidateProvider()
    except LLMConfigError as e:
        raise HTTPException(status_code=500, detail=f"LLM not configured: {e}") from e


def _normalize_traveller_ids(trip: models.Trip, brief: TripBrief, known_ids: set) -> TripBrief:
    """Assign stable, unique traveller ids. The backend is the source of truth:

    - a traveller whose id was already assigned in the brief being edited keeps it;
    - anyone else (newly added, missing id, or an id we don't recognize) gets a
      fresh id from the trip's monotonic counter, which never resets or reuses
      a number freed up by a deleted traveller.
    """
    seen: set = set()
    for traveller in brief.travellers:
        if traveller.id and traveller.id in known_ids and traveller.id not in seen:
            seen.add(traveller.id)
            continue
        trip.traveller_seq += 1
        new_id = f"traveller_{trip.traveller_seq}"
        traveller.id = new_id
        seen.add(new_id)
    return brief


def _known_traveller_ids(record: Optional[models.TripBriefRecord]) -> set:
    if record is None:
        return set()
    travellers = record.structured_brief.get("travellers", [])
    return {t["id"] for t in travellers if t.get("id")}


def _get_trip_or_404(trip_id: str, db: Session) -> models.Trip:
    trip = db.get(models.Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="trip not found")
    return trip


def _latest_brief(trip: models.Trip) -> Optional[models.TripBriefRecord]:
    return trip.briefs[-1] if trip.briefs else None


def _serialize_brief(record: models.TripBriefRecord) -> dict:
    return {
        "id": record.id,
        "trip_id": record.trip_id,
        "version": record.version,
        "raw_request": record.raw_request,
        "structured_brief": record.structured_brief,
        "confirmed_at": record.confirmed_at.isoformat() if record.confirmed_at else None,
    }


@router.post("")
def create_trip(db: Session = Depends(get_db)):
    trip = models.Trip()
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return {"id": trip.id, "public_slug": trip.public_slug, "status": trip.status}


@router.get("/{trip_id}")
def get_trip(trip_id: str, db: Session = Depends(get_db)):
    trip = _get_trip_or_404(trip_id, db)
    latest = _latest_brief(trip)
    return {
        "id": trip.id,
        "public_slug": trip.public_slug,
        "status": trip.status,
        "brief": _serialize_brief(latest) if latest else None,
    }


@router.post("/{trip_id}/parse")
def parse_trip(
    trip_id: str,
    payload: ParseTripRequest,
    db: Session = Depends(get_db),
    llm=Depends(get_llm_provider),
):
    trip = _get_trip_or_404(trip_id, db)

    try:
        brief = llm.parse_brief(payload.raw_text, payload.hints)
    except LLMParseError as e:
        raise HTTPException(status_code=502, detail=f"Could not understand the trip request: {e}") from e

    _normalize_traveller_ids(trip, brief, known_ids=set())

    next_version = len(trip.briefs) + 1
    record = models.TripBriefRecord(
        trip_id=trip.id,
        version=next_version,
        raw_request=payload.raw_text,
        structured_brief=brief.model_dump(mode="json"),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _serialize_brief(record)


@router.put("/{trip_id}/brief")
def update_trip_brief(trip_id: str, brief: TripBrief, db: Session = Depends(get_db)):
    trip = _get_trip_or_404(trip_id, db)
    latest = _latest_brief(trip)
    if latest is None:
        raise HTTPException(status_code=400, detail="no brief to update yet — call parse first")
    if latest.confirmed_at is not None:
        raise HTTPException(status_code=400, detail="brief already confirmed")

    known_ids = _known_traveller_ids(latest)
    _normalize_traveller_ids(trip, brief, known_ids)

    latest.structured_brief = brief.model_dump(mode="json")
    db.commit()
    db.refresh(latest)
    return _serialize_brief(latest)


@router.post("/{trip_id}/confirm")
def confirm_trip_brief(trip_id: str, db: Session = Depends(get_db)):
    trip = _get_trip_or_404(trip_id, db)
    latest = _latest_brief(trip)
    if latest is None:
        raise HTTPException(status_code=400, detail="no brief to confirm yet")
    if latest.confirmed_at is not None:
        raise HTTPException(status_code=400, detail="brief already confirmed")

    latest.confirmed_at = datetime.now(timezone.utc)
    trip.status = "confirmed"
    db.commit()
    db.refresh(latest)
    return _serialize_brief(latest)


def _serialize_candidate_run(run: models.CandidateRun) -> dict:
    return {
        "id": run.id,
        "trip_id": run.trip_id,
        "brief_id": run.brief_id,
        "version": run.version,
        "status": run.status,
        "provider": run.provider,
        "model": run.model,
        "candidate_count": run.candidate_count,
        "error": run.error,
        "candidates": run.candidates or [],
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.post("/{trip_id}/candidates")
def generate_trip_candidates(
    trip_id: str,
    db: Session = Depends(get_db),
    provider=Depends(get_candidate_provider),
):
    trip = _get_trip_or_404(trip_id, db)
    latest = _latest_brief(trip)
    if latest is None or latest.confirmed_at is None:
        raise HTTPException(status_code=400, detail="candidate generation requires a confirmed brief")

    next_version = len(trip.candidate_runs) + 1
    run = models.CandidateRun(
        trip_id=trip.id,
        brief_id=latest.id,
        version=next_version,
        status="pending",
        provider=type(provider).__name__,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        brief = TripBrief.model_validate(latest.structured_brief)
        result = generate_candidates(brief, latest.raw_request, provider)
    except LLMParseError as e:
        run.status = "failed"
        run.error = str(e)
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=502, detail=f"Candidate generation failed: {e}") from e
    except Exception as e:  # malformed/unsalvageable output must not corrupt prior runs
        run.status = "failed"
        run.error = f"unexpected error: {e}"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=502, detail="Candidate generation failed unexpectedly") from e

    run.model = getattr(provider, "model", None)
    run.status = "completed"
    run.candidate_count = len(result.candidates)
    run.candidates = [c.model_dump(mode="json") for c in result.candidates]
    run.raw_llm_output = result.raw_llm_output
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return _serialize_candidate_run(run)


@router.get("/{trip_id}/candidates")
def get_trip_candidates(trip_id: str, db: Session = Depends(get_db)):
    trip = _get_trip_or_404(trip_id, db)
    if not trip.candidate_runs:
        raise HTTPException(status_code=404, detail="no candidate run yet — call POST .../candidates first")
    latest_run = trip.candidate_runs[-1]
    return _serialize_candidate_run(latest_run)


def get_visa_extraction_provider():
    """Optional: the deterministic keyword classifier in research/visa.py
    handles the vast majority of rows on its own. This is only consulted for
    phrasing it doesn't recognize, so its absence degrades gracefully to
    'unknown' for those rows rather than blocking research entirely."""
    if os.environ.get("TRIPMATCH_FAKE_LLM") == "1":
        return None
    try:
        from ..llm.visa_extraction_provider import AnthropicVisaExtractionProvider

        return AnthropicVisaExtractionProvider()
    except LLMConfigError:
        return None


def _serialize_research_run(run: models.ResearchRun) -> dict:
    return {
        "id": run.id,
        "trip_id": run.trip_id,
        "candidate_run_id": run.candidate_run_id,
        "brief_id": run.brief_id,
        "version": run.version,
        "status": run.status,
        "results": run.results or [],
        "warnings": run.warnings or [],
        "error": run.error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.post("/{trip_id}/research")
async def generate_trip_research(
    trip_id: str,
    db: Session = Depends(get_db),
    visa_extraction_provider=Depends(get_visa_extraction_provider),
):
    trip = _get_trip_or_404(trip_id, db)
    latest_brief = _latest_brief(trip)
    if latest_brief is None or latest_brief.confirmed_at is None:
        raise HTTPException(status_code=400, detail="research requires a confirmed brief")
    if not trip.candidate_runs:
        raise HTTPException(status_code=400, detail="research requires an existing candidate run — call POST .../candidates first")

    latest_candidate_run = trip.candidate_runs[-1]
    if latest_candidate_run.status != "completed" or not latest_candidate_run.candidates:
        raise HTTPException(status_code=400, detail="latest candidate run has no candidates to research")

    next_version = len(trip.research_runs) + 1
    run = models.ResearchRun(
        trip_id=trip.id,
        candidate_run_id=latest_candidate_run.id,
        brief_id=latest_brief.id,
        version=next_version,
        status="pending",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        brief = TripBrief.model_validate(latest_brief.structured_brief)
        candidates = [Candidate.model_validate(c) for c in latest_candidate_run.candidates]
        results = await run_research(candidates, brief, visa_extraction_provider=visa_extraction_provider)
    except Exception as e:  # a research-run failure must never corrupt a prior successful run
        run.status = "failed"
        run.error = f"research run failed: {e}"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=502, detail="Research failed unexpectedly") from e

    run.status = summarize_run_status(results)
    run.results = [r.model_dump(mode="json") for r in results]
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return _serialize_research_run(run)


@router.get("/{trip_id}/research")
def get_trip_research(trip_id: str, db: Session = Depends(get_db)):
    trip = _get_trip_or_404(trip_id, db)
    if not trip.research_runs:
        raise HTTPException(status_code=404, detail="no research run yet — call POST .../research first")
    return _serialize_research_run(trip.research_runs[-1])


@router.get("/{trip_id}/research/{run_id}")
def get_trip_research_run(trip_id: str, run_id: str, db: Session = Depends(get_db)):
    trip = _get_trip_or_404(trip_id, db)
    run = next((r for r in trip.research_runs if r.id == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail="research run not found")
    return _serialize_research_run(run)


def get_flight_provider():
    """No fake-mode fallback for real answers: unlike the LLM providers,
    there's no deterministic-by-design substitute for a real Duffel account.
    TRIPMATCH_FAKE_FLIGHTS exists only for exercising the UI end-to-end
    without credentials (mirrors TRIPMATCH_FAKE_LLM) — its offers are
    obviously canned, never presented as live validation."""
    if os.environ.get("TRIPMATCH_FAKE_FLIGHTS") == "1":
        from ..research.duffel_provider import FakeFlightProvider
        from ..schemas import FlightOffer, FlightItinerary, FlightSegment, TransportPlace

        class _AnyQueryPlaces(dict):
            """Dev-only: resolves any place query to the same canned airport,
            so the UI smoke test doesn't depend on which candidate name the
            live LLM happens to generate."""

            def get(self, _key, _default=None):
                return TransportPlace(iata_code="AYT", type="airport", name="Antalya", country_code="TR")

        return FakeFlightProvider(
            places=_AnyQueryPlaces(),
            offers=[
                FlightOffer(
                    id="off_fake_1",
                    outbound=FlightItinerary(
                        segments=[
                            FlightSegment(
                                origin_iata="RMO",
                                destination_iata="AYT",
                                departing_at="2026-10-20T08:00:00",
                                arriving_at="2026-10-20T11:20:00",
                                operating_carrier="Turkish Airlines",
                                marketing_carrier="Turkish Airlines",
                                duration_minutes=200,
                            )
                        ],
                        duration_minutes=200,
                        connections=0,
                    ),
                    return_=FlightItinerary(
                        segments=[
                            FlightSegment(
                                origin_iata="AYT",
                                destination_iata="RMO",
                                departing_at="2026-10-28T13:00:00",
                                arriving_at="2026-10-28T16:20:00",
                                operating_carrier="Turkish Airlines",
                                marketing_carrier="Turkish Airlines",
                                duration_minutes=200,
                            )
                        ],
                        duration_minutes=200,
                        connections=0,
                    ),
                    total_amount=652.44,
                    total_currency="EUR",
                    traveller_count=2,
                    cabin="economy",
                    retrieved_at="2026-09-02T00:00:00Z",
                    expires_at="2026-09-05T00:00:00Z",
                )
            ],
        )
    try:
        return DuffelFlightProvider()
    except DuffelConfigError as e:
        raise HTTPException(status_code=500, detail=f"Flight provider not configured: {e}") from e


def _serialize_flight_run(run: models.FlightRun) -> dict:
    return {
        "id": run.id,
        "trip_id": run.trip_id,
        "candidate_run_id": run.candidate_run_id,
        "research_run_id": run.research_run_id,
        "brief_id": run.brief_id,
        "version": run.version,
        "status": run.status,
        "results": run.results or [],
        "warnings": run.warnings or [],
        "error": run.error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.post("/{trip_id}/flights")
async def generate_trip_flights(
    trip_id: str,
    db: Session = Depends(get_db),
    provider=Depends(get_flight_provider),
):
    trip = _get_trip_or_404(trip_id, db)
    latest_brief = _latest_brief(trip)
    if latest_brief is None or latest_brief.confirmed_at is None:
        raise HTTPException(status_code=400, detail="flight research requires a confirmed brief")
    if not trip.candidate_runs:
        raise HTTPException(status_code=400, detail="flight research requires an existing candidate run")
    latest_candidate_run = trip.candidate_runs[-1]
    if latest_candidate_run.status != "completed" or not latest_candidate_run.candidates:
        raise HTTPException(status_code=400, detail="latest candidate run has no candidates to search flights for")
    if not trip.research_runs:
        raise HTTPException(
            status_code=400, detail="flight research requires an existing research run — call POST .../research first"
        )
    latest_research_run = trip.research_runs[-1]
    if not latest_research_run.results:
        raise HTTPException(status_code=400, detail="latest research run has no destination identities to resolve flights from")

    next_version = len(trip.flight_runs) + 1
    run = models.FlightRun(
        trip_id=trip.id,
        candidate_run_id=latest_candidate_run.id,
        research_run_id=latest_research_run.id,
        brief_id=latest_brief.id,
        version=next_version,
        status="pending",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        brief = TripBrief.model_validate(latest_brief.structured_brief)
        candidates = [Candidate.model_validate(c) for c in latest_candidate_run.candidates]
        research_by_candidate = {
            r["candidate_id"]: DestinationResearch.model_validate(r) for r in latest_research_run.results
        }
        results = await run_flight_research(candidates, research_by_candidate, brief, provider)
    except Exception as e:  # a flight-run failure must never corrupt a prior successful run
        run.status = "failed"
        run.error = f"flight research failed: {e}"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=502, detail="Flight research failed unexpectedly") from e

    run.status = summarize_flight_run_status(results)
    run.results = [r.model_dump(mode="json") for r in results]
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return _serialize_flight_run(run)


@router.get("/{trip_id}/flights")
def get_trip_flights(trip_id: str, db: Session = Depends(get_db)):
    trip = _get_trip_or_404(trip_id, db)
    if not trip.flight_runs:
        raise HTTPException(status_code=404, detail="no flight run yet — call POST .../flights first")
    return _serialize_flight_run(trip.flight_runs[-1])


@router.get("/{trip_id}/flights/{run_id}")
def get_trip_flight_run(trip_id: str, run_id: str, db: Session = Depends(get_db)):
    trip = _get_trip_or_404(trip_id, db)
    run = next((r for r in trip.flight_runs if r.id == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail="flight run not found")
    return _serialize_flight_run(run)
