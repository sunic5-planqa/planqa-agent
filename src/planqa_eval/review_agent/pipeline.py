from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType

from planqa_eval.llm.base import LLMClient
from planqa_eval.review_agent.dedupe import dedupe_issues
from planqa_eval.review_agent.document import parse_document
from planqa_eval.review_agent.tiers import TIER_ORDER
from planqa_eval.rulebook import RuleBook
from planqa_eval.schema import Issue


@dataclass(frozen=True, slots=True)
class ReviewResult:
    doc_id: str
    global_context: str
    issues: tuple[Issue, ...]


def review_document(
    doc_id: str,
    document_text: str,
    rulebook: RuleBook,
    screen_llm: LLMClient,
    confirm_llm: LLMClient,
    profile: ModuleType,
) -> ReviewResult:
    """The one function the CLI (and any future caller) drives end to end — see
    docs/review_agent_architecture.md for the full 6-stage design this assembles:
    Global Context -> 위계 분할 -> per-tier (스크리닝 -> 정밀판정) -> 중복 제거. `profile`
    supplies the actual prompt/logic for those three LLM-facing steps (see
    review_agent/models/__init__.py) — this function only owns the fixed control flow
    around it, so swapping models never touches this file."""
    global_context = profile.extract_global_context(document_text, confirm_llm)
    tree = parse_document(doc_id, document_text)

    all_issues: list[Issue] = []
    for level in TIER_ORDER:
        chunks = list(tree.chunks_for(level))
        if not chunks:
            continue
        candidates = profile.screen_tier(chunks, rulebook, level, global_context, screen_llm)
        all_issues.extend(
            profile.confirm_candidates(
                candidates, chunks, rulebook, doc_id, level, global_context, document_text, confirm_llm
            )
        )

    return ReviewResult(doc_id=doc_id, global_context=global_context, issues=tuple(dedupe_issues(all_issues)))
