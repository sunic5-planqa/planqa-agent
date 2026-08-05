from __future__ import annotations

from planqa_eval.review_agent.models import gemini_lite

# A "model profile" is a package under this directory exposing exactly three functions with
# the same signatures as gemini_lite/{context,screener,confirmer}.py:
#
#   extract_global_context(document_text: str, llm: LLMClient) -> str
#   screen_tier(chunks, rulebook, level, global_context, llm) -> list[ScreenCandidate]
#   confirm_candidates(candidates, chunks, rulebook, doc_id, level, global_context,
#                       source_text, llm) -> list[Issue]
#
# pipeline.review_document only ever calls these three functions by name, so a profile is
# free to reimplement all three from scratch (different prompts, batching, JSON parsing —
# whatever the model needs) or import/reuse pieces from another profile if only one stage
# needs to change. To add one: copy gemini_lite/ to <name>/, edit freely, register it below.
PROFILES = {
    "gemini_lite": gemini_lite,
}

DEFAULT_PROFILE = "gemini_lite"
