from __future__ import annotations

import os

from planqa_review.llm.base import LLMClient
from planqa_review.llm.gemini import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from planqa_review.llm.gemini import GeminiClient
from planqa_review.llm.ollama import DEFAULT_MODEL as OLLAMA_DEFAULT_MODEL
from planqa_review.llm.ollama import OllamaClient

_BUILDERS = {
    "gemini": (GeminiClient, GEMINI_DEFAULT_MODEL),
    "ollama": (OllamaClient, OLLAMA_DEFAULT_MODEL),
}


def build_llm_client(
    backend: str | None = None, model: str | None = None, temperature: float = 0.0
) -> LLMClient:
    """Picks the backend via PLANQA_LLM_BACKEND (default: gemini, the cheap-first choice
    per memory: planqa-model-selection-policy). Claude isn't wired in yet — it only gets
    built if a cheap backend fails the 2-1 confidence gate. `temperature` defaults to 0.0
    (not each backend's own default) for ablation-run reproducibility."""
    backend = (backend or os.environ.get("PLANQA_LLM_BACKEND") or "gemini").lower()
    if backend not in _BUILDERS:
        raise ValueError(f"unknown PLANQA_LLM_BACKEND {backend!r}, expected one of {tuple(_BUILDERS)}")

    client_cls, default_model = _BUILDERS[backend]
    return client_cls(
        model=model or os.environ.get("PLANQA_LLM_MODEL") or default_model, temperature=temperature
    )
