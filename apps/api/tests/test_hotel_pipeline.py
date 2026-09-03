import asyncio
from datetime import date

import pytest

from app.research.hotel_pipeline import (
    MAX_DEEP_INSPECT_PER_DATE_VARIANT,
    MAX_TOTAL_DEEP_FETCHES_PER_RUN,
    _Budget,
    resolve_hotel_search_plans,
    run_hotel_research,
)
from app.research.hotel_provider import DuffelStaysError, FakeHotelProvider
from app.schemas import (
    Candidate,
    Coordinates,
    Dates,
    DestinationIdentity,
    DestinationResearch,
    Evidence,
    HotelProperty,
    HotelPropertyResult,
    HotelRoom,
    Traveller,
    TripBrief,
)


def _candidate(cid="c1"):
    return Candidate(id=cid, destination_name="Antalya", country_code="TR", reason_to_check="x", source="llm", candidate_category="core")


def _identity(lat=36.9, lon=30.7):
    return DestinationIdentity(display_name="Antalya", country_code="TR", coordinates=Coordinates(lat=lat, lon=lon))


_NOT_GIVEN = object()


def _research(cid="c1", identity=_NOT_GIVEN):
    resolved_identity = _identity() if identity is _NOT_GIVEN else identity
    return DestinationResearch(candidate_id=cid, identity=resolved_identity, basics_status="success")


def _brief(**kwargs):
    kwargs.setdefault("dates", Dates(start=date(2026, 10, 20), end=date(2026, 10, 28)))
    kwargs.setdefault("travellers", [Traveller(id="t1", type="adult")])
    return TripBrief(**kwargs)


def _evidence():
    return Evidence(source_type="structured_travel_provider", provider="Duffel Stays", retrieved_at="2026-09-02T00:00:00Z", confidence="high")


def _property(search_result_id, price=100.0, name="Hotel"):
    return HotelPropertyResult(
        search_result_id=search_result_id,
        property=HotelProperty(provider_id=f"acc_{search_result_id}", name=name, coordinates=Coordinates(lat=36.9, lon=30.7)),
        cheapest_total_amount=price,
        cheapest_total_currency="EUR",
        inspection_status="summary_only",
        evidence=_evidence(),
    )


# --- resolve_hotel_search_plans() (requirements A, B, C, E, F) -------------


def test_unresolved_identity_gives_insufficient_input_no_plans():
    plans, reason = resolve_hotel_search_plans(None, _brief())
    assert plans == []
    assert "insufficient_input" in reason


def test_identity_without_coordinates_gives_insufficient_input():
    identity = DestinationIdentity(display_name="Nowhere")
    plans, reason = resolve_hotel_search_plans(identity, _brief())
    assert plans == []
    assert "insufficient_input" in reason


def test_exact_dates_produce_one_valid_plan_using_verified_coordinates():
    plans, reason = resolve_hotel_search_plans(_identity(lat=1.23, lon=4.56), _brief())
    assert reason is None
    assert len(plans) == 1
    plan = plans[0]
    assert plan.centre.lat == 1.23
    assert plan.centre.lon == 4.56
    assert plan.check_in == date(2026, 10, 20)
    assert plan.check_out == date(2026, 10, 28)
    assert plan.nights == 8
    assert plan.date_variant == "exact"
    assert plan.rooms == 1
    assert len(plan.guests) == 1


def test_month_only_dates_are_insufficient_input_no_fabricated_week():
    brief = TripBrief(dates=Dates(month=10), travellers=[Traveller(id="t1", type="adult")])
    plans, reason = resolve_hotel_search_plans(_identity(), brief)
    assert plans == []
    assert "insufficient_input" in reason


def test_flex_dates_stay_bounded_to_at_most_three_plans():
    brief = TripBrief(
        dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 28), flex_days=3),
        travellers=[Traveller(id="t1", type="adult")],
    )
    plans, reason = resolve_hotel_search_plans(_identity(), brief)
    assert reason is None
    assert len(plans) == 3
    assert {p.date_variant for p in plans} == {"flex_early", "flex_center", "flex_late"}


def test_radius_is_the_explicit_bounded_v0_constant():
    plans, _ = resolve_hotel_search_plans(_identity(), _brief())
    assert plans[0].radius_km == 15.0  # DEFAULT_SEARCH_RADIUS_KM, explicit V0 policy


# --- guest mapping ----------------------------------------------------------


def test_guest_mapping_two_adults():
    brief = _brief(travellers=[Traveller(id="t1", type="adult"), Traveller(id="t2", type="adult")])
    plans, _ = resolve_hotel_search_plans(_identity(), brief)
    guests = plans[0].guests
    assert len(guests) == 2
    assert all(g.type == "adult" for g in guests)


def test_guest_mapping_two_adults_plus_child_with_age():
    brief = _brief(
        travellers=[
            Traveller(id="t1", type="adult"),
            Traveller(id="t2", type="adult"),
            Traveller(id="t3", type="child", age=8),
        ]
    )
    plans, _ = resolve_hotel_search_plans(_identity(), brief)
    guests = plans[0].guests
    assert len(guests) == 3
    child = next(g for g in guests if g.type == "child")
    assert child.age == 8


def test_room_count_is_the_documented_v0_policy_of_one():
    plans, _ = resolve_hotel_search_plans(_identity(), _brief())
    assert plans[0].rooms == 1  # V0 policy: no room-assignment optimizer


# --- run_hotel_research() pipeline-level -----------------------------------


def test_geography_status_unknown_when_identity_unresolved_no_provider_call():
    provider = FakeHotelProvider()
    results = asyncio.run(run_hotel_research([_candidate()], {"c1": _research(identity=None)}, _brief(), provider))
    r = results[0]
    assert r.geography_status == "unknown"
    assert r.overall_status == "unknown"
    assert r.searches == []
    assert provider.search_calls == []  # never called the provider without verified coordinates


def test_successful_zero_properties_is_success_not_failure():
    provider = FakeHotelProvider(properties_by_key={(36.9, 30.7): []})
    results = asyncio.run(run_hotel_research([_candidate()], {"c1": _research()}, _brief(), provider))
    r = results[0]
    assert r.searches[0].status == "success"
    assert r.searches[0].properties == []
    assert "not the same as provider failure" in r.searches[0].note
    assert r.overall_status == "success"


def test_provider_failure_is_not_normalized_to_no_hotels():
    class _FailingProvider(FakeHotelProvider):
        async def search(self, plan, client):
            raise DuffelStaysError("simulated provider outage")

    results = asyncio.run(run_hotel_research([_candidate()], {"c1": _research()}, _brief(), _FailingProvider()))
    r = results[0]
    assert r.searches[0].status == "failed"
    assert r.searches[0].error is not None
    assert r.searches[0].properties == []  # empty because the provider never answered, not a verified zero


def test_summary_result_is_not_marked_rates_verified():
    # a property with no usable price is never selected for deep inspection
    # (Requirement 7's neutral selection criteria), so it must stay
    # summary_only with no room/rate facts fabricated for it
    props = [_property("srr_1")]
    props[0].cheapest_total_amount = None
    provider = FakeHotelProvider(properties_by_key={(36.9, 30.7): props})
    results = asyncio.run(run_hotel_research([_candidate()], {"c1": _research()}, _brief(), provider))
    prop = results[0].searches[0].properties[0]
    assert prop.inspection_status == "summary_only"
    assert prop.rooms == []
    assert prop.rates == []


def test_deep_fetch_promotes_only_the_fetched_property_to_rates_fetched():
    props = [_property("srr_1", price=100), _property("srr_2", price=90)]
    rooms1 = [HotelRoom(provider_room_id="r1", name="Standard")]
    provider = FakeHotelProvider(
        properties_by_key={(36.9, 30.7): props},
        rates_by_search_result_id={"srr_1": (rooms1, [])},  # srr_2 deliberately has no fake rates entry
    )

    # only inspect srr_1 by making srr_2's fetch fail instead of missing —
    # simpler: just assert srr_1 (which has a fake entry) gets fetched given
    # both are within the deep-inspect shortlist size
    results = asyncio.run(run_hotel_research([_candidate()], {"c1": _research()}, _brief(), provider))
    by_id = {p.search_result_id: p for p in results[0].searches[0].properties}
    assert by_id["srr_1"].inspection_status == "rates_fetched"
    assert by_id["srr_1"].rooms == rooms1
    # srr_2 has no fake rates registered -> FakeHotelProvider raises -> isolated failure
    assert by_id["srr_2"].inspection_status == "rates_fetch_failed"
    assert by_id["srr_2"].rates_fetch_error is not None


def test_one_rate_fetch_failure_does_not_kill_the_others_or_the_search():
    props = [_property("srr_1"), _property("srr_2")]
    provider = FakeHotelProvider(
        properties_by_key={(36.9, 30.7): props},
        rates_by_search_result_id={"srr_2": ([], [])},  # srr_1 fails, srr_2 succeeds
    )
    results = asyncio.run(run_hotel_research([_candidate()], {"c1": _research()}, _brief(), provider))
    outcome = results[0].searches[0]
    assert outcome.status == "success"  # the search itself still succeeded
    by_id = {p.search_result_id: p for p in outcome.properties}
    assert by_id["srr_1"].inspection_status == "rates_fetch_failed"
    assert by_id["srr_2"].inspection_status == "rates_fetched"


def test_deep_fetch_cap_is_enforced_by_the_backend_not_the_ui():
    # a pathological result set larger than the per-variant deep-inspect cap
    props = [_property(f"srr_{i}", price=float(i)) for i in range(MAX_DEEP_INSPECT_PER_DATE_VARIANT + 10)]
    rates_map = {p.search_result_id: ([], []) for p in props}  # every property WOULD succeed if fetched
    provider = FakeHotelProvider(properties_by_key={(36.9, 30.7): props}, rates_by_search_result_id=rates_map)

    results = asyncio.run(run_hotel_research([_candidate()], {"c1": _research()}, _brief(), provider))
    outcome = results[0].searches[0]
    fetched = [p for p in outcome.properties if p.inspection_status == "rates_fetched"]
    assert len(fetched) == MAX_DEEP_INSPECT_PER_DATE_VARIANT
    assert len(provider.fetch_calls) == MAX_DEEP_INSPECT_PER_DATE_VARIANT


def test_total_deep_fetch_budget_bounds_across_the_whole_run():
    # many candidates, each with a shortlist -> total deep fetches must not
    # exceed MAX_TOTAL_DEEP_FETCHES_PER_RUN even though each individual
    # search's own shortlist would stay under its own per-variant cap
    n_candidates = 20
    candidates = [_candidate(cid=f"c{i}") for i in range(n_candidates)]
    research_map = {c.id: _research(cid=c.id) for c in candidates}
    props = [_property(f"srr_shared_{i}", price=float(i)) for i in range(3)]
    rates_map = {p.search_result_id: ([], []) for p in props}
    provider = FakeHotelProvider(properties_by_key={(36.9, 30.7): props}, rates_by_search_result_id=rates_map)

    asyncio.run(run_hotel_research(candidates, research_map, _brief(), provider))
    assert len(provider.fetch_calls) <= MAX_TOTAL_DEEP_FETCHES_PER_RUN


def test_deep_inspection_selection_skips_properties_with_no_usable_price():
    props = [_property("srr_no_price"), _property("srr_priced", price=50.0)]
    props[0].cheapest_total_amount = None
    rates_map = {"srr_priced": ([], [])}
    provider = FakeHotelProvider(properties_by_key={(36.9, 30.7): props}, rates_by_search_result_id=rates_map)

    results = asyncio.run(run_hotel_research([_candidate()], {"c1": _research()}, _brief(), provider))
    by_id = {p.search_result_id: p for p in results[0].searches[0].properties}
    assert by_id["srr_no_price"].inspection_status == "summary_only"  # never selected for deep inspection
    assert by_id["srr_priced"].inspection_status == "rates_fetched"


def test_rerun_creates_independent_results_old_run_untouched():
    props_v1 = [_property("srr_1", price=100)]
    provider = FakeHotelProvider(properties_by_key={(36.9, 30.7): props_v1})
    results_v1 = asyncio.run(run_hotel_research([_candidate()], {"c1": _research()}, _brief(), provider))

    props_v2 = [_property("srr_1", price=999)]  # price changed between runs
    provider2 = FakeHotelProvider(properties_by_key={(36.9, 30.7): props_v2})
    results_v2 = asyncio.run(run_hotel_research([_candidate()], {"c1": _research()}, _brief(), provider2))

    assert results_v1[0].searches[0].properties[0].cheapest_total_amount == 100
    assert results_v2[0].searches[0].properties[0].cheapest_total_amount == 999  # independent snapshot, v1 untouched


def test_budget_class_stops_at_limit():
    budget = _Budget(2)
    assert budget.take() is True
    assert budget.take() is True
    assert budget.take() is False
