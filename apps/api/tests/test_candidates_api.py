from app.db import SessionLocal
from app.llm.fake_candidate_provider import FakeCandidateProvider
from app.llm.fake_provider import FakeLLMProvider
from app.llm.provider import LLMParseError
from app.main import app
from app.models import CandidateRun
from app.routers.trips import get_candidate_provider, get_llm_provider
from app.schemas import Traveller, TripBrief


def _use_llm(provider):
    app.dependency_overrides[get_llm_provider] = lambda: provider


def _use_candidate_provider(provider):
    app.dependency_overrides[get_candidate_provider] = lambda: provider


def teardown_function(_fn):
    app.dependency_overrides.clear()


def _confirmed_trip(client) -> str:
    _use_llm(FakeLLMProvider(TripBrief(travellers=[Traveller(type="adult")])))
    trip_id = client.post("/api/trips").json()["id"]
    client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "hi"})
    client.post(f"/api/trips/{trip_id}/confirm")
    return trip_id


def _raw_candidate(name, country_code="ES"):
    return {
        "destination_name": name,
        "country_code": country_code,
        "reason_to_check": "fits the brief",
        "matched_preferences": [],
        "potential_conflicts": [],
        "source": "llm",
        "candidate_category": "core",
    }


def test_generate_candidates_requires_confirmed_brief(client):
    _use_llm(FakeLLMProvider(TripBrief()))
    trip_id = client.post("/api/trips").json()["id"]
    client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "hi"})  # not confirmed

    r = client.post(f"/api/trips/{trip_id}/candidates")
    assert r.status_code == 400


def test_get_candidates_before_any_run_is_404(client):
    trip_id = _confirmed_trip(client)
    r = client.get(f"/api/trips/{trip_id}/candidates")
    assert r.status_code == 404


def test_generate_candidates_success_flow(client):
    trip_id = _confirmed_trip(client)
    _use_candidate_provider(FakeCandidateProvider([_raw_candidate("Tenerife")]))

    r = client.post(f"/api/trips/{trip_id}/candidates")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["candidate_count"] == 1
    assert body["candidates"][0]["destination_name"] == "Tenerife"
    assert body["candidates"][0]["id"] == "cand_1"
    assert body["version"] == 1

    r = client.get(f"/api/trips/{trip_id}/candidates")
    assert r.status_code == 200
    assert r.json()["candidate_count"] == 1


def test_second_generation_creates_new_version(client):
    trip_id = _confirmed_trip(client)
    _use_candidate_provider(FakeCandidateProvider([_raw_candidate("Tenerife")]))
    r1 = client.post(f"/api/trips/{trip_id}/candidates")
    assert r1.json()["version"] == 1

    _use_candidate_provider(FakeCandidateProvider([_raw_candidate("Zanzibar", "TZ"), _raw_candidate("Maldives", "MV")]))
    r2 = client.post(f"/api/trips/{trip_id}/candidates")
    assert r2.json()["version"] == 2
    assert r2.json()["candidate_count"] == 2

    r = client.get(f"/api/trips/{trip_id}/candidates")
    assert r.json()["version"] == 2  # GET returns the latest run


def test_failed_generation_does_not_corrupt_previous_run(client):
    trip_id = _confirmed_trip(client)
    _use_candidate_provider(FakeCandidateProvider([_raw_candidate("Tenerife")]))
    client.post(f"/api/trips/{trip_id}/candidates")

    class BrokenProvider:
        def generate(self, brief, raw_request=None):
            raise LLMParseError("boom")

    _use_candidate_provider(BrokenProvider())
    r = client.post(f"/api/trips/{trip_id}/candidates")
    assert r.status_code == 502

    db = SessionLocal()
    try:
        runs = db.query(CandidateRun).filter_by(trip_id=trip_id).order_by(CandidateRun.version).all()
        assert len(runs) == 2
        assert runs[0].status == "completed"
        assert runs[0].candidate_count == 1  # untouched by the later failure
        assert runs[1].status == "failed"
        assert runs[1].error is not None
    finally:
        db.close()


def test_malformed_llm_output_marks_run_failed_not_500(client):
    trip_id = _confirmed_trip(client)

    class MalformedProvider:
        def generate(self, brief, raw_request=None):
            return "not a list", {}  # violates the (list[dict], dict) contract

    _use_candidate_provider(MalformedProvider())
    r = client.post(f"/api/trips/{trip_id}/candidates")
    assert r.status_code == 502

    db = SessionLocal()
    try:
        run = db.query(CandidateRun).filter_by(trip_id=trip_id).one()
        assert run.status == "failed"
    finally:
        db.close()
