"""Live tests against the real Claude API for the 4 required Milestone 1 cases.

Skipped automatically when ANTHROPIC_API_KEY isn't set. Run with:
    pytest tests/test_llm_integration.py -v
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live LLM integration tests",
)


@pytest.fixture(scope="module")
def provider():
    from app.llm.anthropic_provider import AnthropicProvider

    return AnthropicProvider()


def test_case1_mixed_md_ro_passports(provider):
    text = (
        "Мы вдвоём из Кишинёва в конце октября. У меня молдавский биометрический "
        "паспорт, у девушки румынский. Хотим на море на 8–10 дней, до €3500, "
        "минимум 4★, желательно прямой рейс."
    )
    brief = provider.parse_brief(text)

    assert len(brief.travellers) == 2
    passports = {t.travel_passport for t in brief.travellers}
    assert passports == {"MD", "RO"}

    md_traveller = next(t for t in brief.travellers if t.travel_passport == "MD")
    assert md_traveller.passport_type == "biometric"

    assert brief.budget is not None
    assert brief.budget.max_total == 3500
    assert brief.budget.currency == "EUR"

    assert brief.hotel is not None
    assert brief.hotel.stars_min == 4

    assert brief.flight is not None
    assert brief.flight.direct_preferred is True

    assert brief.nights is not None
    assert brief.nights.min == 8
    assert brief.nights.max == 10


def test_case2_family_with_child(provider):
    text = (
        "Хочу с женой и ребёнком 8 лет куда-нибудь тепло в ноябре. Вылет из "
        "Бухареста. У всех румынские паспорта. До €4000."
    )
    brief = provider.parse_brief(text)

    assert len(brief.travellers) == 3
    child = next(t for t in brief.travellers if t.type == "child")
    assert child.age == 8
    assert all(t.travel_passport == "RO" for t in brief.travellers)

    assert brief.budget is not None
    assert brief.budget.max_total == 4000


def test_case3_sparse_request_does_not_invent(provider):
    text = "Хочу в Азию примерно на две недели в феврале."
    brief = provider.parse_brief(text)

    assert brief.budget is None or brief.budget.max_total is None
    assert brief.hotel is None or brief.hotel.stars_min is None
    for t in brief.travellers:
        assert t.travel_passport is None
    assert brief.dates is None or brief.dates.start is None


def test_case4_one_traveller_two_passports(provider):
    text = "У меня молдавский и румынский паспорта."
    brief = provider.parse_brief(text)

    assert len(brief.travellers) == 1
    traveller = brief.travellers[0]
    assert set(traveller.citizenships or []) == {"MD", "RO"}
