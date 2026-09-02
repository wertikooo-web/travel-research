import asyncio

import httpx
import pytest

from app.llm.visa_extraction_provider import FakeVisaExtractionProvider
from app.research.visa import (
    RowNotFoundError,
    classify_requirement_methods,
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


def test_extract_country_row_does_not_match_a_template_from_a_different_cell():
    # observed live: a {{no|X}} template in the Notes column was wrongly
    # matched as the visa requirement when the requirement cell itself used
    # a template (`{{Optional|...}}`) the yes/yes2/no regex doesn't cover
    row = extract_country_row(SAMPLE_WIKITEXT, "JO")
    assert row["requirement_text"] == "eVisa / Visa on arrival"


def test_extract_country_row_not_found_raises():
    with pytest.raises(RowNotFoundError):
        extract_country_row(SAMPLE_WIKITEXT, "JP")  # Japan not in this sample table


def test_extract_country_row_unmapped_country_code_raises():
    with pytest.raises(RowNotFoundError):
        extract_country_row(SAMPLE_WIKITEXT, "XX")  # no English name known for this code


# --- composite entry methods: the core of this correctness pass -------------
# A source stating two valid options ("visa on arrival/eVisa") must produce
# both methods, in either phrasing order — not whichever keyword a scan
# happens to hit first, and not silently merged into one.


def test_classify_composite_visa_on_arrival_slash_evisa():
    methods = classify_requirement_methods("Visa on arrival/eVisa")
    assert set(methods) == {"visa_on_arrival", "evisa"}


def test_classify_composite_evisa_slash_visa_on_arrival_order_reversed():
    methods = classify_requirement_methods("eVisa / Visa on arrival")
    assert set(methods) == {"visa_on_arrival", "evisa"}


def test_classify_simple_visa_free():
    assert classify_requirement_methods("Visa not required") == ["visa_free"]


def test_classify_simple_visa_required():
    assert classify_requirement_methods("Visa required") == ["visa_required"]


def test_classify_visa_not_required_does_not_also_match_visa_required():
    # "required" is a substring of "not required" — a naive substring check
    # would wrongly add visa_required here too
    methods = classify_requirement_methods("Visa not required")
    assert "visa_required" not in methods


@pytest.mark.parametrize(
    "text,expected",
    [
        ("eVisa", ["evisa"]),
        ("Visa on arrival", ["visa_on_arrival"]),
        ("Electronic Travel Authorization required", ["electronic_authorization", "visa_required"]),
        ("Not permitted", ["entry_restricted"]),
    ],
)
def test_classify_requirement_methods_known_phrasings(text, expected):
    assert set(classify_requirement_methods(text)) == set(expected)


def test_classify_requirement_methods_unknown_phrasing_returns_empty_list():
    assert classify_requirement_methods("Something unusual and unclassifiable") == []


def _mock_transport(wikitext=SAMPLE_WIKITEXT, http_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if http_status != 200:
            return httpx.Response(http_status, json={"error": {"info": "not found"}})
        return httpx.Response(200, json={"parse": {"wikitext": wikitext}})

    return httpx.MockTransport(handler)


def test_research_visa_single_method_known_with_evidence():
    async def run():
        async with httpx.AsyncClient(transport=_mock_transport()) as client:
            return await research_visa("t1", "MD", "TH", client)

    result = asyncio.run(run())
    assert result.entry_methods.status == "known"
    assert [m.method for m in result.entry_methods.value] == ["evisa"]
    assert result.entry_methods.value[0].allowed_stay_days == 30
    assert len(result.entry_methods.evidence) == 1
    assert result.entry_methods.evidence[0].source_type == "secondary_travel_site"
    assert result.entry_methods.evidence[0].confidence == "medium"


def test_research_visa_composite_methods_both_preserved():
    async def run():
        async with httpx.AsyncClient(transport=_mock_transport()) as client:
            return await research_visa("t1", "MD", "BG", client)

    result = asyncio.run(run())
    assert result.entry_methods.status == "known"
    methods = {m.method for m in result.entry_methods.value}
    assert methods == {"visa_on_arrival", "evisa"}
    # both real, materially distinct options — not collapsed to one
    assert len(result.entry_methods.value) == 2


def test_research_visa_row_not_found_is_unknown_not_a_crash():
    async def run():
        async with httpx.AsyncClient(transport=_mock_transport()) as client:
            return await research_visa("t1", "MD", "JP", client)

    result = asyncio.run(run())
    assert result.entry_methods.status == "unknown"


def test_research_visa_source_unavailable_on_fetch_failure():
    async def run():
        async with httpx.AsyncClient(transport=_mock_transport(http_status=500)) as client:
            return await research_visa("t1", "MD", "TH", client)

    result = asyncio.run(run())
    assert result.entry_methods.status == "unavailable"


def test_research_visa_no_passport_mapping_is_unavailable_never_llm_memory():
    async def run():
        async with httpx.AsyncClient(transport=_mock_transport()) as client:
            return await research_visa("t1", "ZZ", "TH", client)  # no demonym configured

    result = asyncio.run(run())
    assert result.entry_methods.status == "unavailable"


def test_research_visa_no_destination_country_is_unknown():
    async def run():
        async with httpx.AsyncClient(transport=_mock_transport()) as client:
            return await research_visa("t1", "MD", None, client)

    result = asyncio.run(run())
    assert result.entry_methods.status == "unknown"


def test_llm_fallback_used_only_when_deterministic_classification_fails():
    fake_llm = FakeVisaExtractionProvider(result=["visa_free"])

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
    assert result.entry_methods.status == "known"
    assert [m.method for m in result.entry_methods.value] == ["visa_free"]
