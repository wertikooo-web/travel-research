"""Visa/entry research — Wikipedia's "Visa requirements for X citizens" tables.

Honesty about source tier: this is NOT an official government source. There is
no free, structured, government-grade visa API available for V0 (a real
per-country embassy integration is out of scope entirely). Wikipedia's tables
are widely relied upon, well maintained, and — critically — actually
fetchable with a real URL and timestamp. Every VisaResult from this module is
tagged source_type="secondary_travel_site" at "medium" confidence, never
upgraded to look like an authoritative source it isn't.

Retrieval and classification are deliberately separate steps (section 17):
1. fetch_visa_page(): one HTTP call, no interpretation.
2. extract_country_row(): deterministic wikitext parsing — finds the row for
   the destination country. No LLM.
3. classify_requirement_methods(): deterministic regex classification of the
   row's requirement text into every distinct entry method it states (a
   source can offer more than one, e.g. "visa on arrival/eVisa" — both are
   kept, never collapsed to whichever keyword happens to match first).
   Falls back to a bounded LLM extraction (the row text only, forced
   structured output) only when nothing is recognized — never asks the
   model what it "knows" from memory.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional, Protocol, Tuple

import httpx

from ..schemas import EntryMethod, EntryMethodType, Evidence, FactResult, VisaResult
from .country_names import country_name, demonym

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

_REF_RE = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", re.DOTALL | re.IGNORECASE)
_FLAG_RE = re.compile(r"\{\{\s*flag(?:country)?\s*\|\s*([^}|]+)", re.IGNORECASE)
_REQ_RE = re.compile(r"\{\{\s*(yes2?|no)\s*\|\s*([^}|<]+)", re.IGNORECASE)


class VisaSourceError(Exception):
    """Retrieval failed — never fall back to model memory when this happens."""


class RowNotFoundError(Exception):
    """The destination doesn't appear in the fetched table."""


class VisaExtractionProvider(Protocol):
    def classify(self, requirement_text: str, allowed_stay_text: str, notes: str) -> List[EntryMethodType]: ...


async def fetch_visa_page(passport_country: str, client: httpx.AsyncClient) -> Tuple[str, str]:
    """Returns (wikitext, page_url). Raises VisaSourceError on any failure —
    including simply not knowing how to name this passport country's page,
    which is a real, explicit limitation, not a silent guess."""
    demo = demonym(passport_country)
    if demo is None:
        raise VisaSourceError(f"no Wikipedia visa-page mapping configured for passport country {passport_country!r}")

    title = f"Visa requirements for {demo} citizens"
    try:
        resp = await client.get(
            WIKIPEDIA_API,
            params={"action": "parse", "page": title, "prop": "wikitext", "format": "json", "formatversion": "2"},
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        raise VisaSourceError(f"failed to fetch {title!r}: {e}") from e

    if "error" in data:
        raise VisaSourceError(f"Wikipedia has no page {title!r}: {data['error'].get('info')}")

    wikitext = data.get("parse", {}).get("wikitext")
    if not wikitext:
        raise VisaSourceError(f"{title!r} returned no wikitext")

    page_url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
    return wikitext, page_url


def _clean_wikitext(text: str) -> str:
    """Strip refs/templates/links down to their readable text. Not a full
    wikitext parser — good enough to turn a table cell into plain text."""
    text = _REF_RE.sub("", text)
    text = re.sub(r"\{\{[^{}]*\|([^{}|]*)\}\}", r"\1", text)  # {{Template|label}} -> label
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)  # bare {{Template}} with nothing useful -> drop
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)  # [[link|label]] / [[link]] -> label
    return text.strip()


def extract_country_row(wikitext: str, destination_country: str) -> dict:
    """Deterministic wikitext parsing — no LLM. Raises RowNotFoundError if the
    destination isn't in the table (never silently returns nothing useful)."""
    target_name = country_name(destination_country)
    if target_name is None:
        raise RowNotFoundError(f"no English country name known for {destination_country!r}")

    section_match = re.search(r"==\s*Visa requirements\s*==(.*?)(?:\n==[^=]|\Z)", wikitext, re.DOTALL)
    section = section_match.group(1) if section_match else wikitext

    for row in section.split("|-"):
        flag_match = _FLAG_RE.search(row)
        if not flag_match or flag_match.group(1).strip().lower() != target_name.lower():
            continue

        cells = re.findall(r"^\|\s?(.*)$", row, re.MULTILINE)

        # Most rows wrap the requirement in {{yes|...}}/{{yes2|...}}/{{no|...}} —
        # but not all (some are plain text, e.g. "Visa on arrival/eVisa"). Fall
        # back to the raw second cell rather than silently extracting nothing.
        # Scoped to cells[1] specifically — searching the whole row risked
        # matching an unrelated {{no|...}} template from the notes column.
        req_match = _REQ_RE.search(cells[1]) if len(cells) >= 2 else None
        if req_match:
            requirement_text = req_match.group(2).strip()
        elif len(cells) >= 2:
            requirement_text = _clean_wikitext(cells[1])
        else:
            requirement_text = ""

        allowed_stay_text = _clean_wikitext(cells[2]) if len(cells) >= 3 else ""
        notes = _clean_wikitext("\n".join(cells[3:])) if len(cells) >= 4 else ""

        return {
            "requirement_text": requirement_text,
            "allowed_stay_text": allowed_stay_text,
            "notes": notes,
            "raw_row_text": row.strip()[:1500],
        }

    raise RowNotFoundError(f"{target_name!r} not found in the visa-requirements table")


# Regex, not substring checks: a source line like "Visa not required" must
# match visa_free ONLY, never also visa_required just because "required" is
# a substring of "not required". Every entry gets checked — a composite
# statement like "Visa on arrival/eVisa" is meant to match more than one
# rule; normalization must preserve that, not collapse it to the first hit.
_METHOD_PATTERNS: List[Tuple["re.Pattern[str]", EntryMethodType]] = [
    (re.compile(r"\bnot required\b"), "visa_free"),
    (re.compile(r"\bfreedom of movement\b"), "visa_free"),
    (re.compile(r"\bnot permitted\b"), "entry_restricted"),
    (re.compile(r"\bno admittance\b"), "entry_restricted"),
    (re.compile(r"\bbanned\b"), "entry_restricted"),
    (re.compile(r"\be-?visa\b"), "evisa"),
    (re.compile(r"\belectronic travel authoriz\w*\b"), "electronic_authorization"),
    (re.compile(r"\beta\b"), "electronic_authorization"),
    (re.compile(r"\bvisa on arrival\b"), "visa_on_arrival"),
    (re.compile(r"\bon arrival\b"), "visa_on_arrival"),
    (re.compile(r"(?<!not )\brequired\b"), "visa_required"),
]


def classify_requirement_methods(requirement_text: str) -> List[EntryMethodType]:
    """Every distinct entry method the source text actually states, in the
    order its patterns are defined, deduplicated. Empty if nothing
    recognized — the caller decides what to do next (LLM fallback, then
    'unknown'), this function never guesses."""
    text = requirement_text.lower()
    methods: List[EntryMethodType] = []
    for pattern, method in _METHOD_PATTERNS:
        if pattern.search(text) and method not in methods:
            methods.append(method)
    return methods


def _parse_allowed_stay_days(text: str) -> Optional[int]:
    match = re.search(r"(\d+)\s*day", text.lower())
    return int(match.group(1)) if match else None


async def research_visa(
    traveller_id: str,
    passport_country: str,
    destination_country: Optional[str],
    client: httpx.AsyncClient,
    extraction_provider: Optional[VisaExtractionProvider] = None,
) -> VisaResult:
    if destination_country is None:
        return VisaResult(
            traveller_id=traveller_id,
            passport_country=passport_country,
            destination_country=None,
            entry_methods=FactResult(status="unknown", note="destination country not resolved — cannot look up entry rules"),
        )

    retrieved_at = datetime.now(timezone.utc).isoformat()

    try:
        wikitext, page_url = await fetch_visa_page(passport_country, client)
        row = extract_country_row(wikitext, destination_country)
    except VisaSourceError as e:
        return VisaResult(
            traveller_id=traveller_id,
            passport_country=passport_country,
            destination_country=destination_country,
            entry_methods=FactResult(status="unavailable", note=str(e)),
        )
    except RowNotFoundError as e:
        return VisaResult(
            traveller_id=traveller_id,
            passport_country=passport_country,
            destination_country=destination_country,
            entry_methods=FactResult(status="unknown", note=str(e)),
        )

    evidence = Evidence(
        source_type="secondary_travel_site",
        provider="Wikipedia",
        url=page_url,
        retrieved_at=retrieved_at,
        title=f"Visa requirements for {demonym(passport_country)} citizens",
        raw_excerpt=row["raw_row_text"],
        confidence="medium",
    )

    methods = classify_requirement_methods(row["requirement_text"])
    if not methods and extraction_provider is not None:
        try:
            methods = extraction_provider.classify(row["requirement_text"], row["allowed_stay_text"], row["notes"])
        except Exception:
            methods = []

    if not methods:
        return VisaResult(
            traveller_id=traveller_id,
            passport_country=passport_country,
            destination_country=destination_country,
            entry_methods=FactResult(
                status="unknown",
                evidence=[evidence],
                note=f"could not classify requirement text: {row['requirement_text']!r}",
            ),
            conditions=[row["notes"]] if row["notes"] else [],
        )

    # the source states one allowed-stay figure for the whole row, not one
    # per method — applied to every method parsed from it, not split up
    allowed_stay = _parse_allowed_stay_days(row["allowed_stay_text"])
    entry_method_objs = [EntryMethod(method=m, allowed_stay_days=allowed_stay) for m in methods]

    return VisaResult(
        traveller_id=traveller_id,
        passport_country=passport_country,
        destination_country=destination_country,
        entry_methods=FactResult(status="known", value=entry_method_objs, evidence=[evidence]),
        conditions=[row["notes"]] if row["notes"] else [],
    )
