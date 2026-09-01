from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from ..schemas import TripBrief
from .provider import LLMConfigError, LLMParseError, deep_json_decode, unwrap_self_nested_keys

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

PROMPT_PATH = Path(__file__).resolve().parents[4] / "prompts" / "generate_candidates.md"

TOOL_NAME = "emit_candidates"

TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "destination_name": {
                        "type": "string",
                        "description": "The specific place worth researching, e.g. 'Tenerife', 'Zanzibar', 'Maldives'",
                    },
                    "country_code": {
                        "type": ["string", "null"],
                        "description": "ISO 3166-1 alpha-2, or null if not confident",
                    },
                    "destination_type": {
                        "type": ["string", "null"],
                        "enum": ["city", "island", "resort_region", "country", "archipelago", None],
                    },
                    "reason_to_check": {
                        "type": "string",
                        "description": "Why this is worth researching for THIS traveller — a hypothesis, never a verified fact",
                    },
                    "matched_preferences": {"type": "array", "items": {"type": "string"}},
                    "potential_conflicts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Open questions/uncertainties to verify later, e.g. 'direct flight availability unclear'",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["llm", "user"],
                        "description": "'user' ONLY if the traveller explicitly named this destination themselves",
                    },
                    "candidate_category": {"type": "string", "enum": ["core", "alternative", "wildcard"]},
                },
                "required": ["destination_name", "reason_to_check", "source", "candidate_category"],
            },
        }
    },
    "required": ["candidates"],
}


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _unwrap_if_nested(data: dict) -> dict:
    """See anthropic_provider._unwrap_if_nested — same occasional model quirk
    of wrapping the payload under one extra key instead of top-level fields."""
    if not isinstance(data, dict) or "candidates" in data:
        return data
    if len(data) == 1:
        (only_value,) = data.values()
        if isinstance(only_value, dict):
            return only_value
    return data


def _build_user_message(brief: TripBrief, raw_request: Optional[str]) -> str:
    parts = [f"Confirmed TripBrief (structured):\n{brief.model_dump_json(exclude_none=True, indent=2)}"]
    if raw_request:
        parts.append(
            "Original free-text request (use this to catch destinations the "
            "traveller named explicitly, per rule 1):\n"
            f'"""\n{raw_request}\n"""'
        )
    return "\n\n".join(parts)


class AnthropicCandidateProvider:
    """Thin call/parse layer only — validation, dedup, filtering and id
    assignment are the normalization layer's job (research/candidate_generator.py),
    not this provider's. Mirrors AnthropicProvider's shape for parse_brief."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMConfigError("ANTHROPIC_API_KEY is not set")

        import anthropic

        self._anthropic = anthropic
        workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        default_headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self.client = anthropic.Anthropic(api_key=api_key, default_headers=default_headers)
        self.model = model or os.environ.get("TRIPMATCH_LLM_MODEL", "claude-sonnet-5")
        self._system_prompt = _load_system_prompt()

    def generate(self, brief: TripBrief, raw_request: Optional[str] = None) -> tuple[list[dict], dict]:
        user_message = _build_user_message(brief, raw_request)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self._system_prompt,
                tools=[
                    {
                        "name": TOOL_NAME,
                        "description": "Emit the candidate destination pool for this trip brief.",
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

        if not isinstance(tool_input, dict):
            raise LLMParseError("LLM tool output was not a JSON object")

        raw_candidates = tool_input.get("candidates")
        if not isinstance(raw_candidates, list):
            raise LLMParseError("LLM output missing a 'candidates' array")

        return raw_candidates, tool_input
