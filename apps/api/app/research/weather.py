"""Weather research — Open-Meteo Archive (air) + Marine (sea) APIs.

For any real travel date this far out, "forecast" would be a lie — so this
always researches *historical climate*: the average of the same calendar
window across several past years. Deterministic HTTP + averaging, no LLM.
Never invents sea temperature: if the marine API has nothing for these
coordinates (e.g. inland), sea_temp_c stays unavailable rather than guessed.
"""

from __future__ import annotations

import asyncio
import calendar
from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

import httpx

from ..schemas import Evidence, FactResult, TripBrief, WeatherFacts

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
HISTORICAL_YEARS_BACK = 3
RAIN_DAY_THRESHOLD_MM = 1.0


class WeatherProviderError(Exception):
    pass


def _resolve_period(brief: TripBrief) -> Optional[Tuple[int, int, int, int]]:
    """(start_month, start_day, end_month, end_day) from the brief only —
    never invents exact dates the traveller didn't give. Exact dates win;
    otherwise a bare month (e.g. "late October") uses that whole month;
    otherwise there's no reproducible period to research at all."""
    dates = brief.dates if brief else None
    if dates is None:
        return None
    if dates.start and dates.end:
        return (dates.start.month, dates.start.day, dates.end.month, dates.end.day)
    if dates.month:
        last_day = calendar.monthrange(2023, dates.month)[1]  # non-leap reference year
        return (dates.month, 1, dates.month, last_day)
    return None


def _historical_ranges(
    period: Tuple[int, int, int, int], years_back: int = HISTORICAL_YEARS_BACK
) -> List[Tuple[date, date]]:
    start_month, start_day, end_month, end_day = period
    this_year = datetime.now(timezone.utc).year
    ranges: List[Tuple[date, date]] = []
    for i in range(1, years_back + 1):
        year = this_year - i
        try:
            start = date(year, start_month, min(start_day, calendar.monthrange(year, start_month)[1]))
            end_year = year if end_month >= start_month else year + 1
            end = date(end_year, end_month, min(end_day, calendar.monthrange(end_year, end_month)[1]))
        except ValueError:
            continue
        if end < start:
            continue
        ranges.append((start, end))
    return ranges


def _unknown_no_period() -> WeatherFacts:
    note = "no travel period in the confirmed brief — nothing to research"
    unknown = lambda: FactResult(status="unknown", note=note)  # noqa: E731
    return WeatherFacts(day_temp_c=unknown(), night_temp_c=unknown(), sea_temp_c=unknown(), rainy_day_ratio=unknown())


class OpenMeteoWeatherProvider:
    async def research(
        self, lat: float, lon: float, brief: TripBrief, client: httpx.AsyncClient
    ) -> Tuple[WeatherFacts, List[Evidence]]:
        period = _resolve_period(brief)
        if period is None:
            return _unknown_no_period(), []

        ranges = _historical_ranges(period)
        if not ranges:
            return _unknown_no_period(), []

        async def fetch_year(start: date, end: date):
            archive = client.get(
                ARCHIVE_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                    "timezone": "auto",
                },
                timeout=20.0,
            )
            marine = client.get(
                MARINE_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "daily": "sea_surface_temperature_max",
                    "timezone": "auto",
                },
                timeout=20.0,
            )
            return await asyncio.gather(archive, marine, return_exceptions=True)

        results = await asyncio.gather(*[fetch_year(s, e) for s, e in ranges])

        day_highs: List[float] = []
        day_lows: List[float] = []
        rain_days = 0
        total_days = 0
        sea_temps: List[float] = []
        successful_years = 0

        for archive_resp, marine_resp in results:
            if isinstance(archive_resp, Exception):
                continue
            try:
                archive_resp.raise_for_status()
                daily = archive_resp.json().get("daily", {})
                highs = [v for v in daily.get("temperature_2m_max", []) if v is not None]
                lows = [v for v in daily.get("temperature_2m_min", []) if v is not None]
                precs = [v for v in daily.get("precipitation_sum", []) if v is not None]
            except (httpx.HTTPError, KeyError, ValueError, TypeError):
                continue
            day_highs.extend(highs)
            day_lows.extend(lows)
            rain_days += sum(1 for p in precs if p >= RAIN_DAY_THRESHOLD_MM)
            total_days += len(precs)
            successful_years += 1

            if not isinstance(marine_resp, Exception):
                try:
                    marine_resp.raise_for_status()
                    sea_vals = marine_resp.json().get("daily", {}).get("sea_surface_temperature_max", [])
                    sea_temps.extend(v for v in sea_vals if v is not None)
                except (httpx.HTTPError, KeyError, ValueError, TypeError):
                    pass

        if successful_years == 0:
            raise WeatherProviderError("all historical weather requests failed")

        retrieved_at = datetime.now(timezone.utc).isoformat()
        years_text = ", ".join(str(s.year) for s, _ in ranges[:successful_years])
        period_desc = (
            f"{ranges[0][0].strftime('%b %d')}–{ranges[0][1].strftime('%b %d')} "
            f"averaged over {successful_years} year(s) ({years_text})"
        )
        evidence = Evidence(
            source_type="weather_provider",
            provider="Open-Meteo Archive",
            url=ARCHIVE_URL,
            retrieved_at=retrieved_at,
            title="Historical daily weather archive",
            raw_excerpt=f"{successful_years} year(s) of daily max/min temperature and precipitation for this window",
            confidence="high",
        )

        def known_or_unavailable(values: List[float], note: Optional[str] = None) -> FactResult:
            if not values:
                return FactResult(status="unavailable", note=note)
            return FactResult(status="known", value=round(sum(values) / len(values), 1), evidence=[evidence])

        facts = WeatherFacts(
            period_basis="historical_climate",
            period_description=period_desc,
            day_temp_c=known_or_unavailable(day_highs, "no daily-max data returned"),
            night_temp_c=known_or_unavailable(day_lows, "no daily-min data returned"),
            rainy_day_ratio=(
                FactResult(status="known", value=round(rain_days / total_days, 2), evidence=[evidence])
                if total_days
                else FactResult(status="unavailable", note="no precipitation data returned")
            ),
            sea_temp_c=known_or_unavailable(sea_temps, "no marine data for these coordinates (likely inland)"),
        )
        return facts, [evidence]
