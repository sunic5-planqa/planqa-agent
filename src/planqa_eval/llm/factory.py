from __future__ import annotations

import os

from planqa_eval.llm.base import LLMClient
from planqa_eval.llm.gemini import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from planqa_eval.llm.gemini import GeminiClient
from planqa_eval.llm.ollama import DEFAULT_MODEL as OLLAMA_DEFAULT_MODEL
from planqa_eval.llm.ollama import OllamaClient

_BUILDERS = {
    "gemini": (GeminiClient, GEMINI_DEFAULT_MODEL),
    "ollama": (OllamaClient, OLLAMA_DEFAULT_MODEL),
}


def build_llm_client(backend: str | None = None, model: str | None = None) -> LLMClient:
    """Picks the backend via PLANQA_LLM_BACKEND (default: gemini, the cheap-first choice
    per memory: planqa-model-selection-policy). Claude isn't wired in yet — it only gets
    built if a cheap backend fails the 2-1 confidence gate."""
    backend = (backend or os.environ.get("PLANQA_LLM_BACKEND") or "gemini").lower()
    if backend not in _BUILDERS:
        raise ValueError(f"unknown PLANQA_LLM_BACKEND {backend!r}, expected one of {tuple(_BUILDERS)}")

    client_cls, default_model = _BUILDERS[backend]
    return client_cls(model=model or os.environ.get("PLANQA_LLM_MODEL") or default_model)
