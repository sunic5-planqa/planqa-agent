from __future__ import annotations

from planqa_eval_service.llm.base import LLMClient
from planqa_eval_service.llm.gemini import DEFAULT_MODEL, GeminiClient

# Cloud-only, deliberately — eval-service audits *live* traffic and has to keep up with
# review-agent's own request rate, so a local model that only one dev machine can run isn't
# an option here the way it is for eval-agent's offline benchmark runs.
_BUILDERS = {
    "gemini": (GeminiClient, DEFAULT_MODEL),
}


def build_llm_client(backend: str | None = None, model: str | None = None) -> LLMClient:
    backend = (backend or "gemini").lower()
    if backend not in _BUILDERS:
        raise ValueError(f"unknown backend {backend!r}, expected one of {tuple(_BUILDERS)}")
    client_cls, default_model = _BUILDERS[backend]
    return client_cls(model=model or default_model)
