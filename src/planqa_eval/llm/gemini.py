from __future__ import annotations

import os
from typing import Any

from google import genai
from google.genai import types

from planqa_eval.llm.base import LLMClient, parse_json_response

DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiClient(LLMClient):
    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None) -> None:
        self.model = model
        self._client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])

    def complete_json(self, *, system: str, prompt: str) -> Any:
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
            ),
        )
        return parse_json_response(response.text)
