from __future__ import annotations

from planqa_review.llm.base import LLMClient

_SYSTEM = (
    "You read one Korean product-planning document (기획서) and produce a compact context "
    "summary that will be prepended to every later review prompt about this same document, "
    "so it must stand on its own without the full document attached. Capture: the "
    "document's core purpose, its key policies/constraints, and its target KPIs/goals — "
    "exactly what a reviewer needs to judge whether *other* sections of the document stay "
    "consistent with what this document set out to do. Keep it to a few sentences.\n"
    'Respond with JSON only: {"summary": "<compact Korean summary>"}'
)


def extract_global_context(document_text: str, llm: LLMClient) -> str:
    """Stage 1 of the review pipeline (see docs/review_agent_architecture.md): one call
    against the whole document, reused verbatim in every later screen/confirm prompt so the
    model doesn't need the full document re-attached (and stays consistent) on every call."""
    response = llm.complete_json(system=_SYSTEM, prompt=document_text)
    summary = response.get("summary") if isinstance(response, dict) else None
    return summary.strip() if isinstance(summary, str) and summary.strip() else ""
