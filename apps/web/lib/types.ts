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

export function emptyTripBrief(): TripBrief {
  return {
    travellers: [],
    preferences: { avoid: [], prefer: [] },
    destination_picks: [],
  };
}
