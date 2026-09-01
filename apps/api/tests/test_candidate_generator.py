from app.llm.fake_candidate_provider import FakeCandidateProvider
from app.research.candidate_generator import generate_candidates
from app.schemas import Preferences, TripBrief


def _cand(name, category="core", source="llm", country_code=None, reason="fits the brief"):
    return {
        "destination_name": name,
        "country_code": country_code,
        "reason_to_check": reason,
        "matched_preferences": [],
        "potential_conflicts": [],
        "source": source,
        "candidate_category": category,
    }


def _brief(avoid=None):
    return TripBrief(preferences=Preferences(avoid=avoid or [], prefer=[]))


def test_valid_candidates_pass_through():
    raw = [_cand("Tenerife", country_code="ES"), _cand("Zanzibar", country_code="TZ", category="alternative")]
    result = generate_candidates(_brief(), None, FakeCandidateProvider(raw))
    assert len(result.candidates) == 2
    assert {c.destination_name for c in result.candidates} == {"Tenerife", "Zanzibar"}


def test_missing_destination_name_dropped_with_warning():
    raw = [_cand("Tenerife"), {"reason_to_check": "no name", "source": "llm", "candidate_category": "core"}]
    result = generate_candidates(_brief(), None, FakeCandidateProvider(raw))
    assert len(result.candidates) == 1
    assert any("destination_name" in w for w in result.warnings)


def test_invalid_country_code_cleared_not_dropped():
    raw = [_cand("Somewhere Nice", country_code="Turkey")]  # not a 2-letter code
    result = generate_candidates(_brief(), None, FakeCandidateProvider(raw))
    assert len(result.candidates) == 1
    assert result.candidates[0].country_code is None
    assert any("invalid country code" in w for w in result.warnings)


def test_avoid_list_removes_country_by_name_in_russian():
    raw = [
        _cand("Hurghada", country_code="EG"),
        _cand("Antalya", country_code="TR"),
        _cand("Tenerife", country_code="ES"),
    ]
    result = generate_candidates(_brief(avoid=["Египет", "Турцию"]), None, FakeCandidateProvider(raw))
    names = {c.destination_name for c in result.candidates}
    assert names == {"Tenerife"}
    assert "EG" not in [c.country_code for c in result.candidates]
    assert "TR" not in [c.country_code for c in result.candidates]


def test_avoid_list_never_lets_avoided_country_back_in_via_user_pick():
    raw = [_cand("Cairo", country_code="EG", source="user")]
    result = generate_candidates(_brief(avoid=["Egypt"]), None, FakeCandidateProvider(raw))
    assert result.candidates == []


def test_user_pick_survives_pool_capping():
    core_names = [
        "Tenerife", "Antalya", "Malta", "Crete", "Sardinia", "Corfu", "Rhodes",
        "Ibiza", "Mallorca", "Sicily", "Zakynthos", "Algarve", "Costa del Sol",
        "Naxos", "Santorini", "Cyprus", "Menorca", "Kos", "Lanzarote", "Fuerteventura",
    ]
    raw = [_cand(name, category="core") for name in core_names]
    raw.append(_cand("Explicitly Requested Place", source="user", category="core"))
    result = generate_candidates(_brief(), None, FakeCandidateProvider(raw), max_total=10, max_core=9)
    assert any(c.destination_name == "Explicitly Requested Place" and c.source == "user" for c in result.candidates)


def test_dedup_merges_near_duplicate_destinations():
    raw = [
        _cand("Phuket", country_code="TH", category="core"),
        _cand("Phuket Thailand", country_code="TH", category="alternative"),
        _cand("Thailand Phuket", country_code="TH", category="core"),
    ]
    result = generate_candidates(_brief(), None, FakeCandidateProvider(raw))
    assert len(result.candidates) == 1
    assert result.candidates[0].candidate_category == "core"  # strongest category survives the merge


def test_dedup_keeps_distinct_destinations_in_same_country():
    raw = [_cand("Antalya", country_code="TR"), _cand("Istanbul", country_code="TR")]
    result = generate_candidates(_brief(), None, FakeCandidateProvider(raw))
    assert len(result.candidates) == 2


def test_cap_pool_respects_category_limits():
    core_names = ["Tenerife", "Antalya", "Malta", "Crete", "Sardinia"]
    wildcard_names = ["Oman", "Jordan", "Fiji", "Bhutan", "Iceland"]
    raw = [_cand(name, category="core") for name in core_names]
    raw += [_cand(name, category="wildcard") for name in wildcard_names]
    result = generate_candidates(_brief(), None, FakeCandidateProvider(raw), max_wildcard=2, max_total=50)
    wildcards = [c for c in result.candidates if c.candidate_category == "wildcard"]
    assert len(wildcards) == 2
    assert any("wildcard category limit" in w for w in result.warnings)


def test_empty_llm_output_produces_empty_result_not_a_crash():
    result = generate_candidates(_brief(), None, FakeCandidateProvider([]))
    assert result.candidates == []
    assert any("no candidates survived" in w for w in result.warnings)


def test_ids_assigned_sequentially_by_backend():
    raw = [_cand("A"), _cand("B"), _cand("C")]
    result = generate_candidates(_brief(), None, FakeCandidateProvider(raw))
    assert [c.id for c in result.candidates] == ["cand_1", "cand_2", "cand_3"]
