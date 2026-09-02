import asyncio

import httpx
import pytest

from app.llm.visa_extraction_provider import FakeVisaExtractionProvider
from app.research.visa import (
    RowNotFoundError,
    VisaSourceError,
    classify_requirement_deterministic,
    extract_country_row,
    research_visa,
)

SAMPLE_WIKITEXT = """
{{Short description|Administrative entry restrictions}}
Some intro text.

==Visa requirements==
{| class="sortable wikitable"
|-
! Country
! Visa requirement
! Allowed stay
! Notes
|-
| {{flag|Thailand}}
| {{yes2|eVisa}}<ref>{{Timatic|nationality=MD|destination=TH}}</ref>
| 30 days
|
* some note about Thailand
|-
| {{flag|Romania}}
| {{yes|Visa not required}}<ref>{{Timatic|nationality=MD|destination=RO}}</ref>
| 90 days
|
|-
| {{flag|Egypt}}
| {{no|Visa required}}<ref>{{Timatic|nationality=MD|destination=EG}}</ref>
|
|
|-
| {{flag|Narnia}}
| {{yes|Something unusual and unclassifiable}}
|
|
|-
| {{flag|Bulgaria}}
| Visa on arrival/eVisa
| 30 days
|
|-
| {{flag|Jordan}}
| {{Optional|eVisa / Visa on arrival}}<ref>{{Timatic|nationality=RO|destination=JO}}</ref>
|
| {{no|X}}
|}

==See also==
Other section text.
"""


def test_extract_country_row_finds_thailand():
    row = extract_country_row(SAMPLE_WIKITEXT, "TH")
    assert row["requirement_text"] == "eVisa"
    assert row["allowed_stay_text"] == "30 days"
    assert "note about Thailand" in row["notes"]


def test_extract_country_row_strips_ref_tags():
    row = extract_country_row(SAMPLE_WIKITEXT, "RO")
    assert "<ref>" not in row["requirement_text"]
    assert "Timatic" not in row["requirement_text"]


def test_extract_country_row_falls_back_to_plain_text_when_no_yes_no_template():
    # observed live: some rows state the requirement as plain text
    # ("Visa on arrival/eVisa") instead of wrapping it in {{yes|...}}
    row = extract_country_row(SAMPLE_WIKITEXT, "BG")
    assert row["requirement_text"] == "Visa on arrival/eVisa"
    assert classify_requirement_deterministic(row["requirement_text"]) == "evisa"


def test_extract_country_row_does_not_match_a_template_from_a_different_cell():
    # observed live: a {{no|X}} template in the Notes column was wrongly
    # matched as the visa requirement when the requirement cell itself used
    # a template (`{{Optional|...}}`) the yes/yes2/no regex doesn't cover
    row = extract_country_row(SAMPLE_WIKITEXT, "JO")
    assert row["requirement_text"] == "eVisa / Visa on arrival"
    assert classify_requirement_deterministic(row["requirement_text"]) == "evisa"


def test_extract_country_row_not_found_raises():
    with pytest.raises(RowNotFoundError):
        extract_country_row(SAMPLE_WIKITEXT, "JP")  # Japan not in this sample table


def test_extract_country_row_unmapped_country_code_raises():
    with pytest.raises(RowNotFoundError):
        extract_country_row(SAMPLE_WIKITEXT, "XX")  # no English name known for this code


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Visa not required", "visa_free"),
        ("eVisa", "evisa"),
        ("Visa on arrival", "visa_on_arrival"),
        ("Electronic Travel Authorization required", "electronic_authorization"),
        ("Visa required", "visa_required"),
        ("Not permitted", "entry_restricted"),
    ],
)
def test_classify_requirement_deterministic_known_phrasings(text, expected):
    assert classify_requirement_deterministic(text) == expected


def test_classify_requirement_deterministic_unknown_phrasing_returns_none():
    assert classify_requirement_deterministic("Something unusual and unclassifiable") is None


def _mock_transport(wikitext=SAMPLE_WIKITEXT, http_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if http_status != 200:
            return httpx.Response(http_status, json={"error": {"info": "not found"}})
        return httpx.Response(200, json={"parse": {"wikitext": wikitext}})

    return httpx.MockTransport(handler)


def test_research_visa_known_status_with_evidence():
    async def run():
        async with httpx.AsyncClient(transport=_mock_transport()) as client:
            return await research_visa("t1", "MD", "TH", client)

    result = asyncio.run(run())
    assert result.status.status == "known"
    assert result.status.value == "evisa"
    assert result.allowed_stay_days.value == 30
    assert len(result.status.evidence) == 1
    assert result.status.evidence[0].source_type == "secondary_travel_site"
    assert result.status.evidence[0].confidence == "medium"


def test_research_visa_row_not_found_is_unknown_not_a_crash():
    async def run():
        async with httpx.AsyncClient(transport=_mock_transport()) as client:
            return await research_visa("t1", "MD", "JP", client)

    result = asyncio.run(run())
    assert result.status.status == "unknown"


def test_research_visa_source_unavailable_on_fetch_failure():
    async def run():
        async with httpx.AsyncClient(transport=_mock_transport(http_status=500)) as client:
            return await research_visa("t1", "MD", "TH", client)

    result = asyncio.run(run())
    assert result.status.status == "unavailable"


def test_research_visa_no_passport_mapping_is_unavailable_never_llm_memory():
    async def run():
        async with httpx.AsyncClient(transport=_mock_transport()) as client:
            return await research_visa("t1", "ZZ", "TH", client)  # no demonym configured

    result = asyncio.run(run())
    assert result.status.status == "unavailable"


def test_research_visa_no_destination_country_is_unknown():
    async def run():
        async with httpx.AsyncClient(transport=_mock_transport()) as client:
            return await research_visa("t1", "MD", None, client)

    result = asyncio.run(run())
    assert result.status.status == "unknown"


def test_llm_fallback_used_only_when_deterministic_classification_fails():
    fake_llm = FakeVisaExtractionProvider(result=("visa_free", 60))

    from app.research import country_names

    # Temporarily map an unused code to "Narnia" so research_visa can resolve destination_country -> name
    country_names.ISO2_TO_COUNTRY_NAME["ZZ"] = "Narnia"
    try:
        async def run():
            async with httpx.AsyncClient(transport=_mock_transport()) as client:
                return await research_visa("t1", "MD", "ZZ", client, extraction_provider=fake_llm)

        result = asyncio.run(run())
    finally:
        del country_names.ISO2_TO_COUNTRY_NAME["ZZ"]

    assert len(fake_llm.calls) == 1
    assert result.status.status == "known"
    assert result.status.value == "visa_free"
