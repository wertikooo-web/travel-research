from datetime import date

from app.research.flight_dates import MAX_PLANS_PER_DESTINATION, resolve_date_plans
from app.schemas import Dates, Nights


def test_case_a_exact_dates_produce_exactly_one_plan():
    dates = Dates(start=date(2026, 10, 20), end=date(2026, 10, 28))
    plans, reason = resolve_date_plans(dates, None)
    assert reason is None
    assert len(plans) == 1
    assert plans[0].outbound_date == date(2026, 10, 20)
    assert plans[0].return_date == date(2026, 10, 28)
    assert plans[0].nights == 8
    assert plans[0].variant == "exact"


def test_case_b_flex_dates_are_bounded_not_a_cartesian_explosion():
    dates = Dates(start=date(2026, 10, 20), end=date(2026, 10, 28), flex_days=3)
    plans, reason = resolve_date_plans(dates, None)
    assert reason is None
    # NOT (2*3+1)^2 = 49, and not even 2*3+1 = 7 - the window shifts as a
    # whole, not outbound/return independently
    assert len(plans) <= MAX_PLANS_PER_DESTINATION
    assert len(plans) == 3
    variants = {p.variant for p in plans}
    assert variants == {"flex_early", "flex_center", "flex_late"}


def test_case_c_every_flex_plan_respects_the_nights_constraint():
    dates = Dates(start=date(2026, 10, 20), end=date(2026, 10, 28), flex_days=3)  # 8 nights
    plans, _ = resolve_date_plans(dates, None)
    for p in plans:
        assert (p.return_date - p.outbound_date).days == 8
        assert p.nights == 8


def test_nights_min_used_when_only_start_date_given():
    dates = Dates(start=date(2026, 10, 20))
    nights = Nights(min=8, max=10, preferred=9)
    plans, reason = resolve_date_plans(dates, nights)
    assert reason is None
    assert len(plans) == 1
    assert plans[0].nights == 9  # preferred wins over min/max
    assert plans[0].return_date == date(2026, 10, 29)


def test_nights_priority_falls_back_to_min_then_max():
    dates = Dates(start=date(2026, 10, 20))
    assert resolve_date_plans(dates, Nights(min=8, max=10))[0][0].nights == 8
    assert resolve_date_plans(dates, Nights(max=10))[0][0].nights == 10


def test_end_date_only_derives_outbound_from_nights():
    dates = Dates(end=date(2026, 10, 28))
    nights = Nights(preferred=8)
    plans, reason = resolve_date_plans(dates, nights)
    assert reason is None
    assert plans[0].outbound_date == date(2026, 10, 20)
    assert plans[0].return_date == date(2026, 10, 28)


def test_case_d_month_only_is_insufficient_input_no_plans():
    dates = Dates(month=10)
    plans, reason = resolve_date_plans(dates, Nights(preferred=8))
    assert plans == []
    assert reason is not None
    assert "insufficient_input" in reason


def test_no_dates_at_all_is_insufficient_input():
    plans, reason = resolve_date_plans(None, Nights(preferred=8))
    assert plans == []
    assert "insufficient_input" in reason


def test_start_date_alone_without_derivable_nights_is_insufficient():
    dates = Dates(start=date(2026, 10, 20))
    plans, reason = resolve_date_plans(dates, None)
    assert plans == []
    assert "insufficient_input" in reason


def test_invalid_range_end_before_start_is_insufficient_not_a_crash():
    dates = Dates(start=date(2026, 10, 28), end=date(2026, 10, 20))
    plans, reason = resolve_date_plans(dates, None)
    assert plans == []
    assert reason is not None
