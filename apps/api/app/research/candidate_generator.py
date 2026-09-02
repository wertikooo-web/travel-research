from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol

from pydantic import ValidationError

from ..llm.provider import LLMParseError
from ..schemas import Candidate, DestinationPick, TripBrief
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
    structure first, enforce the avoid-list before dedup, cap pool size
    before the final guarantee pass — so `_ensure_destination_picks` is the
    last word on what survives, never subject to a category or total limit.

    `brief.destination_picks` is user intent, confirmed as part of the
    brief — not something this function infers from raw_request or from
    what the LLM decided to propose. LLM proposes, user decides, backend
    guarantees: every pick in destination_picks is in the returned pool,
    every time, regardless of what provider.generate() returned.
    """
    raw_candidates, raw_llm_output = provider.generate(brief, raw_request)
    if not isinstance(raw_candidates, list):
        raise LLMParseError("candidate provider returned a non-list candidates payload")

    picks = brief.destination_picks or []

    warnings: List[str] = []
    validated = _validate(raw_candidates, warnings)
    filtered = _apply_avoid_filter(validated, brief, picks, warnings)
    deduped = _deduplicate(filtered, warnings)
    capped = _cap_pool(deduped, max_total, max_core, max_alternative, max_wildcard, warnings)
    guaranteed = _ensure_destination_picks(capped, picks, warnings)
    _detect_pick_avoid_conflicts(brief, picks, warnings)

    if len(guaranteed) > max_total:
        warnings.append(
            f"explicit picks push the pool to {len(guaranteed)} candidates, exceeding max_total={max_total} — kept anyway"
        )

    _assign_ids(guaranteed)

    if not guaranteed:
        warnings.append("no candidates survived generation + normalization")

    return CandidateGenerationResult(candidates=guaranteed, raw_llm_output=raw_llm_output, warnings=warnings)


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


def _apply_avoid_filter(
    candidates: List[Candidate], brief: TripBrief, picks: List[DestinationPick], warnings: List[str]
) -> List[Candidate]:
    avoid_codes, avoid_terms = _avoid_codes_and_terms(brief)
    if not avoid_codes and not avoid_terms:
        return candidates

    kept = []
    for c in candidates:
        if _matches_avoid(c, avoid_codes, avoid_terms):
            if _matches_any_pick(c, picks):
                # explicit user intent overrides avoid — see _detect_pick_avoid_conflicts,
                # which surfaces this contradiction as a warning instead of silently dropping either side
                kept.append(c)
                continue
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

    # user picks are never trimmed, even if they alone exceed max_total — only
    # the non-user remainder yields room, and if picks alone already exceed
    # the limit the pool is allowed to exceed it too (never removed to fit).
    room = max(0, max_total - len(user_picks))
    if len(kept_rest) > room:
        overflow = len(kept_rest) - room
        warnings.append(f"trimmed {overflow} candidate(s) to respect max_total={max_total}")
        kept_rest = kept_rest[:room]
    if len(user_picks) > max_total:
        warnings.append(
            f"user picks alone ({len(user_picks)}) exceed max_total={max_total} — keeping all of them anyway"
        )

    return user_picks + kept_rest


def _pick_stub(pick: DestinationPick) -> Candidate:
    return Candidate(
        destination_name=pick.text,
        country_code=pick.country_code or resolve_country_code(pick.text),
        reason_to_check="",
        source="user",
        candidate_category="core",
    )


def _matches_any_pick(candidate: Candidate, picks: List[DestinationPick]) -> bool:
    return any(_is_near_duplicate(candidate, _pick_stub(p)) for p in picks)


def _ensure_destination_picks(
    candidates: List[Candidate], picks: List[DestinationPick], warnings: List[str]
) -> List[Candidate]:
    """The final word on user intent: every explicit pick is in the pool
    afterward, no exceptions. Reuses a matching candidate (promoting it to
    source=user) when one made it through normalization; synthesizes a
    minimal one when the provider omitted the pick entirely."""
    result = list(candidates)
    for pick in picks:
        stub = _pick_stub(pick)
        match_index = next((i for i, c in enumerate(result) if _is_near_duplicate(c, stub)), None)

        if match_index is not None:
            match = result[match_index]
            if match.source != "user":
                warnings.append(f"promoted {match.destination_name!r} to a user pick (explicitly named: {pick.text!r})")
                result[match_index] = match.model_copy(update={"source": "user"})
            continue

        warnings.append(f"added user pick {pick.text!r} — the provider omitted it")
        result.append(
            stub.model_copy(
                update={"reason_to_check": "Explicitly named by the traveller — include for research regardless of automated fit."}
            )
        )
    return result


def _detect_pick_avoid_conflicts(brief: TripBrief, picks: List[DestinationPick], warnings: List[str]) -> None:
    if not picks:
        return
    avoid_codes, avoid_terms = _avoid_codes_and_terms(brief)
    if not avoid_codes and not avoid_terms:
        return
    for pick in picks:
        stub = _pick_stub(pick)
        if _matches_avoid(stub, avoid_codes, avoid_terms):
            warnings.append(
                f"conflict: {pick.text!r} is both an explicit pick and on the avoid list — "
                "kept as a candidate, needs manual resolution by the traveller"
            )


def _assign_ids(candidates: List[Candidate]) -> None:
    for index, candidate in enumerate(candidates, start=1):
        candidate.id = f"cand_{index}"
