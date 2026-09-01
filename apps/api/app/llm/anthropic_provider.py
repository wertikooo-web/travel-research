from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from pydantic import ValidationError

from ..schemas import TripBrief, TripHints
from .provider import LLMConfigError, LLMParseError, deep_json_decode, unwrap_self_nested_keys

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

PROMPT_PATH = Path(__file__).resolve().parents[4] / "prompts" / "parse_brief.md"

TOOL_NAME = "emit_trip_brief"

TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "origin": {
            "type": ["object", "null"],
            "properties": {
                "text": {"type": ["string", "null"], "description": "Origin city/place as the user said it"},
                "iata": {"type": ["string", "null"], "description": "3-letter IATA code, only if confidently known"},
            },
        },
        "travellers": {
            "type": "array",
            "description": "One entry per traveller. Never merge two different people into one entry.",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["adult", "child"]},
                    "age": {"type": ["integer", "null"], "description": "Only for children, if stated"},
                    "citizenships": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                        "description": "ISO 3166-1 alpha-2 codes of every citizenship this traveller holds, if stated",
                    },
                    "travel_passport": {
                        "type": ["string", "null"],
                        "description": (
                            "ISO alpha-2 code of the passport they said they'll travel on. "
                            "Null if not stated, even if only one citizenship is known."
                        ),
                    },
                    "passport_type": {
                        "type": ["string", "null"],
                        "enum": ["biometric", "ordinary", "other", None],
                    },
                },
                "required": ["type"],
            },
        },
        "dates": {
            "type": ["object", "null"],
            "properties": {
                "start": {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD, only if reasonably precise"},
                "end": {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD"},
                "flex_days": {"type": ["integer", "null"]},
            },
        },
        "nights": {
            "type": ["object", "null"],
            "properties": {
                "min": {"type": ["integer", "null"]},
                "max": {"type": ["integer", "null"]},
                "preferred": {"type": ["integer", "null"]},
            },
        },
        "budget": {
            "type": ["object", "null"],
            "properties": {
                "currency": {"type": ["string", "null"], "description": "ISO 4217 currency code, e.g. EUR"},
                "max_total": {"type": ["number", "null"], "description": "Only if a concrete number was stated"},
                "hard_constraint": {"type": ["boolean", "null"]},
            },
        },
        "flight": {
            "type": ["object", "null"],
            "properties": {
                "direct_preferred": {"type": ["boolean", "null"]},
                "max_connections": {"type": ["integer", "null"]},
                "max_duration_hours": {"type": ["number", "null"]},
                "preferred_cabin": {
                    "type": ["string", "null"],
                    "enum": ["economy", "premium_economy", "business", "first", None],
                },
            },
        },
        "hotel": {
            "type": ["object", "null"],
            "properties": {
                "stars_min": {"type": ["integer", "null"], "description": "Only if a star rating or clear synonym was stated"},
                "beachfront": {"type": ["boolean", "null"]},
                "sea_view": {"type": ["boolean", "null"]},
                "meal_min": {
                    "type": ["string", "null"],
                    "enum": ["room_only", "breakfast", "half_board", "full_board", "all_inclusive", None],
                },
            },
        },
        "weather": {
            "type": ["object", "null"],
            "properties": {
                "day_temp_min": {"type": ["number", "null"]},
                "sea_temp_min": {"type": ["number", "null"]},
                "rain_tolerance": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
            },
        },
        "visa": {
            "type": ["object", "null"],
            "properties": {
                "easy_required": {"type": ["boolean", "null"]},
            },
        },
        "preferences": {
            "type": ["object", "null"],
            "properties": {
                "avoid": {"type": "array", "items": {"type": "string"}},
                "prefer": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    "required": ["travellers"],
}


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


_TRIP_BRIEF_FIELDS = set(TripBrief.model_fields.keys())


def _unwrap_if_nested(data: dict) -> dict:
    """The model occasionally wraps the whole payload under one extra key
    (e.g. {"trip_brief": {...actual fields...}}) instead of emitting the tool
    schema's fields at the top level. Validating that as-is silently produces
    an all-null TripBrief instead of raising, so detect and unwrap it."""
    if not isinstance(data, dict) or _TRIP_BRIEF_FIELDS & data.keys():
        return data
    if len(data) == 1:
        (only_value,) = data.values()
        if isinstance(only_value, dict):
            return only_value
    return data


def _build_user_message(raw_text: str, hints: Optional[TripHints]) -> str:
    parts = [f'Free-text trip description from the user:\n"""\n{raw_text}\n"""']
    if hints is not None:
        hints_json = hints.model_dump_json(exclude_none=True)
        if hints_json and hints_json != "{}":
            parts.append(
                "Structured hints already entered via the UI (trustworthy user input, not a guess — "
                "merge them in; if the free text conflicts with a hint, the free text wins):\n"
                f"{hints_json}"
            )
    return "\n\n".join(parts)


class AnthropicProvider:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMConfigError("ANTHROPIC_API_KEY is not set")

        import anthropic  # imported lazily so tests without the package installed don't need it

        self._anthropic = anthropic
        workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        default_headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self.client = anthropic.Anthropic(api_key=api_key, default_headers=default_headers)
        self.model = model or os.environ.get("TRIPMATCH_LLM_MODEL", "claude-sonnet-5")
        self._system_prompt = _load_system_prompt()

    def parse_brief(self, raw_text: str, hints: Optional[TripHints] = None) -> TripBrief:
        user_message = _build_user_message(raw_text, hints)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=self._system_prompt,
                tools=[
                    {
                        "name": TOOL_NAME,
                        "description": "Emit the structured TripBrief extracted from the user's request.",
                        "input_schema": TOOL_SCHEMA,
                    }
                ],
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=[{"role": "user", "content": user_message}],
            )
        except self._anthropic.APIError as e:
            raise LLMParseError(f"LLM request failed: {e}") from e

        tool_use = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_use is None:
            raise LLMParseError("LLM did not return structured output")

        tool_input = deep_json_decode(tool_use.input)
        tool_input = unwrap_self_nested_keys(tool_input)
        tool_input = _unwrap_if_nested(tool_input)

        try:
            return TripBrief.model_validate(tool_input)
        except ValidationError as e:
            raise LLMParseError(f"LLM output failed schema validation: {e}") from e
