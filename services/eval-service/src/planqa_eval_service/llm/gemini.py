from __future__ import annotations

import os
from typing import Any

from google import genai
from google.genai import types

from planqa_eval_service.llm.base import LLMClient, parse_json_response

# "gemini-2.5-flash"/"gemini-2.5-pro" are quota-exhausted (429) on this key/project — same
# finding review-agent's docs/progress.md already recorded (2026-08-05); the "-lite" lineup
# is what actually works. Matters more here than for review-agent: eval-service is meant to
# keep up with review-agent's live request rate, and 2.5-flash's client-side retry-until-it-
# works behavior (~16s/call observed) works against that.
DEFAULT_MODEL = "gemini-flash-lite-latest"


class GeminiClient(LLMClient):
    # Single-key — eval-service's audit traffic is a small fraction of what review-agent
    # itself sends, so the multi-key rotation review-agent/eval-agent need isn't worth the
    # complexity here yet. Revisit if quota becomes a real constraint.
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
