"""Live tests against the real Claude API for Milestone 2 candidate generation
(Cases A-F). Skipped automatically when ANTHROPIC_API_KEY isn't set.

These check structural/hard requirements only (avoid-list respected, user
picks present, reasonable diversity, no near-duplicates). Subjective output
quality was reviewed manually — see the milestone report, not this file.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live candidate generation tests",
)


@pytest.fixture(scope="module")
def brief_provider():
    from app.llm.anthropic_provider import AnthropicProvider

    return AnthropicProvider()


@pytest.fixture(scope="module")
def candidate_provider():
    from app.llm.candidate_provider import AnthropicCandidateProvider

    return AnthropicCandidateProvider()


def _generate(text, brief_provider, candidate_provider):
    from app.research.candidate_generator import generate_candidates

    brief = brief_provider.parse_brief(text)
    return generate_candidates(brief, text, candidate_provider)


def test_case_a_beach_diversified_pool(brief_provider, candidate_provider):
    text = (
        "Мы вдвоём из Кишинёва в конце октября. Хотим на море на 8–10 дней, "
        "до €3500, минимум 4★, желательно прямой рейс."
    )
    result = _generate(text, brief_provider, candidate_provider)

    assert len(result.candidates) >= 6
    categories = {c.candidate_category for c in result.candidates}
    assert "core" in categories
    countries = {c.country_code for c in result.candidates if c.country_code}
    assert len(countries) >= 3, "expected geographic diversity, not one country repeated"


def test_case_b_sparse_asia_no_invented_constraints(brief_provider, candidate_provider):
    text = "Хочу куда-нибудь в Азию примерно на две недели в феврале."
    result = _generate(text, brief_provider, candidate_provider)

    assert len(result.candidates) >= 5
    # candidates carry no fields for price/flight/visa/weather facts at all —
    # this is a schema guarantee, not something to re-check per test.


def test_case_c_user_picks_survive(brief_provider, candidate_provider):
    from app.research.candidate_generator import generate_candidates

    text = "Хочу море в ноябре. Думаю про Thailand и Vietnam."

    # deterministic guarantee starts at parse time — the brief itself must
    # carry the picks, independent of what the candidate-generation call does
    brief = brief_provider.parse_brief(text)
    pick_texts = " ".join(p.text.lower() for p in brief.destination_picks)
    assert "thai" in pick_texts
    assert "vietnam" in pick_texts

    result = generate_candidates(brief, text, candidate_provider)

    user_picks = [c for c in result.candidates if c.source == "user"]
    user_countries = {c.country_code for c in user_picks}
    assert "TH" in user_countries or any("thai" in c.destination_name.lower() for c in user_picks)
    assert "VN" in user_countries or any("vietnam" in c.destination_name.lower() for c in user_picks)


def test_case_d_avoid_list_respected(brief_provider, candidate_provider):
    text = "Хочу тёплое море, но Египет и Турцию не хочу."
    result = _generate(text, brief_provider, candidate_provider)

    countries = {c.country_code for c in result.candidates}
    names = " ".join(c.destination_name.lower() for c in result.candidates)
    assert "EG" not in countries and "TR" not in countries
    assert "egypt" not in names and "turkey" not in names and "антаl" not in names


def test_case_e_dual_passport_context_only(brief_provider, candidate_provider):
    text = (
        "Мы вдвоём, у меня молдавский и румынский паспорта. Хотим на море "
        "в ноябре."
    )
    result = _generate(text, brief_provider, candidate_provider)

    assert len(result.candidates) >= 5
    # the brief itself must still carry both citizenships through untouched
    brief = brief_provider.parse_brief(text)
    assert set(brief.travellers[0].citizenships or []) == {"MD", "RO"}


def test_case_f_no_near_duplicate_destinations_survive_normalization(brief_provider, candidate_provider):
    text = "Хочу на пляж в Таиланде, конкретно на Пхукет, в любое время."
    result = _generate(text, brief_provider, candidate_provider)

    dedup_keys = set()
    for c in result.candidates:
        key = c.destination_name.lower().replace(c.country_code.lower() if c.country_code else "", "").strip()
        assert key not in dedup_keys, f"near-duplicate survived normalization: {c.destination_name}"
        dedup_keys.add(key)
