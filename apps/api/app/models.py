import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .db import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Trip(Base):
    __tablename__ = "trips"

    id = Column(String, primary_key=True, default=gen_uuid)
    public_slug = Column(String, unique=True, index=True, default=gen_uuid)
    status = Column(String, nullable=False, default="draft")
    currency = Column(String, nullable=True)
    traveller_seq = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    briefs = relationship(
        "TripBriefRecord",
        back_populates="trip",
        order_by="TripBriefRecord.version",
    )
    candidate_runs = relationship(
        "CandidateRun",
        back_populates="trip",
        order_by="CandidateRun.version",
    )
    research_runs = relationship(
        "ResearchRun",
        back_populates="trip",
        order_by="ResearchRun.version",
    )
    flight_runs = relationship(
        "FlightRun",
        back_populates="trip",
        order_by="FlightRun.version",
    )
    hotel_runs = relationship(
        "HotelRun",
        back_populates="trip",
        order_by="HotelRun.version",
    )


class TripBriefRecord(Base):
    __tablename__ = "trip_briefs"

    id = Column(String, primary_key=True, default=gen_uuid)
    trip_id = Column(String, ForeignKey("trips.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    raw_request = Column(String, nullable=True)
    structured_brief = Column(JSON, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    trip = relationship("Trip", back_populates="briefs")


class CandidateRun(Base):
    """One candidate-generation attempt for a confirmed TripBrief.

    Separate from TripBrief on purpose: the brief is the traveller's intent,
    this is the system's research output for one version of that intent.
    Runs are immutable once created and never overwrite each other, so brief
    v1 -> run 1 and brief v2 -> run 2 can be compared later.
    """

    __tablename__ = "candidate_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    trip_id = Column(String, ForeignKey("trips.id"), nullable=False)
    brief_id = Column(String, ForeignKey("trip_briefs.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="pending")  # pending|completed|failed
    provider = Column(String, nullable=True)
    model = Column(String, nullable=True)
    candidate_count = Column(Integer, nullable=False, default=0)
    error = Column(String, nullable=True)
    raw_llm_output = Column(JSON, nullable=True)
    candidates = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)

    trip = relationship("Trip", back_populates="candidate_runs")


class ResearchRun(Base):
    """One evidence-gathering pass over a CandidateRun's destinations.

    Same immutability contract as CandidateRun: a rerun creates version N+1
    and never touches version N, so historical research stays inspectable
    even after the traveller edits their brief or the candidate pool changes.
    """

    __tablename__ = "research_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    trip_id = Column(String, ForeignKey("trips.id"), nullable=False)
    candidate_run_id = Column(String, ForeignKey("candidate_runs.id"), nullable=False)
    brief_id = Column(String, ForeignKey("trip_briefs.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="pending")  # pending|completed|partial|failed
    results = Column(JSON, nullable=True)  # List[DestinationResearch]
    warnings = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)

    trip = relationship("Trip", back_populates="research_runs")


class FlightRun(Base):
    """One flight-search pass over a ResearchRun's resolved destinations.

    Depends on candidate_run_id (which candidates) AND research_run_id
    (whose DestinationIdentity to resolve transport places from) — flight
    place resolution consumes M3's geocoded identity, not the raw candidate
    name. Same immutability contract as CandidateRun/ResearchRun: a rerun is
    version N+1, and yesterday's now-expired offers stay exactly as
    retrieved in version N — they're a historical snapshot, not something a
    rerun is allowed to erase.
    """

    __tablename__ = "flight_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    trip_id = Column(String, ForeignKey("trips.id"), nullable=False)
    candidate_run_id = Column(String, ForeignKey("candidate_runs.id"), nullable=False)
    research_run_id = Column(String, ForeignKey("research_runs.id"), nullable=False)
    brief_id = Column(String, ForeignKey("trip_briefs.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="pending")  # pending|completed|partial|failed
    results = Column(JSON, nullable=True)  # List[DestinationFlightResearch]
    warnings = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)

    trip = relationship("Trip", back_populates="flight_runs")


class HotelRun(Base):
    """One hotel-search pass over a ResearchRun's resolved destinations.

    Same dependency shape and immutability contract as FlightRun: depends on
    candidate_run_id (which candidates) and research_run_id (whose
    DestinationIdentity to search hotel geography from). A rerun is version
    N+1; yesterday's prices/availability stay exactly as retrieved in
    version N — a historical snapshot, never overwritten.
    """

    __tablename__ = "hotel_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    trip_id = Column(String, ForeignKey("trips.id"), nullable=False)
    candidate_run_id = Column(String, ForeignKey("candidate_runs.id"), nullable=False)
    research_run_id = Column(String, ForeignKey("research_runs.id"), nullable=False)
    brief_id = Column(String, ForeignKey("trip_briefs.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="pending")  # pending|completed|partial|failed
    results = Column(JSON, nullable=True)  # List[DestinationHotelResearch]
    warnings = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)

    trip = relationship("Trip", back_populates="hotel_runs")
