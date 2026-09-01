import json
from typing import Any, Optional, Protocol

from ..schemas import TripBrief, TripHints


class LLMParseError(Exception):
    """The LLM call failed or returned something we can't trust."""


class LLMConfigError(Exception):
    """The LLM provider is missing required configuration (e.g. an API key)."""


class LLMProvider(Protocol):
    def parse_brief(self, raw_text: str, hints: Optional[TripHints] = None) -> TripBrief: ...


def deep_json_decode(value: Any) -> Any:
    """Recursively json.loads any string that looks like encoded JSON.

    Observed live: forced tool-use occasionally stringifies a whole nested
    object or array (or the entire payload) instead of emitting native JSON
    structure — anywhere from the top level down to a single field. Handling
    it once, generically, here beats special-casing every field that might
    be affected.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in "{[":
            try:
                return deep_json_decode(json.loads(stripped))
            except (json.JSONDecodeError, ValueError):
                return value
        return value
    if isinstance(value, dict):
        return {k: deep_json_decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [deep_json_decode(v) for v in value]
    return value


def unwrap_self_nested_keys(value: Any) -> Any:
    """Collapse {"key": {"key": <actual value>}} down to {"key": <actual value>}, recursively.

    A second, related quirk from the same root cause as deep_json_decode: the
    model sometimes re-wraps a field's value under a dict with a single key
    matching that same field's name (e.g. travellers -> {"travellers": [...]})
    instead of emitting the value directly. Only collapses a *single-key* dict
    keyed by the *same* name — a normal single-field object like
    {"easy_required": null} isn't touched, since its key doesn't match the
    key it's nested under.
    """
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            v = unwrap_self_nested_keys(v)
            if isinstance(v, dict) and len(v) == 1 and k in v:
                v = v[k]
            result[k] = v
        return result
    if isinstance(value, list):
        return [unwrap_self_nested_keys(v) for v in value]
    return value
