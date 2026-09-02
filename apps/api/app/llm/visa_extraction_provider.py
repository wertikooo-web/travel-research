from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

from ..schemas import EntryMethodType
from .provider import LLMConfigError, LLMParseError, deep_json_decode, unwrap_self_nested_keys

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

PROMPT_PATH = Path(__file__).resolve().parents[4] / "prompts" / "extract_visa.md"
TOOL_NAME = "emit_visa_classification"

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "methods": {
            "type": "array",
            "description": (
                "Every entry method the text actually states — more than one if the source "
                "offers alternatives (e.g. 'visa on arrival or eVisa' -> both). Empty if none apply."
            ),
            "items": {
                "type": "string",
                "enum": [
                    "visa_free",
                    "visa_on_arrival",
                    "evisa",
                    "electronic_authorization",
                    "visa_required",
                    "entry_restricted",
                ],
            },
        },
    },
    "required": ["methods"],
}


class AnthropicVisaExtractionProvider:
    """Bounded fallback only: classifies one already-fetched table row when
    the deterministic regex classifier in research/visa.py doesn't recognize
    the phrasing. Never asked to recall a visa rule from memory — only to
    read text it's handed."""

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
        self._system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def classify(self, requirement_text: str, allowed_stay_text: str, notes: str) -> List[EntryMethodType]:
        user_message = (
            f"Requirement text: {requirement_text!r}\nAllowed stay text: {allowed_stay_text!r}\nNotes: {notes!r}"
        )
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=256,
                system=self._system_prompt,
                tools=[{"name": TOOL_NAME, "description": "Classify the given visa row.", "input_schema": TOOL_SCHEMA}],
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=[{"role": "user", "content": user_message}],
            )
        except self._anthropic.APIError as e:
            raise LLMParseError(f"visa extraction request failed: {e}") from e

        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use is None:
            raise LLMParseError("visa extraction returned no structured output")

        tool_input = deep_json_decode(tool_use.input)
        tool_input = unwrap_self_nested_keys(tool_input)
        if not isinstance(tool_input, dict) or "methods" not in tool_input:
            raise LLMParseError("visa extraction output missing 'methods'")

        methods = tool_input["methods"]
        if not isinstance(methods, list):
            raise LLMParseError("visa extraction 'methods' was not a list")
        return methods


class FakeVisaExtractionProvider:
    def __init__(self, result: Optional[List[EntryMethodType]] = None):
        self.result = result if result is not None else []
        self.calls = []

    def classify(self, requirement_text: str, allowed_stay_text: str, notes: str) -> List[EntryMethodType]:
        self.calls.append((requirement_text, allowed_stay_text, notes))
        return self.result
