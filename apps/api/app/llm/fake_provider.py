from typing import List, Optional, Tuple

from ..schemas import TripBrief, TripHints


class FakeLLMProvider:
    """Test double: returns a canned TripBrief instead of calling a real LLM."""

    def __init__(self, response: Optional[TripBrief] = None):
        self.response = response if response is not None else TripBrief()
        self.calls: List[Tuple[str, Optional[TripHints]]] = []

    def parse_brief(self, raw_text: str, hints: Optional[TripHints] = None) -> TripBrief:
        self.calls.append((raw_text, hints))
        return self.response.model_copy(deep=True)
