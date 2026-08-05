from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType

from planqa_review.llm.base import LLMClient
from planqa_review.dedupe import dedupe_issues
from planqa_review.document import parse_document
from planqa_review.instrumentation import CallEvent, record_call
from planqa_review.tiers import TIER_ORDER, rules_for_tier
from planqa_review.rulebook import RuleBook
from planqa_review.schema import Issue


@dataclass(frozen=True, slots=True)
class ReviewResult:
    doc_id: str
    global_context: str
    issues: tuple[Issue, ...]
    tier_errors: tuple[str, ...] = ()
    call_events: tuple[CallEvent, ...] = ()


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
    around it, so swapping models never touches this file.

    Each stage is isolated with a broad except: models occasionally return malformed JSON
    even in JSON mode (seen live: "Invalid \\uXXXX escape"), and a single tier failing
    shouldn't discard every other tier's already-successful results for this document. Every
    failure is recorded in `tier_errors` rather than silently swallowed.

    Every LLM call is also wrapped with `record_call` so `call_events` carries per-tier/
    per-rule cost attribution for ablation analysis (see instrumentation.py, run_stats.py)
    — this orchestrator is the only place that knows which rules a call was for, so it's
    the only place that needs to change to get that attribution; the profile functions
    themselves are untouched."""
    tier_errors: list[str] = []
    events: list[CallEvent] = []

    try:
        global_context = record_call(
            confirm_llm,
            stage="context",
            tier=None,
            rule_ids=(),
            events=events,
            call=lambda: profile.extract_global_context(document_text, confirm_llm),
        )
    except Exception as error:  # noqa: BLE001 - intentionally broad, see docstring
        global_context = ""
        tier_errors.append(f"Global Context 추출 실패: {error}")

    tree = parse_document(doc_id, document_text)

    all_issues: list[Issue] = []
    for level in TIER_ORDER:
        chunks = list(tree.chunks_for(level))
        if not chunks:
            continue
        tier_rule_ids = tuple(rule.rule_id for rule in rules_for_tier(rulebook, level))
        try:
            candidates = record_call(
                screen_llm,
                stage="screen",
                tier=level,
                rule_ids=tier_rule_ids,
                events=events,
                call=lambda: profile.screen_tier(chunks, rulebook, level, global_context, screen_llm),
            )
            candidate_rule_ids = tuple(sorted({candidate.rule_id for candidate in candidates}))
            issues = record_call(
                confirm_llm,
                stage="confirm",
                tier=level,
                rule_ids=candidate_rule_ids,
                events=events,
                call=lambda: profile.confirm_candidates(
                    candidates, chunks, rulebook, doc_id, level, global_context, document_text, confirm_llm
                ),
            )
            all_issues.extend(issues)
        except Exception as error:  # noqa: BLE001 - intentionally broad, see docstring
            tier_errors.append(f"{level.value} 위계 검토 실패: {error}")

    return ReviewResult(
        doc_id=doc_id,
        global_context=global_context,
        issues=tuple(dedupe_issues(all_issues)),
        tier_errors=tuple(tier_errors),
        call_events=tuple(events),
    )
