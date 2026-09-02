from __future__ import annotations

from datetime import date
from typing import Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

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
    # Set when the traveller named a month/season but no exact days ("late
    # October", "in February") — the common case M1 correctly leaves start/end
    # null for. Without this, research has no reproducible period signal at
    # all for that case short of re-reading raw text. 1-12, additive/optional,
    # old briefs default to null.
    month: Optional[int] = None

    @field_validator("month")
    @classmethod
    def _validate_month(cls, v):
        if v is not None and not (1 <= v <= 12):
            raise ValueError("month must be between 1 and 12")
        return v


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


# --- Research (Milestone 3) --------------------------------------------------
#
# "known" vs "unknown" vs "unavailable" vs "conflicting" vs "not_applicable"
# must never collapse into the same null the way a plain Optional[T] would:
# "direct flight unknown" must never behave like "direct flight doesn't exist".
# Every factual field below is a FactResult, not a bare Optional.

FactStatus = Literal["known", "unknown", "unavailable", "conflicting", "not_applicable"]

EvidenceSourceType = Literal[
    "official_government",
    "embassy_consular",
    "citizenship_country_authority",
    "structured_travel_provider",
    "secondary_travel_site",
    "weather_provider",
    "geo_provider",
]
EvidenceConfidence = Literal["high", "medium", "low"]
ComponentStatus = Literal["pending", "success", "partial", "failed", "unknown"]
WeatherPeriodBasis = Literal["forecast", "historical_climate", "historical_observation"]

# Every value a source can state a traveller actually gets, not a status of
# our confidence — "we don't know" lives in FactResult.status, never here.
EntryMethodType = Literal[
    "visa_free",
    "visa_on_arrival",
    "evisa",
    "electronic_authorization",
    "visa_required",
    "entry_restricted",
]


class Evidence(BaseModel):
    """The one reusable provenance object every factual claim points to —
    weather, visa, and (later) flights/hotels/prices/safety alike. No source
    -> no verified fact. Deliberately small: metadata for traceability and
    debugging, never a copy of the source page."""

    id: Optional[str] = None  # assigned by the backend
    source_type: EvidenceSourceType
    provider: str
    url: Optional[str] = None
    retrieved_at: str
    published_or_updated_at: Optional[str] = None
    title: Optional[str] = None
    raw_excerpt: Optional[str] = None
    confidence: EvidenceConfidence = "medium"


ResearchValueT = TypeVar("ResearchValueT")


class FactResult(BaseModel, Generic[ResearchValueT]):
    """The one wrapper every research fact goes through. Structurally
    enforced, not just conventional:

    - `known` always has a value.
    - `known` AND sourced (`is_derived=False`, the default) always has
      evidence — "no source, no verified fact" is unenforceable as a
      convention, so it's enforced here instead.
    - `unknown` / `unavailable` / `not_applicable` never carry a value —
      "we don't know" must never be representable as a fact that happens to
      equal the right answer.
    - `conflicting` always carries the evidence responsible for the
      conflict (that's the whole point of the state).

    `is_derived=True` is the deliberate escape hatch for a future fact
    computed from other already-evidenced FactResults (e.g. a scoring
    layer's rollup) — it doesn't need its own fresh external source, since
    its truth traces through inputs that already carry theirs. Without this
    flag every derived value would need to fake a source to pass validation,
    which would be worse than not validating at all.
    """

    status: FactStatus
    value: Optional[ResearchValueT] = None
    evidence: List[Evidence] = Field(default_factory=list)
    note: Optional[str] = None
    is_derived: bool = False

    @model_validator(mode="after")
    def _enforce_evidence_invariant(self):
        if self.status == "known":
            if self.value is None:
                raise ValueError("a 'known' FactResult must have a value")
            if not self.is_derived and not self.evidence:
                raise ValueError(
                    "a 'known' sourced FactResult must carry evidence (no source, no verified fact) — "
                    "set is_derived=True if this is computed from other already-evidenced facts"
                )
        elif self.status in ("unknown", "unavailable", "not_applicable"):
            if self.value is not None:
                raise ValueError(f"a '{self.status}' FactResult must not carry a value")
        elif self.status == "conflicting":
            if not self.evidence:
                raise ValueError("a 'conflicting' FactResult must carry the evidence responsible for the conflict")
        return self


def _unknown_fact() -> FactResult:
    return FactResult(status="unknown")


class Coordinates(BaseModel):
    lat: float
    lon: float


class DestinationIdentity(BaseModel):
    """Milestone 2 identified destinations by string. Sources call the same
    place different things, so research needs something slightly stronger —
    not a global geography service, just enough to avoid obvious mismatches."""

    display_name: str
    country_code: Optional[str] = None
    destination_type: Optional[DestinationType] = None
    parent_country_name: Optional[str] = None
    coordinates: Optional[Coordinates] = None
    timezone: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)


class WeatherFacts(BaseModel):
    period_basis: Optional[WeatherPeriodBasis] = None
    period_description: Optional[str] = None
    day_temp_c: FactResult[float] = Field(default_factory=_unknown_fact)
    night_temp_c: FactResult[float] = Field(default_factory=_unknown_fact)
    sea_temp_c: FactResult[float] = Field(default_factory=_unknown_fact)
    rainy_day_ratio: FactResult[float] = Field(default_factory=_unknown_fact)


class EntryMethod(BaseModel):
    """One valid way to enter — a source often states more than one at once
    ("visa on arrival / eVisa"), and that's materially different information
    from either option alone. Never collapse a source's options down to a
    single value just because the field used to only hold one."""

    method: EntryMethodType
    allowed_stay_days: Optional[int] = None
    notes: Optional[str] = None


class VisaResult(BaseModel):
    """Visa status belongs to destination + traveller + passport + travel
    period — never to the trip as a whole. One of these per passport a
    traveller actually holds, never collapsed into a single group verdict.

    `entry_methods` holds every distinct option the source actually states,
    not just the first one a keyword scan happens to hit — a group-level
    scoring layer later can pick "the easiest available method" itself
    without this layer having pre-decided and discarded the alternatives."""

    traveller_id: str
    passport_country: Optional[str] = None  # null only when the traveller's passport itself is unknown
    destination_country: Optional[str] = None
    entry_methods: FactResult[List[EntryMethod]] = Field(default_factory=_unknown_fact)
    application_method: Optional[str] = None
    conditions: List[str] = Field(default_factory=list)
    checked_for_period: Optional[str] = None


class DestinationResearch(BaseModel):
    candidate_id: str
    identity: Optional[DestinationIdentity] = None
    basics_status: ComponentStatus = "pending"
    weather: Optional[WeatherFacts] = None
    weather_status: ComponentStatus = "pending"
    visa_results: List[VisaResult] = Field(default_factory=list)
    visa_status: ComponentStatus = "pending"
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class ResearchRunSummary(BaseModel):
    id: str
    trip_id: str
    candidate_run_id: str
    brief_id: str
    version: int
    status: Literal["pending", "completed", "partial", "failed"]
    results: List[DestinationResearch] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
