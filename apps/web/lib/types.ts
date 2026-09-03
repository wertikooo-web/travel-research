export type TravellerType = "adult" | "child";
export type PassportType = "biometric" | "ordinary" | "other";
export type RainTolerance = "low" | "medium" | "high";
export type MealPlan = "room_only" | "breakfast" | "half_board" | "full_board" | "all_inclusive";
export type Cabin = "economy" | "premium_economy" | "business" | "first";

export interface Traveller {
  id?: string | null;
  type: TravellerType;
  age?: number | null;
  citizenships?: string[] | null;
  travel_passport?: string | null;
  passport_type?: PassportType | null;
}

export interface Origin {
  text?: string | null;
  iata?: string | null;
}

export interface Dates {
  start?: string | null;
  end?: string | null;
  flex_days?: number | null;
}

export interface Nights {
  min?: number | null;
  max?: number | null;
  preferred?: number | null;
}

export interface Budget {
  currency?: string | null;
  max_total?: number | null;
  hard_constraint?: boolean | null;
}

export interface Flight {
  direct_preferred?: boolean | null;
  max_connections?: number | null;
  max_duration_hours?: number | null;
  preferred_cabin?: Cabin | null;
}

export interface Hotel {
  stars_min?: number | null;
  beachfront?: boolean | null;
  sea_view?: boolean | null;
  meal_min?: MealPlan | null;
}

export interface Weather {
  day_temp_min?: number | null;
  sea_temp_min?: number | null;
  rain_tolerance?: RainTolerance | null;
}

export interface VisaPreferences {
  easy_required?: boolean | null;
}

export interface Preferences {
  avoid: string[];
  prefer: string[];
}

export interface DestinationPick {
  text: string;
  country_code?: string | null;
}

export interface TripBrief {
  origin?: Origin | null;
  travellers: Traveller[];
  dates?: Dates | null;
  nights?: Nights | null;
  budget?: Budget | null;
  flight?: Flight | null;
  hotel?: Hotel | null;
  weather?: Weather | null;
  visa?: VisaPreferences | null;
  preferences?: Preferences | null;
  destination_picks: DestinationPick[];
}

export interface TravellerHint {
  citizenships?: string[] | null;
  travel_passport?: string | null;
}

export interface TripHints {
  origin_text?: string | null;
  date_start?: string | null;
  date_end?: string | null;
  travellers_count?: number | null;
  travellers?: TravellerHint[] | null;
  budget_max_total?: number | null;
  budget_currency?: string | null;
}

export interface BriefRecord {
  id: string;
  trip_id: string;
  version: number;
  raw_request: string | null;
  structured_brief: TripBrief;
  confirmed_at: string | null;
}

export type DestinationType = "city" | "island" | "resort_region" | "country" | "archipelago";
export type CandidateCategory = "core" | "alternative" | "wildcard";
export type CandidateSource = "llm" | "user";

export interface Candidate {
  id: string | null;
  destination_name: string;
  country_code: string | null;
  destination_type: DestinationType | null;
  reason_to_check: string;
  matched_preferences: string[];
  potential_conflicts: string[];
  source: CandidateSource;
  candidate_category: CandidateCategory;
  research_status: "unverified";
}

export interface CandidateRun {
  id: string;
  trip_id: string;
  brief_id: string;
  version: number;
  status: "pending" | "completed" | "failed";
  provider: string | null;
  model: string | null;
  candidate_count: number;
  error: string | null;
  candidates: Candidate[];
  created_at: string;
  completed_at: string | null;
}

// --- Research (Milestone 3) --------------------------------------------------

export type FactStatus = "known" | "unknown" | "unavailable" | "conflicting" | "not_applicable";
export type ComponentStatus = "pending" | "success" | "partial" | "failed" | "unknown";
export type EntryMethodType =
  | "visa_free"
  | "visa_on_arrival"
  | "evisa"
  | "electronic_authorization"
  | "visa_required"
  | "entry_restricted";

export interface Evidence {
  id: string | null;
  source_type: string;
  provider: string;
  url: string | null;
  retrieved_at: string;
  published_or_updated_at: string | null;
  title: string | null;
  raw_excerpt: string | null;
  confidence: "high" | "medium" | "low";
}

export interface FactResult<T> {
  status: FactStatus;
  value: T | null;
  evidence: Evidence[];
  note: string | null;
  is_derived: boolean;
}

export interface EntryMethod {
  method: EntryMethodType;
  allowed_stay_days: number | null;
  notes: string | null;
}

export interface DestinationIdentity {
  display_name: string;
  country_code: string | null;
  destination_type: DestinationType | null;
  parent_country_name: string | null;
  coordinates: { lat: number; lon: number } | null;
  timezone: string | null;
  aliases: string[];
}

export interface WeatherFacts {
  period_basis: "forecast" | "historical_climate" | "historical_observation" | null;
  period_description: string | null;
  day_temp_c: FactResult<number>;
  night_temp_c: FactResult<number>;
  sea_temp_c: FactResult<number>;
  rainy_day_ratio: FactResult<number>;
}

export interface VisaResult {
  traveller_id: string;
  passport_country: string | null;
  destination_country: string | null;
  entry_methods: FactResult<EntryMethod[]>;
  application_method: string | null;
  conditions: string[];
  checked_for_period: string | null;
}

export interface DestinationResearch {
  candidate_id: string;
  identity: DestinationIdentity | null;
  basics_status: ComponentStatus;
  weather: WeatherFacts | null;
  weather_status: ComponentStatus;
  visa_results: VisaResult[];
  visa_status: ComponentStatus;
  warnings: string[];
  errors: string[];
}

export interface ResearchRun {
  id: string;
  trip_id: string;
  candidate_run_id: string;
  brief_id: string;
  version: number;
  status: "pending" | "completed" | "partial" | "failed";
  results: DestinationResearch[];
  warnings: string[];
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

// --- Flight research (Milestone 4) -------------------------------------------

export type FlightPlaceType = "airport" | "city";
export type FlightPassengerType = "adult" | "child" | "infant_without_seat";
export type DateVariant = "exact" | "flex_early" | "flex_center" | "flex_late";
export type ConnectionPolicy = "direct_required" | "direct_preferred" | "max_connections_constraint" | "unspecified";

export interface TransportPlace {
  iata_code: string;
  type: FlightPlaceType;
  name: string;
  country_code: string | null;
  alternate_iata_codes: string[];
}

export interface FlightPassenger {
  traveller_id: string;
  type: FlightPassengerType;
  age: number | null;
}

export interface FlightSearchPlan {
  origin: TransportPlace;
  destination: TransportPlace;
  outbound_date: string;
  return_date: string;
  nights: number;
  date_variant: DateVariant;
  passengers: FlightPassenger[];
  cabin: string;
  max_connections_sent: number;
  connection_policy: ConnectionPolicy;
}

export interface FlightSegment {
  origin_iata: string;
  destination_iata: string;
  departing_at: string;
  arriving_at: string;
  operating_carrier: string | null;
  marketing_carrier: string | null;
  duration_minutes: number | null;
}

export interface FlightItinerary {
  segments: FlightSegment[];
  duration_minutes: number | null;
  connections: number;
}

export interface FlightOffer {
  id: string;
  outbound: FlightItinerary;
  return_: FlightItinerary | null;
  total_amount: number;
  total_currency: string;
  traveller_count: number;
  cabin: string | null;
  retrieved_at: string;
  expires_at: string | null;
}

export interface FlightSearchOutcome {
  plan: FlightSearchPlan;
  status: ComponentStatus;
  offers: FlightOffer[];
  evidence: Evidence | null;
  error: string | null;
  note: string | null;
}

export interface DestinationFlightResearch {
  candidate_id: string;
  origin_place: TransportPlace | null;
  destination_place: TransportPlace | null;
  resolution_status: ComponentStatus;
  date_status: ComponentStatus;
  searches: FlightSearchOutcome[];
  overall_status: ComponentStatus;
  warnings: string[];
  errors: string[];
}

export interface FlightRun {
  id: string;
  trip_id: string;
  candidate_run_id: string;
  research_run_id: string;
  brief_id: string;
  version: number;
  status: "pending" | "completed" | "partial" | "failed";
  results: DestinationFlightResearch[];
  warnings: string[];
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

// --- Hotel research (Milestone 5) --------------------------------------------

export type HotelInspectionStatus = "summary_only" | "rates_fetched" | "rates_fetch_failed";
export type PaymentTiming = "pay_now" | "pay_at_property";

export interface HotelGuest {
  type: TravellerType;
  age: number | null;
}

export interface HotelSearchPlan {
  centre: { lat: number; lon: number };
  radius_km: number;
  check_in: string;
  check_out: string;
  nights: number;
  date_variant: DateVariant;
  rooms: number;
  guests: HotelGuest[];
}

export interface HotelProperty {
  provider_id: string;
  name: string;
  coordinates: { lat: number; lon: number } | null;
  address: string | null;
  country_code: string | null;
  star_rating: FactResult<number>;
  review_score: FactResult<number>;
  review_count: FactResult<number>;
  amenities: string[];
  photos: string[];
  beachfront: FactResult<boolean>;
}

export interface HotelRoom {
  provider_room_id: string;
  name: string;
  description: string | null;
  bed_info: string | null;
  amenities: string[];
  sea_view: FactResult<boolean>;
  balcony: FactResult<boolean>;
}

export interface HotelRate {
  provider_rate_id: string;
  room_id: string;
  total_amount: number;
  total_currency: string;
  nightly_equivalent: FactResult<number>;
  board_type: FactResult<MealPlan>;
  refundable: FactResult<boolean>;
  cancellation_deadline: string | null;
  payment_timing: FactResult<PaymentTiming>;
  taxes_amount: number | null;
  fees_amount: number | null;
  quantity_available: number | null;
}

export interface HotelPropertyResult {
  search_result_id: string;
  property: HotelProperty;
  cheapest_total_amount: number | null;
  cheapest_total_currency: string | null;
  inspection_status: HotelInspectionStatus;
  rooms: HotelRoom[];
  rates: HotelRate[];
  evidence: Evidence;
  rates_evidence: Evidence | null;
  rates_fetch_error: string | null;
}

export interface HotelSearchOutcome {
  plan: HotelSearchPlan;
  status: ComponentStatus;
  properties: HotelPropertyResult[];
  evidence: Evidence | null;
  error: string | null;
  note: string | null;
}

export interface DestinationHotelResearch {
  candidate_id: string;
  geography_status: ComponentStatus;
  date_status: ComponentStatus;
  searches: HotelSearchOutcome[];
  overall_status: ComponentStatus;
  warnings: string[];
  errors: string[];
}

export interface HotelRun {
  id: string;
  trip_id: string;
  candidate_run_id: string;
  research_run_id: string;
  brief_id: string;
  version: number;
  status: "pending" | "completed" | "partial" | "failed";
  results: DestinationHotelResearch[];
  warnings: string[];
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export function emptyTripBrief(): TripBrief {
  return {
    travellers: [],
    preferences: { avoid: [], prefer: [] },
    destination_picks: [],
  };
}
