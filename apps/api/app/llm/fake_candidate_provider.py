from typing import List, Optional, Tuple

from ..schemas import TripBrief


class FakeCandidateProvider:
    """Test double: returns canned raw candidate dicts instead of calling a real LLM."""

    def __init__(self, raw_candidates: Optional[List[dict]] = None):
        self.raw_candidates = raw_candidates if raw_candidates is not None else []
        self.calls: List[Tuple[TripBrief, Optional[str]]] = []

    def generate(self, brief: TripBrief, raw_request: Optional[str] = None) -> Tuple[List[dict], dict]:
        self.calls.append((brief, raw_request))
        return list(self.raw_candidates), {"candidates": self.raw_candidates}
