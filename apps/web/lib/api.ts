import type { BriefRecord, CandidateRun, FlightRun, HotelRun, ResearchRun, TripBrief, TripHints } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new ApiError(0, "Не удалось связаться с сервером. Проверьте, что backend запущен.");
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // ignore non-JSON error bodies
    }
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<T>;
}

export function createTrip() {
  return request<{ id: string; public_slug: string; status: string }>("/api/trips", {
    method: "POST",
  });
}

export function parseTrip(tripId: string, rawText: string, hints?: TripHints) {
  return request<BriefRecord>(`/api/trips/${tripId}/parse`, {
    method: "POST",
    body: JSON.stringify({ raw_text: rawText, hints }),
  });
}

export function updateBrief(tripId: string, brief: TripBrief) {
  return request<BriefRecord>(`/api/trips/${tripId}/brief`, {
    method: "PUT",
    body: JSON.stringify(brief),
  });
}

export function confirmBrief(tripId: string) {
  return request<BriefRecord>(`/api/trips/${tripId}/confirm`, {
    method: "POST",
  });
}

export function generateCandidates(tripId: string) {
  return request<CandidateRun>(`/api/trips/${tripId}/candidates`, {
    method: "POST",
  });
}

export function getCandidates(tripId: string) {
  return request<CandidateRun>(`/api/trips/${tripId}/candidates`, {
    method: "GET",
  });
}

export function generateResearch(tripId: string) {
  return request<ResearchRun>(`/api/trips/${tripId}/research`, {
    method: "POST",
  });
}

export function getResearch(tripId: string) {
  return request<ResearchRun>(`/api/trips/${tripId}/research`, {
    method: "GET",
  });
}

export function generateFlights(tripId: string) {
  return request<FlightRun>(`/api/trips/${tripId}/flights`, {
    method: "POST",
  });
}

export function getFlights(tripId: string) {
  return request<FlightRun>(`/api/trips/${tripId}/flights`, {
    method: "GET",
  });
}

export function generateHotels(tripId: string) {
  return request<HotelRun>(`/api/trips/${tripId}/hotels`, {
    method: "POST",
  });
}

export function getHotels(tripId: string) {
  return request<HotelRun>(`/api/trips/${tripId}/hotels`, {
    method: "GET",
  });
}
