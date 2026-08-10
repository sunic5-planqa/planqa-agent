from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMClient(ABC):
    model: str

    # Callers must instruct the model (in `prompt`/`system`) to respond with JSON only.
    @abstractmethod
    def complete_json(self, *, system: str, prompt: str) -> Any: ...


def parse_json_response(text: str) -> Any:
    cleaned = _JSON_FENCE.sub("", text.strip())
    return json.loads(cleaned)
