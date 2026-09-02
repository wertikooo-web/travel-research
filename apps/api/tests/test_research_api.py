from unittest.mock import patch

from app.db import SessionLocal
from app.llm.fake_candidate_provider import FakeCandidateProvider
from app.llm.fake_provider import FakeLLMProvider
from app.main import app
from app.models import ResearchRun
from app.routers.trips import get_candidate_provider, get_llm_provider
from app.schemas import DestinationResearch, Traveller, TripBrief


def _use_llm(provider):
    app.dependency_overrides[get_llm_provider] = lambda: provider


def _use_candidate_provider(provider):
    app.dependency_overrides[get_candidate_provider] = lambda: provider


def teardown_function(_fn):
    app.dependency_overrides.clear()


def _raw_candidate(name="Tenerife", country_code="ES"):
    return {
        "destination_name": name,
        "country_code": country_code,
        "reason_to_check": "fits the brief",
        "matched_preferences": [],
        "potential_conflicts": [],
        "source": "llm",
        "candidate_category": "core",
    }


def _confirmed_trip_with_candidates(client) -> str:
    _use_llm(FakeLLMProvider(TripBrief(travellers=[Traveller(type="adult")])))
    trip_id = client.post("/api/trips").json()["id"]
    client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "hi"})
    client.post(f"/api/trips/{trip_id}/confirm")
    _use_candidate_provider(FakeCandidateProvider([_raw_candidate()]))
    client.post(f"/api/trips/{trip_id}/candidates")
    return trip_id


def _canned_result(candidate_id="cand_1"):
    return DestinationResearch(candidate_id=candidate_id, basics_status="success", weather_status="success", visa_status="success")


def test_research_requires_confirmed_brief(client):
    _use_llm(FakeLLMProvider(TripBrief()))
    trip_id = client.post("/api/trips").json()["id"]
    client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "hi"})  # not confirmed
    r = client.post(f"/api/trips/{trip_id}/research")
    assert r.status_code == 400


def test_research_requires_a_candidate_run(client):
    _use_llm(FakeLLMProvider(TripBrief(travellers=[Traveller(type="adult")])))
    trip_id = client.post("/api/trips").json()["id"]
    client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "hi"})
    client.post(f"/api/trips/{trip_id}/confirm")
    r = client.post(f"/api/trips/{trip_id}/research")
    assert r.status_code == 400


def test_get_research_before_any_run_is_404(client):
    trip_id = _confirmed_trip_with_candidates(client)
    r = client.get(f"/api/trips/{trip_id}/research")
    assert r.status_code == 404


def test_research_success_flow_persists_and_returns(client):
    trip_id = _confirmed_trip_with_candidates(client)

    with patch("app.routers.trips.run_research", return_value=[_canned_result()]):
        r = client.post(f"/api/trips/{trip_id}/research")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["version"] == 1
    assert len(body["results"]) == 1
    assert body["results"][0]["candidate_id"] == "cand_1"

    r = client.get(f"/api/trips/{trip_id}/research")
    assert r.status_code == 200
    assert r.json()["version"] == 1


def test_second_research_run_creates_new_version(client):
    trip_id = _confirmed_trip_with_candidates(client)

    with patch("app.routers.trips.run_research", return_value=[_canned_result()]):
        r1 = client.post(f"/api/trips/{trip_id}/research")
    assert r1.json()["version"] == 1

    with patch("app.routers.trips.run_research", return_value=[_canned_result(), _canned_result("cand_2")]):
        r2 = client.post(f"/api/trips/{trip_id}/research")
    assert r2.json()["version"] == 2
    assert len(r2.json()["results"]) == 2

    r = client.get(f"/api/trips/{trip_id}/research")
    assert r.json()["version"] == 2

    r_v1 = client.get(f"/api/trips/{trip_id}/research/{r1.json()['id']}")
    assert r_v1.status_code == 200
    assert len(r_v1.json()["results"]) == 1  # version 1 is untouched by version 2


def test_research_failure_does_not_corrupt_previous_run(client):
    trip_id = _confirmed_trip_with_candidates(client)

    with patch("app.routers.trips.run_research", return_value=[_canned_result()]):
        client.post(f"/api/trips/{trip_id}/research")

    with patch("app.routers.trips.run_research", side_effect=RuntimeError("boom")):
        r = client.post(f"/api/trips/{trip_id}/research")
    assert r.status_code == 502

    db = SessionLocal()
    try:
        runs = db.query(ResearchRun).filter_by(trip_id=trip_id).order_by(ResearchRun.version).all()
        assert len(runs) == 2
        assert runs[0].status == "completed"
        assert runs[0].results is not None  # untouched
        assert runs[1].status == "failed"
        assert runs[1].error is not None
    finally:
        db.close()
