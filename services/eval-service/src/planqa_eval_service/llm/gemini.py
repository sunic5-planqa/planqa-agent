from __future__ import annotations

import os
from typing import Any

from google import genai
from google.genai import types

from planqa_eval_service.llm.base import LLMClient, parse_json_response

DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiClient(LLMClient):
    """Single-key client — eval-service's audit traffic is a small fraction of what
    review-agent itself sends, so the multi-key rotation review-agent/eval-agent need
    isn't worth the complexity here yet. Revisit if quota becomes a real constraint."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        self.model = model
        self._client = genai.Client(api_key=api_key)

    def complete_json(self, *, system: str, prompt: str) -> Any:
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json"),
        )
        return parse_json_response(response.text)
