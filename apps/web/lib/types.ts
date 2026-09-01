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

export function emptyTripBrief(): TripBrief {
  return {
    travellers: [],
    preferences: { avoid: [], prefer: [] },
  };
}
