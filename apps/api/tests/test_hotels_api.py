from datetime import date
from unittest.mock import patch

from app.db import SessionLocal
from app.llm.fake_candidate_provider import FakeCandidateProvider
from app.llm.fake_provider import FakeLLMProvider
from app.main import app
from app.models import HotelRun
from app.research.hotel_provider import FakeHotelProvider
from app.routers.trips import get_candidate_provider, get_hotel_provider, get_llm_provider
from app.schemas import Coordinates, Dates, DestinationIdentity, DestinationHotelResearch, DestinationResearch, Origin, Traveller, TripBrief


def _use_llm(provider):
    app.dependency_overrides[get_llm_provider] = lambda: provider


def _use_candidate_provider(provider):
    app.dependency_overrides[get_candidate_provider] = lambda: provider


def _use_hotel_provider(provider):
    app.dependency_overrides[get_hotel_provider] = lambda: provider


def teardown_function(_fn):
    app.dependency_overrides.clear()


def _raw_candidate(name="Antalya", country_code="TR"):
    return {
        "destination_name": name,
        "country_code": country_code,
        "reason_to_check": "fits the brief",
        "matched_preferences": [],
        "potential_conflicts": [],
        "source": "llm",
        "candidate_category": "core",
    }


def _canned_research_result(candidate_id="cand_1"):
    return DestinationResearch(
        candidate_id=candidate_id,
        identity=DestinationIdentity(display_name="Antalya", country_code="TR", coordinates=Coordinates(lat=36.9, lon=30.7)),
        basics_status="success",
    )


def _confirmed_trip_with_research(client) -> str:
    _use_llm(
        FakeLLMProvider(
            TripBrief(
                origin=Origin(text="Chisinau"),
                dates=Dates(start=date(2026, 10, 20), end=date(2026, 10, 28)),
                travellers=[Traveller(type="adult")],
            )
        )
    )
    trip_id = client.post("/api/trips").json()["id"]
    client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "hi"})
    client.post(f"/api/trips/{trip_id}/confirm")

    _use_candidate_provider(FakeCandidateProvider([_raw_candidate()]))
    client.post(f"/api/trips/{trip_id}/candidates")

    with patch("app.routers.trips.run_research", return_value=[_canned_research_result()]):
        client.post(f"/api/trips/{trip_id}/research")

    return trip_id


def _canned_hotel_result(candidate_id="cand_1"):
    return DestinationHotelResearch(candidate_id=candidate_id, geography_status="success", date_status="success", overall_status="success")


def test_hotels_requires_confirmed_brief(client):
    _use_llm(FakeLLMProvider(TripBrief()))
    _use_hotel_provider(FakeHotelProvider())
    trip_id = client.post("/api/trips").json()["id"]
    client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "hi"})  # not confirmed
    r = client.post(f"/api/trips/{trip_id}/hotels")
    assert r.status_code == 400


def test_hotels_requires_a_candidate_run(client):
    _use_llm(FakeLLMProvider(TripBrief(travellers=[Traveller(type="adult")])))
    _use_hotel_provider(FakeHotelProvider())
    trip_id = client.post("/api/trips").json()["id"]
    client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "hi"})
    client.post(f"/api/trips/{trip_id}/confirm")
    r = client.post(f"/api/trips/{trip_id}/hotels")
    assert r.status_code == 400


def test_hotels_requires_a_research_run(client):
    _use_llm(FakeLLMProvider(TripBrief(travellers=[Traveller(type="adult")])))
    _use_hotel_provider(FakeHotelProvider())
    trip_id = client.post("/api/trips").json()["id"]
    client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "hi"})
    client.post(f"/api/trips/{trip_id}/confirm")
    _use_candidate_provider(FakeCandidateProvider([_raw_candidate()]))
    client.post(f"/api/trips/{trip_id}/candidates")

    r = client.post(f"/api/trips/{trip_id}/hotels")
    assert r.status_code == 400


def test_get_hotels_before_any_run_is_404(client):
    trip_id = _confirmed_trip_with_research(client)
    r = client.get(f"/api/trips/{trip_id}/hotels")
    assert r.status_code == 404


def test_hotels_success_flow_persists_and_returns(client):
    trip_id = _confirmed_trip_with_research(client)
    _use_hotel_provider(FakeHotelProvider())

    with patch("app.routers.trips.run_hotel_research", return_value=[_canned_hotel_result()]):
        r = client.post(f"/api/trips/{trip_id}/hotels")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["version"] == 1
    assert len(body["results"]) == 1
    assert body["results"][0]["candidate_id"] == "cand_1"

    r = client.get(f"/api/trips/{trip_id}/hotels")
    assert r.status_code == 200
    assert r.json()["version"] == 1


def test_second_hotel_run_creates_new_version_first_untouched(client):
    trip_id = _confirmed_trip_with_research(client)
    _use_hotel_provider(FakeHotelProvider())

    with patch("app.routers.trips.run_hotel_research", return_value=[_canned_hotel_result()]):
        r1 = client.post(f"/api/trips/{trip_id}/hotels")
    assert r1.json()["version"] == 1

    with patch("app.routers.trips.run_hotel_research", return_value=[_canned_hotel_result(), _canned_hotel_result("cand_2")]):
        r2 = client.post(f"/api/trips/{trip_id}/hotels")
    assert r2.json()["version"] == 2
    assert len(r2.json()["results"]) == 2

    r_v1 = client.get(f"/api/trips/{trip_id}/hotels/{r1.json()['id']}")
    assert r_v1.status_code == 200
    assert len(r_v1.json()["results"]) == 1  # version 1 untouched by version 2


def test_hotel_run_failure_does_not_corrupt_previous_run(client):
    trip_id = _confirmed_trip_with_research(client)
    _use_hotel_provider(FakeHotelProvider())

    with patch("app.routers.trips.run_hotel_research", return_value=[_canned_hotel_result()]):
        client.post(f"/api/trips/{trip_id}/hotels")

    with patch("app.routers.trips.run_hotel_research", side_effect=RuntimeError("boom")):
        r = client.post(f"/api/trips/{trip_id}/hotels")
    assert r.status_code == 502

    db = SessionLocal()
    try:
        runs = db.query(HotelRun).filter_by(trip_id=trip_id).order_by(HotelRun.version).all()
        assert len(runs) == 2
        assert runs[0].status == "completed"
        assert runs[0].results is not None
        assert runs[1].status == "failed"
        assert runs[1].error is not None
    finally:
        db.close()


def test_hotels_without_credentials_returns_500_not_silent_fallback(client):
    trip_id = _confirmed_trip_with_research(client)

    def raise_config_error():
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail="Hotel provider not configured: DUFFEL_API_KEY is not set")

    app.dependency_overrides[get_hotel_provider] = raise_config_error
    r = client.post(f"/api/trips/{trip_id}/hotels")
    assert r.status_code == 500
