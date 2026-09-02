import asyncio
from datetime import date

import httpx
import pytest

from app.research.duffel_provider import DuffelFlightProvider
from app.research.flight_pipeline import (
    MAX_TOTAL_SEARCHES_PER_RUN,
    _Budget,
    _resolve_cabin,
    _resolve_connections,
    run_flight_research,
)
from app.schemas import (
    Candidate,
    Coordinates,
    Dates,
    DestinationIdentity,
    DestinationResearch,
    Flight,
    Origin,
    Traveller,
    TripBrief,
)

PLACES = {
    "Antalya": {"iata_code": "AYT", "type": "airport", "name": "Antalya", "iata_country_code": "TR"},
    "Chisinau": {"iata_code": "RMO", "type": "airport", "name": "Chisinau", "iata_country_code": "MD"},
    "Madeira": {"iata_code": "FNC", "type": "airport", "name": "Madeira", "iata_country_code": "PT"},
}


def _candidate(name, country_code, cid="c1"):
    return Candidate(id=cid, destination_name=name, country_code=country_code, reason_to_check="x", source="llm", candidate_category="core")


def _research(identity_name, country_code, lat=36.9, lon=30.7):
    identity = DestinationIdentity(display_name=identity_name, country_code=country_code, coordinates=Coordinates(lat=lat, lon=lon))
    return DestinationResearch(candidate_id="c1", identity=identity, basics_status="success")


def _brief(**flight_kwargs):
    return TripBrief(
        origin=Origin(text="Chisinau"),
        dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 28)),
        travellers=[Traveller(id="t1", type="adult")],
        flight=Flight(**flight_kwargs) if flight_kwargs else None,
    )


def _make_transport(*, search_fails_for=None, offers_by_dest=None):
    search_fails_for = search_fails_for or set()
    offers_by_dest = offers_by_dest or {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "places/suggestions" in url:
            query = httpx.QueryParams(request.url.query).get("query", "")
            place = PLACES.get(query)
            if place is None:
                return httpx.Response(200, json={"data": []})
            return httpx.Response(200, json={"data": [place]})
        if "offer_requests" in url:
            import json

            body = json.loads(request.content)
            dest = body["data"]["slices"][0]["destination"]
            if dest in search_fails_for:
                return httpx.Response(500)
            return httpx.Response(200, json={"data": {"id": "orq_1", "offers": offers_by_dest.get(dest, [])}})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _run(candidates, research_map, brief, transport, provider=None):
    provider = provider or DuffelFlightProvider(api_key="test_key")

    async def go():
        import app.research.flight_pipeline as fp

        original_client_cls = httpx.AsyncClient
        # monkeypatch-free: inject transport via a thin wrapper client factory
        class _Client(httpx.AsyncClient):
            def __init__(self_inner, *a, **kw):
                kw["transport"] = transport
                super().__init__(*a, **kw)

        fp.httpx.AsyncClient = _Client
        try:
            return await run_flight_research(candidates, research_map, brief, provider)
        finally:
            fp.httpx.AsyncClient = original_client_cls

    return asyncio.run(go())


# --- cabin / connection mapping (deterministic, no network needed) ------


def test_cabin_defaults_to_economy_when_unspecified():
    assert _resolve_cabin(_brief()) == "economy"


def test_case_g_cabin_business_mapped_directly():
    assert _resolve_cabin(_brief(preferred_cabin="business")) == "business"


def test_case_e_explicit_max_connections_zero_is_direct_required_hard_constraint():
    max_conn, policy = _resolve_connections(_brief(max_connections=0))
    assert max_conn == 0
    assert policy == "direct_required"


def test_case_f_direct_preferred_is_not_silently_a_hard_direct_only_filter():
    max_conn, policy = _resolve_connections(_brief(direct_preferred=True))
    assert policy == "direct_preferred"
    assert max_conn != 0  # a preference, not converted into max_connections=0


def test_explicit_nonzero_max_connections_is_a_hard_constraint_not_direct_required():
    max_conn, policy = _resolve_connections(_brief(max_connections=2))
    assert max_conn == 2
    assert policy == "max_connections_constraint"


def test_unspecified_connections_policy():
    max_conn, policy = _resolve_connections(_brief())
    assert policy == "unspecified"


# --- pipeline-level (mocked Duffel) --------------------------------------


def test_full_search_success():
    candidates = [_candidate("Antalya", "TR")]
    research_map = {"c1": _research("Antalya", "TR")}
    result = _run(candidates, research_map, _brief(), _make_transport())[0]

    assert result.resolution_status == "success"
    assert result.date_status == "success"
    assert result.destination_place.iata_code == "AYT"
    assert result.origin_place.iata_code == "RMO"
    assert len(result.searches) == 1  # exact dates -> one plan
    assert result.overall_status == "success"


def test_case_h_unresolved_origin_no_search_attempted():
    candidates = [_candidate("Antalya", "TR")]
    research_map = {"c1": _research("Antalya", "TR")}
    brief = _brief()
    brief.origin = None

    result = _run(candidates, research_map, brief, _make_transport())[0]
    assert result.origin_place is None
    assert result.resolution_status == "unknown"
    assert result.searches == []


def test_case_i_unresolved_destination_no_search_attempted():
    candidates = [_candidate("Nowhereville", "ZZ")]
    research_map = {"c1": _research("Nowhereville", "ZZ")}  # not in PLACES fixture -> Duffel finds nothing

    result = _run(candidates, research_map, _brief(), _make_transport())[0]
    assert result.destination_place is None
    assert result.resolution_status == "unknown"
    assert result.searches == []


def test_case_d_month_only_dates_produce_no_search_and_unknown_status():
    candidates = [_candidate("Antalya", "TR")]
    research_map = {"c1": _research("Antalya", "TR")}
    brief = TripBrief(origin=Origin(text="Chisinau"), dates=Dates(month=10), travellers=[Traveller(id="t1", type="adult")])

    result = _run(candidates, research_map, brief, _make_transport())[0]
    assert result.resolution_status == "success"  # place resolution itself is fine
    assert result.date_status == "unknown"
    assert result.searches == []
    assert result.overall_status == "unknown"
    assert any("insufficient_input" in w for w in result.warnings)


def test_case_l_zero_offers_is_a_successful_search_not_a_failure():
    candidates = [_candidate("Antalya", "TR")]
    research_map = {"c1": _research("Antalya", "TR")}
    result = _run(candidates, research_map, _brief(), _make_transport(offers_by_dest={"AYT": []}))[0]

    assert result.searches[0].status == "success"
    assert result.searches[0].offers == []
    assert result.searches[0].error is None
    assert "no offers" in result.searches[0].note


def test_case_m_provider_timeout_is_failed_never_zero_flights():
    candidates = [_candidate("Antalya", "TR")]
    research_map = {"c1": _research("Antalya", "TR")}
    result = _run(candidates, research_map, _brief(), _make_transport(search_fails_for={"AYT"}))[0]

    assert result.searches[0].status == "failed"
    assert result.searches[0].error is not None
    assert result.searches[0].offers == []  # empty because it never got an answer, not because zero was verified


def test_case_n_mixed_destination_results_one_fails_other_succeeds():
    candidates = [_candidate("Antalya", "TR", cid="c1"), _candidate("Madeira", "PT", cid="c2")]
    research_map = {
        "c1": DestinationResearch(candidate_id="c1", identity=DestinationIdentity(display_name="Antalya", country_code="TR", coordinates=Coordinates(lat=1, lon=1))),
        "c2": DestinationResearch(candidate_id="c2", identity=DestinationIdentity(display_name="Madeira", country_code="PT", coordinates=Coordinates(lat=2, lon=2))),
    }
    results = _run(candidates, research_map, _brief(), _make_transport(search_fails_for={"FNC"}))
    by_id = {r.candidate_id: r for r in results}
    assert by_id["c1"].overall_status == "success"
    assert by_id["c2"].overall_status == "failed"


def test_case_q_request_budget_is_never_exceeded():
    # 25 destinations x up to 3 flex plans each = 75 > MAX_TOTAL_SEARCHES_PER_RUN(60):
    # the budget must cap total Duffel searches across the whole run
    candidates = [_candidate("Antalya", "TR", cid=f"c{i}") for i in range(25)]
    research_map = {
        c.id: DestinationResearch(candidate_id=c.id, identity=DestinationIdentity(display_name="Antalya", country_code="TR", coordinates=Coordinates(lat=1, lon=1)))
        for c in candidates
    }
    brief = TripBrief(
        origin=Origin(text="Chisinau"),
        dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 28), flex_days=3),
        travellers=[Traveller(id="t1", type="adult")],
    )
    results = _run(candidates, research_map, brief, _make_transport())
    total_searches = sum(len(r.searches) for r in results)
    assert total_searches <= MAX_TOTAL_SEARCHES_PER_RUN
    assert any("budget" in w for r in results for w in r.warnings)


def test_budget_class_stops_at_limit():
    budget = _Budget(2)
    assert budget.take() is True
    assert budget.take() is True
    assert budget.take() is False
