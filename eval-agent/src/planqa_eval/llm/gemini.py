from __future__ import annotations

import os
import time
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from planqa_eval.llm.base import LLMClient, parse_json_response

DEFAULT_MODEL = "gemini-2.5-flash"

# The free tier caps out fast (as low as 5 RPM, or 20 requests/day on some models), and a
# batch run naturally fires many calls back to back. GEMINI_API_KEYS lets several free-tier
# keys/projects be round-robined to multiply the effective daily quota; _MAX_CYCLES guards
# against looping forever once every key is genuinely exhausted for the day.
_MAX_CYCLES = 3
_DEFAULT_RETRY_DELAY_SECONDS = 20.0


def _load_api_keys(explicit: list[str] | None) -> list[str]:
    if explicit:
        return explicit
    multi = os.environ.get("GEMINI_API_KEYS")
    if multi:
        keys = [key.strip() for key in multi.split(",") if key.strip()]
        if keys:
            return keys
    single = os.environ.get("GEMINI_API_KEY")
    if single:
        return [single]
    raise RuntimeError(
        "No Gemini API key found — set GEMINI_API_KEY (one key) or GEMINI_API_KEYS "
        "(comma-separated, to round-robin across multiple free-tier quotas) in .env"
    )


def _retry_delay_seconds(error: genai_errors.ClientError) -> float:
    details = error.details if isinstance(error.details, dict) else {}
    for detail in details.get("error", {}).get("details", []):
        if detail.get("@type", "").endswith("RetryInfo"):
            raw = detail.get("retryDelay", "")
            if raw.endswith("s"):
                try:
                    return float(raw[:-1])
                except ValueError:
                    pass
    return _DEFAULT_RETRY_DELAY_SECONDS


class GeminiClient(LLMClient):
    def __init__(self, model: str = DEFAULT_MODEL, api_keys: list[str] | None = None) -> None:
        self.model = model
        self._clients = [genai.Client(api_key=key) for key in _load_api_keys(api_keys)]
        self._current = 0

    def complete_json(self, *, system: str, prompt: str) -> Any:
        last_error: genai_errors.ClientError | None = None
        for _cycle in range(_MAX_CYCLES):
            for _ in range(len(self._clients)):
                client = self._clients[self._current]
                try:
                    response = client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system,
                            response_mime_type="application/json",
                        ),
                    )
                    return parse_json_response(response.text)
                except genai_errors.ClientError as error:
                    if error.code != 429:
                        raise
                    last_error = error
                    self._current = (self._current + 1) % len(self._clients)
            # every key hit 429 this cycle — back off before cycling through them again
            time.sleep(_retry_delay_seconds(last_error))
        raise last_error
