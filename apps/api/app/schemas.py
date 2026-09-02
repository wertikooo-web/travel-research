from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

TravellerType = Literal["adult", "child"]
PassportType = Literal["biometric", "ordinary", "other"]
RainTolerance = Literal["low", "medium", "high"]
MealPlan = Literal["room_only", "breakfast", "half_board", "full_board", "all_inclusive"]
Cabin = Literal["economy", "premium_economy", "business", "first"]


def _iso2(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip().upper()
    return value or None


class Traveller(BaseModel):
    id: Optional[str] = None
    type: TravellerType = "adult"
    age: Optional[int] = None
    citizenships: Optional[List[str]] = None
    travel_passport: Optional[str] = None
    passport_type: Optional[PassportType] = None

    @field_validator("citizenships", mode="before")
    @classmethod
    def _norm_citizenships(cls, v):
        if v is None:
            return None
        cleaned = [c.strip().upper() for c in v if c and str(c).strip()]
        return cleaned or None

    @field_validator("travel_passport", mode="before")
    @classmethod
    def _norm_passport(cls, v):
        return _iso2(v)


class Origin(BaseModel):
    text: Optional[str] = None
    iata: Optional[str] = None


class Dates(BaseModel):
    start: Optional[date] = None
    end: Optional[date] = None
    flex_days: Optional[int] = None


class Nights(BaseModel):
    min: Optional[int] = None
    max: Optional[int] = None
    preferred: Optional[int] = None


class Budget(BaseModel):
    currency: Optional[str] = None
    max_total: Optional[float] = None
    hard_constraint: Optional[bool] = None


class Flight(BaseModel):
    direct_preferred: Optional[bool] = None
    max_connections: Optional[int] = None
    max_duration_hours: Optional[float] = None
    preferred_cabin: Optional[Cabin] = None


class Hotel(BaseModel):
    stars_min: Optional[int] = None
    beachfront: Optional[bool] = None
    sea_view: Optional[bool] = None
    meal_min: Optional[MealPlan] = None


class Weather(BaseModel):
    day_temp_min: Optional[float] = None
    sea_temp_min: Optional[float] = None
    rain_tolerance: Optional[RainTolerance] = None


class VisaPreferences(BaseModel):
    easy_required: Optional[bool] = None


class Preferences(BaseModel):
    avoid: List[str] = Field(default_factory=list)
    prefer: List[str] = Field(default_factory=list)


class DestinationPick(BaseModel):
    """A destination the traveller explicitly named — user intent, not an LLM
    hypothesis. Confirmed as part of TripBrief; CandidateGenerator treats
    every entry here as a deterministic guarantee, never a suggestion."""

    text: str
    country_code: Optional[str] = None

    @field_validator("country_code", mode="before")
    @classmethod
    def _norm_country_code(cls, v):
        return _iso2(v)

    @field_validator("text", mode="before")
    @classmethod
    def _norm_text(cls, v):
        return v.strip() if isinstance(v, str) else v


class TripBrief(BaseModel):
    origin: Optional[Origin] = None
    travellers: List[Traveller] = Field(default_factory=list)
    dates: Optional[Dates] = None
    nights: Optional[Nights] = None
    budget: Optional[Budget] = None
    flight: Optional[Flight] = None
    hotel: Optional[Hotel] = None
    weather: Optional[Weather] = None
    visa: Optional[VisaPreferences] = None
    preferences: Optional[Preferences] = None
    destination_picks: List[DestinationPick] = Field(default_factory=list)


class TravellerHint(BaseModel):
    citizenships: Optional[List[str]] = None
    travel_passport: Optional[str] = None


class TripHints(BaseModel):
    """Optional structured values pre-filled on the home screen before parsing."""

    origin_text: Optional[str] = None
    date_start: Optional[date] = None
    date_end: Optional[date] = None
    travellers_count: Optional[int] = None
    travellers: Optional[List[TravellerHint]] = None
    budget_max_total: Optional[float] = None
    budget_currency: Optional[str] = None


class ParseTripRequest(BaseModel):
    raw_text: str
    hints: Optional[TripHints] = None


# --- Candidate generation (Milestone 2) -------------------------------------

DestinationType = Literal["city", "island", "resort_region", "country", "archipelago"]
CandidateCategory = Literal["core", "alternative", "wildcard"]
CandidateSource = Literal["llm", "user"]


class Candidate(BaseModel):
    """A destination worth researching further — a hypothesis, not a verified fact.

    Every field here is either the LLM's reasoning or a normalization-layer
    decision. Nothing about actual flights, hotels, prices, weather, visas or
    safety belongs on this model — those are verified facts that later
    milestones attach, never something this generator is allowed to assert.
    """

    id: Optional[str] = None  # assigned by the backend, never trusted from the LLM
    destination_name: str
    country_code: Optional[str] = None
    destination_type: Optional[DestinationType] = None
    reason_to_check: str
    matched_preferences: List[str] = Field(default_factory=list)
    potential_conflicts: List[str] = Field(default_factory=list)
    source: CandidateSource = "llm"
    candidate_category: CandidateCategory = "core"
    research_status: Literal["unverified"] = "unverified"

    @field_validator("country_code", mode="before")
    @classmethod
    def _norm_country_code(cls, v):
        return _iso2(v)

    @field_validator("destination_name", mode="before")
    @classmethod
    def _norm_destination_name(cls, v):
        return v.strip() if isinstance(v, str) else v


class CandidateGenerationRequest(BaseModel):
    """Currently no user-provided fields — the confirmed brief is the only input.
    Kept as its own model so future overrides (e.g. custom limits) don't
    require breaking the endpoint's request shape."""


class CandidateRunSummary(BaseModel):
    id: str
    trip_id: str
    brief_id: str
    version: int
    status: Literal["pending", "completed", "failed"]
    provider: Optional[str] = None
    model: Optional[str] = None
    candidate_count: int = 0
    error: Optional[str] = None
    candidates: List[Candidate] = Field(default_factory=list)
    created_at: str
    completed_at: Optional[str] = None
