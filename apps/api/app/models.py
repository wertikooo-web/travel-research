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
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    briefs = relationship(
        "TripBriefRecord",
        back_populates="trip",
        order_by="TripBriefRecord.version",
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
