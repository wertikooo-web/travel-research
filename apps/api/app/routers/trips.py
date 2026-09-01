import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..llm.fake_provider import FakeLLMProvider
from ..llm.provider import LLMConfigError, LLMParseError
from ..schemas import ParseTripRequest, TripBrief

router = APIRouter(prefix="/api/trips", tags=["trips"])


def get_llm_provider():
    if os.environ.get("TRIPMATCH_FAKE_LLM") == "1":
        return FakeLLMProvider()
    try:
        from ..llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    except LLMConfigError as e:
        raise HTTPException(status_code=500, detail=f"LLM not configured: {e}") from e


def _assign_traveller_ids(brief: TripBrief) -> TripBrief:
    for index, traveller in enumerate(brief.travellers, start=1):
        traveller.id = f"traveller_{index}"
    return brief


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

    _assign_traveller_ids(brief)

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
