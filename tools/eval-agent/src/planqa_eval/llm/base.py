from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMClient(ABC):
    """Every Matcher/Judge/신규룰 판별 call goes through this — swap the backend by changing
    PLANQA_LLM_BACKEND (see llm/factory.py), not by touching the modules that use it."""

    model: str

    @abstractmethod
    def complete_json(self, *, system: str, prompt: str) -> Any:
        """Sends `prompt` under `system` instructions and returns the parsed JSON response.
        Callers must instruct the model (in `prompt`/`system`) to respond with JSON only."""


def parse_json_response(text: str) -> Any:
    """Defensive parse for backends without a native JSON-only mode: strips ```json fences
    a model may still wrap its answer in despite instructions."""
    cleaned = _JSON_FENCE.sub("", text.strip())
    return json.loads(cleaned)
