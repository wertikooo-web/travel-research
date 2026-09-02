from app.llm.fake_candidate_provider import FakeCandidateProvider
from app.research.candidate_generator import generate_candidates
from app.schemas import DestinationPick, Preferences, TripBrief


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


def _brief(avoid=None, picks=None):
    return TripBrief(
        preferences=Preferences(avoid=avoid or [], prefer=[]),
        destination_picks=[DestinationPick(text=p) for p in (picks or [])],
    )


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


# --- explicit destination picks are a backend guarantee, not an LLM courtesy ---


def test_explicit_picks_survive_even_when_provider_omits_them_entirely():
    brief = _brief(picks=["Thailand", "Vietnam"])
    raw = [_cand("Malta", country_code="MT")]  # provider ignores both picks completely
    result = generate_candidates(brief, None, FakeCandidateProvider(raw))

    names = {c.destination_name for c in result.candidates}
    assert "Thailand" in names and "Vietnam" in names
    picks = {c.destination_name: c for c in result.candidates if c.destination_name in ("Thailand", "Vietnam")}
    assert all(c.source == "user" for c in picks.values())
    assert any("omitted it" in w for w in result.warnings)


def test_provider_sourced_llm_gets_promoted_to_user_for_a_pick():
    brief = _brief(picks=["Thailand"])
    raw = [_cand("Thailand", country_code="TH", source="llm", reason="looks like a decent beach option")]
    result = generate_candidates(brief, None, FakeCandidateProvider(raw))

    assert len(result.candidates) == 1
    thailand = result.candidates[0]
    assert thailand.source == "user"
    assert thailand.reason_to_check == "looks like a decent beach option"  # LLM's reasoning preserved, only source changes
    assert any("promoted" in w for w in result.warnings)


def test_pick_dedup_preserves_intent_without_swallowing_a_distinct_city():
    brief = _brief(picks=["Thailand"])
    raw = [
        _cand("Thailand", country_code="TH", source="llm"),  # same as the pick -> merges + promotes
        _cand("Phuket", country_code="TH", source="llm"),  # a different, more specific place -> stays separate
    ]
    result = generate_candidates(brief, None, FakeCandidateProvider(raw))

    by_name = {c.destination_name: c for c in result.candidates}
    assert by_name["Thailand"].source == "user"
    assert "Phuket" in by_name
    assert by_name["Phuket"].source == "llm"


def test_user_picks_are_never_removed_even_beyond_max_total():
    brief = _brief(picks=["Thailand", "Vietnam", "Cambodia", "Laos"])
    result = generate_candidates(brief, None, FakeCandidateProvider([]), max_total=2)

    names = {c.destination_name for c in result.candidates}
    assert names == {"Thailand", "Vietnam", "Cambodia", "Laos"}
    assert len(result.candidates) == 4  # exceeds max_total=2 on purpose
    assert any("exceeding max_total" in w for w in result.warnings)


def test_pick_that_is_also_avoided_survives_with_a_conflict_warning():
    brief = _brief(avoid=["Thailand"], picks=["Thailand"])
    result = generate_candidates(brief, None, FakeCandidateProvider([]))

    assert any(c.destination_name == "Thailand" and c.source == "user" for c in result.candidates)
    assert any("conflict" in w and "Thailand" in w for w in result.warnings)


def test_old_brief_without_destination_picks_field_still_works():
    # simulates a Milestone 1 brief loaded from a saved JSON blob that predates this field
    old_brief_json = {"travellers": [], "preferences": {"avoid": [], "prefer": []}}
    brief = TripBrief.model_validate(old_brief_json)
    assert brief.destination_picks == []

    result = generate_candidates(brief, None, FakeCandidateProvider([_cand("Malta", country_code="MT")]))
    assert len(result.candidates) == 1
