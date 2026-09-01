from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol

from pydantic import ValidationError

from ..llm.provider import LLMParseError
from ..schemas import Candidate, TripBrief
from .country_names import resolve_country_code

DEFAULT_MAX_TOTAL = 18
DEFAULT_MAX_CORE = 12
DEFAULT_MAX_ALTERNATIVE = 6
DEFAULT_MAX_WILDCARD = 3

_DEDUP_SIMILARITY_THRESHOLD = 0.6
_CATEGORY_RANK = {"core": 0, "alternative": 1, "wildcard": 2}  # lower survives a merge


class CandidateProvider(Protocol):
    def generate(self, brief: TripBrief, raw_request: Optional[str] = None) -> tuple[list[dict], dict]: ...


@dataclass
class CandidateGenerationResult:
    candidates: List[Candidate]
    raw_llm_output: dict
    warnings: List[str] = field(default_factory=list)


def generate_candidates(
    brief: TripBrief,
    raw_request: Optional[str],
    provider: CandidateProvider,
    *,
    max_total: int = DEFAULT_MAX_TOTAL,
    max_core: int = DEFAULT_MAX_CORE,
    max_alternative: int = DEFAULT_MAX_ALTERNATIVE,
    max_wildcard: int = DEFAULT_MAX_WILDCARD,
) -> CandidateGenerationResult:
    """Confirmed brief -> normalized candidate pool.

    The LLM call (provider.generate) is untrusted input: everything after it
    is deterministic code, not a second model call. Order matters: validate
    structure first, then enforce the avoid-list (a hard constraint) before
    deduplication, then cap pool size last so a duplicate or avoided entry
    never eats a slot a real candidate should have had.
    """
    raw_candidates, raw_llm_output = provider.generate(brief, raw_request)
    if not isinstance(raw_candidates, list):
        raise LLMParseError("candidate provider returned a non-list candidates payload")

    warnings: List[str] = []
    validated = _validate(raw_candidates, warnings)
    filtered = _apply_avoid_filter(validated, brief, warnings)
    deduped = _deduplicate(filtered, warnings)
    capped = _cap_pool(deduped, max_total, max_core, max_alternative, max_wildcard, warnings)
    _assign_ids(capped)

    if not capped:
        warnings.append("no candidates survived generation + normalization")

    return CandidateGenerationResult(candidates=capped, raw_llm_output=raw_llm_output, warnings=warnings)


def _validate(raw_candidates: list[Any], warnings: List[str]) -> List[Candidate]:
    out: List[Candidate] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict) or not str(raw.get("destination_name", "")).strip():
            warnings.append(f"dropped a candidate with no destination_name: {raw!r}")
            continue
        try:
            candidate = Candidate.model_validate(raw)
        except ValidationError as e:
            warnings.append(f"dropped invalid candidate {raw.get('destination_name')!r}: {e}")
            continue

        if candidate.country_code and not (len(candidate.country_code) == 2 and candidate.country_code.isalpha()):
            warnings.append(f"{candidate.destination_name}: invalid country code {candidate.country_code!r}, cleared")
            candidate.country_code = None

        out.append(candidate)
    return out


def _avoid_codes_and_terms(brief: TripBrief) -> tuple[set[str], list[str]]:
    if not brief.preferences or not brief.preferences.avoid:
        return set(), []
    terms = [t.strip().lower() for t in brief.preferences.avoid if t and t.strip()]
    codes = {code for term in terms if (code := resolve_country_code(term))}
    return codes, terms


def _matches_avoid(candidate: Candidate, avoid_codes: set[str], avoid_terms: list[str]) -> bool:
    if candidate.country_code and candidate.country_code in avoid_codes:
        return True
    name = candidate.destination_name.lower()
    return any(term in name or name in term for term in avoid_terms if len(term) > 2)


def _apply_avoid_filter(candidates: List[Candidate], brief: TripBrief, warnings: List[str]) -> List[Candidate]:
    avoid_codes, avoid_terms = _avoid_codes_and_terms(brief)
    if not avoid_codes and not avoid_terms:
        return candidates

    kept = []
    for c in candidates:
        if _matches_avoid(c, avoid_codes, avoid_terms):
            warnings.append(f"removed {c.destination_name!r} — matches the traveller's avoid list")
            continue
        kept.append(c)
    return kept


def _dedup_key(candidate: Candidate) -> str:
    name = candidate.destination_name.lower()
    if candidate.country_code:
        name = name.replace(candidate.country_code.lower(), "")
    return "".join(ch for ch in name if ch.isalnum() or ch.isspace()).strip()


def _is_near_duplicate(a: Candidate, b: Candidate) -> bool:
    if a.country_code and b.country_code and a.country_code != b.country_code:
        return False
    key_a, key_b = _dedup_key(a), _dedup_key(b)
    if key_a == key_b:
        return True
    if key_a in key_b or key_b in key_a:
        return True
    return difflib.SequenceMatcher(None, key_a, key_b).ratio() >= _DEDUP_SIMILARITY_THRESHOLD


def _merge_duplicate(kept: Candidate, incoming: Candidate) -> Candidate:
    # user picks are sacred; a stronger category (core > alternative > wildcard) wins;
    # keep the richer reasoning text either way.
    winner = incoming if incoming.source == "user" and kept.source != "user" else kept
    if _CATEGORY_RANK[incoming.candidate_category] < _CATEGORY_RANK[winner.candidate_category]:
        winner = winner.model_copy(update={"candidate_category": incoming.candidate_category})
    if incoming.source == "user":
        winner = winner.model_copy(update={"source": "user"})
    if len(incoming.reason_to_check) > len(winner.reason_to_check):
        winner = winner.model_copy(update={"reason_to_check": incoming.reason_to_check})
    merged_prefs = list(dict.fromkeys([*winner.matched_preferences, *incoming.matched_preferences]))
    merged_conflicts = list(dict.fromkeys([*winner.potential_conflicts, *incoming.potential_conflicts]))
    return winner.model_copy(update={"matched_preferences": merged_prefs, "potential_conflicts": merged_conflicts})


def _deduplicate(candidates: List[Candidate], warnings: List[str]) -> List[Candidate]:
    result: List[Candidate] = []
    for candidate in candidates:
        merged = False
        for i, existing in enumerate(result):
            if _is_near_duplicate(existing, candidate):
                warnings.append(f"merged near-duplicate {candidate.destination_name!r} into {existing.destination_name!r}")
                result[i] = _merge_duplicate(existing, candidate)
                merged = True
                break
        if not merged:
            result.append(candidate)
    return result


def _cap_pool(
    candidates: List[Candidate],
    max_total: int,
    max_core: int,
    max_alternative: int,
    max_wildcard: int,
    warnings: List[str],
) -> List[Candidate]:
    # user picks always survive capping, regardless of category limits
    user_picks = [c for c in candidates if c.source == "user"]
    rest = [c for c in candidates if c.source != "user"]

    limits = {"core": max_core, "alternative": max_alternative, "wildcard": max_wildcard}
    counts = {"core": 0, "alternative": 0, "wildcard": 0}
    kept_rest: List[Candidate] = []
    for c in rest:
        if counts[c.candidate_category] < limits[c.candidate_category]:
            kept_rest.append(c)
            counts[c.candidate_category] += 1
        else:
            warnings.append(f"dropped {c.destination_name!r} — {c.candidate_category} category limit reached")

    combined = user_picks + kept_rest
    if len(combined) > max_total:
        overflow = len(combined) - max_total
        # trim from the back of kept_rest (lowest-priority non-user candidates) first
        trimmed = combined[:max_total]
        warnings.append(f"trimmed {overflow} candidate(s) to respect max_total={max_total}")
        combined = trimmed

    return combined


def _assign_ids(candidates: List[Candidate]) -> None:
    for index, candidate in enumerate(candidates, start=1):
        candidate.id = f"cand_{index}"
