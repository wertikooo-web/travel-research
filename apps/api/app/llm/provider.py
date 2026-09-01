from typing import Optional, Protocol

from ..schemas import TripBrief, TripHints


class LLMParseError(Exception):
    """The LLM call failed or returned something we can't trust."""


class LLMConfigError(Exception):
    """The LLM provider is missing required configuration (e.g. an API key)."""


class LLMProvider(Protocol):
    def parse_brief(self, raw_text: str, hints: Optional[TripHints] = None) -> TripBrief: ...
