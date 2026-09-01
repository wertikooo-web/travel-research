from app.llm.fake_provider import FakeLLMProvider
from app.llm.provider import LLMParseError
from app.main import app
from app.routers.trips import get_llm_provider
from app.schemas import Traveller, TripBrief


def _use_llm(provider):
    app.dependency_overrides[get_llm_provider] = lambda: provider


def teardown_function(_fn):
    app.dependency_overrides.clear()


def test_create_trip(client):
    r = client.post("/api/trips")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "draft"
    assert body["id"]


def test_full_parse_edit_confirm_flow(client):
    canned = TripBrief(
        travellers=[
            Traveller(type="adult", citizenships=["MD"], travel_passport="MD", passport_type="biometric"),
            Traveller(type="adult", citizenships=["RO"], travel_passport="RO"),
        ]
    )
    _use_llm(FakeLLMProvider(canned))

    trip_id = client.post("/api/trips").json()["id"]

    r = client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "мы вдвоём, у меня MD паспорт, у неё RO"})
    assert r.status_code == 200
    body = r.json()
    travellers = body["structured_brief"]["travellers"]
    assert len(travellers) == 2
    assert travellers[0]["id"] == "traveller_1"
    assert travellers[1]["id"] == "traveller_2"
    assert {t["travel_passport"] for t in travellers} == {"MD", "RO"}
    assert body["confirmed_at"] is None

    edited = body["structured_brief"]
    edited["budget"] = {"currency": "EUR", "max_total": 3500, "hard_constraint": True}
    r = client.put(f"/api/trips/{trip_id}/brief", json=edited)
    assert r.status_code == 200
    assert r.json()["structured_brief"]["budget"]["max_total"] == 3500

    r = client.post(f"/api/trips/{trip_id}/confirm")
    assert r.status_code == 200
    assert r.json()["confirmed_at"] is not None

    r = client.get(f"/api/trips/{trip_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"


def test_parse_missing_trip_returns_404(client):
    r = client.post("/api/trips/does-not-exist/parse", json={"raw_text": "hi"})
    assert r.status_code == 404


def test_confirm_without_brief_fails(client):
    trip_id = client.post("/api/trips").json()["id"]
    r = client.post(f"/api/trips/{trip_id}/confirm")
    assert r.status_code == 400


def test_confirm_twice_fails(client):
    _use_llm(FakeLLMProvider(TripBrief()))
    trip_id = client.post("/api/trips").json()["id"]
    client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "hi"})
    r1 = client.post(f"/api/trips/{trip_id}/confirm")
    assert r1.status_code == 200
    r2 = client.post(f"/api/trips/{trip_id}/confirm")
    assert r2.status_code == 400


def test_edit_after_confirm_fails(client):
    _use_llm(FakeLLMProvider(TripBrief()))
    trip_id = client.post("/api/trips").json()["id"]
    client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "hi"})
    client.post(f"/api/trips/{trip_id}/confirm")
    r = client.put(f"/api/trips/{trip_id}/brief", json=TripBrief().model_dump(mode="json"))
    assert r.status_code == 400


def test_llm_failure_returns_502_not_500(client):
    class BrokenProvider:
        def parse_brief(self, raw_text, hints=None):
            raise LLMParseError("upstream boom")

    _use_llm(BrokenProvider())
    trip_id = client.post("/api/trips").json()["id"]
    r = client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "hi"})
    assert r.status_code == 502


def test_sparse_case_keeps_unknowns_null(client):
    canned = TripBrief(travellers=[Traveller(type="adult")])
    _use_llm(FakeLLMProvider(canned))
    trip_id = client.post("/api/trips").json()["id"]

    r = client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "хочу в Азию на две недели в феврале"})
    brief = r.json()["structured_brief"]
    assert brief["budget"] is None
    assert brief["hotel"] is None
    assert brief["travellers"][0]["travel_passport"] is None


def test_traveller_ids_stable_and_unique_after_remove_and_add(client):
    canned = TripBrief(
        travellers=[
            Traveller(type="adult", citizenships=["MD"], travel_passport="MD"),
            Traveller(type="adult", citizenships=["RO"], travel_passport="RO"),
            Traveller(type="adult", citizenships=["US"], travel_passport="US"),
        ]
    )
    _use_llm(FakeLLMProvider(canned))
    trip_id = client.post("/api/trips").json()["id"]

    parsed = client.post(f"/api/trips/{trip_id}/parse", json={"raw_text": "3 travellers"}).json()
    travellers = parsed["structured_brief"]["travellers"]
    assert [t["id"] for t in travellers] == ["traveller_1", "traveller_2", "traveller_3"]

    # remove traveller_2, add a brand new traveller the way the frontend does: no id at all
    remaining = [t for t in travellers if t["id"] != "traveller_2"]
    remaining.append({"type": "adult", "citizenships": ["FR"], "travel_passport": "FR"})

    edited_brief = parsed["structured_brief"]
    edited_brief["travellers"] = remaining
    r = client.put(f"/api/trips/{trip_id}/brief", json=edited_brief)
    assert r.status_code == 200

    saved = r.json()["structured_brief"]["travellers"]
    saved_ids = [t["id"] for t in saved]

    assert len(saved_ids) == len(set(saved_ids)), "traveller ids must be unique"
    assert "traveller_1" in saved_ids, "untouched traveller must keep its id"
    assert "traveller_3" in saved_ids, "untouched traveller must keep its id"
    assert "traveller_2" not in saved_ids, "removed traveller's id must not reappear"

    new_ids = set(saved_ids) - {"traveller_1", "traveller_3"}
    assert len(new_ids) == 1
    (new_id,) = new_ids
    assert new_id not in {"traveller_1", "traveller_2", "traveller_3"}, "new traveller must not reuse a freed id"

    fr_traveller = next(t for t in saved if t["travel_passport"] == "FR")
    assert fr_traveller["id"] == new_id
