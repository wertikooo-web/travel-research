"""Deterministic, bounded flight date-plan generation from a confirmed brief.

The line this module exists to hold: historical climate can meaningfully
answer a month-level question ("what's October like?"); a live fare cannot
be honestly priced for a month — it needs an actual date. Wherever the brief
doesn't give (or let us derive) an actual date, this returns zero plans and
an explicit reason, never an invented representative day.

Flex dates never explode into a Cartesian product of outbound x return
combinations (that's the ±3-days-each-way -> 49-combinations trap). The
window shifts as a whole, holding nights constant, at up to three points:
early / center / late. Bounded, deterministic, reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from ..schemas import Dates, Nights

MAX_PLANS_PER_DESTINATION = 3


@dataclass(frozen=True)
class DatePlan:
    outbound_date: date
    return_date: date
    nights: int
    variant: str  # "exact" | "flex_early" | "flex_center" | "flex_late"


def _anchor_nights(nights: Optional[Nights]) -> Optional[int]:
    if nights is None:
        return None
    return nights.preferred if nights.preferred is not None else (nights.min if nights.min is not None else nights.max)


def resolve_date_plans(dates: Optional[Dates], nights: Optional[Nights]) -> tuple[List[DatePlan], Optional[str]]:
    """Returns (plans, insufficiency_reason). Exactly one of them is
    meaningful: a non-empty plan list with reason=None, or an empty list
    with a reason explaining why flight search can't run yet."""
    if dates is None:
        return [], "insufficient_input: no travel dates in the confirmed brief"

    anchor_nights = _anchor_nights(nights)

    if dates.start is not None and dates.end is not None:
        base_outbound = dates.start
        base_nights = (dates.end - dates.start).days
        if base_nights <= 0:
            return [], "insufficient_input: return date is not after the outbound date"
    elif dates.start is not None and anchor_nights is not None:
        base_outbound = dates.start
        base_nights = anchor_nights
    elif dates.end is not None and anchor_nights is not None:
        base_outbound = dates.end - timedelta(days=anchor_nights)
        base_nights = anchor_nights
    else:
        return [], (
            "insufficient_input: only a month/season is known (or dates are missing) — "
            "live flight pricing needs an actual date, unlike historical-climate weather research"
        )

    plans = _build_variants(base_outbound, base_nights, dates.flex_days)
    return plans, None


def _build_variants(base_outbound: date, nights: int, flex_days: Optional[int]) -> List[DatePlan]:
    if not flex_days or flex_days <= 0:
        return [DatePlan(base_outbound, base_outbound + timedelta(days=nights), nights, "exact")]

    offsets = [(-flex_days, "flex_early"), (0, "flex_center"), (flex_days, "flex_late")]
    plans: List[DatePlan] = []
    seen_outbound: set = set()
    for offset, variant in offsets:
        outbound = base_outbound + timedelta(days=offset)
        if outbound in seen_outbound:
            continue  # flex_days could be 0-ish after rounding; never duplicate a plan
        seen_outbound.add(outbound)
        plans.append(DatePlan(outbound, outbound + timedelta(days=nights), nights, variant))
    return plans[:MAX_PLANS_PER_DESTINATION]
