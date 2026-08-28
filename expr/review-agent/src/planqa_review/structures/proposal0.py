from __future__ import annotations

from planqa_review.dedupe import dedupe_issues
from planqa_review.document import Chunk, parse_document
from planqa_review.instrumentation import CallEvent, record_call
from planqa_review.llm.base import LLMClient
from planqa_review.models.gemini_lite.context import extract_global_context
from planqa_review.pipeline import ReviewResult
from planqa_review.rulebook import RuleBook, RuleDef
from planqa_review.schema import Issue, Level
from planqa_review.tiers import TIER_ORDER, rules_for_tier
from planqa_review.verifier import has_valid_reference_exception

_SYSTEM = (
    "You are a single-pass document QA reviewer — there is no separate cheap screening "
    "step before you, so decide directly whether each rule is actually violated (don't "
    "over-flag on the assumption something else will double-check). For each numbered "
    "chunk below, check it against the numbered rules. If a rule is violated: quote the "
    "exact evidence sentence from the chunk (original_text), state what's wrong "
    "(description), explain why it breaks the rule (rationale), and write a concrete "
    "revised version of the text that would fix it (fix_direction) — phrase it as a "
    "suggestion, not a command. Also apply the rule's own exception condition if given; "
    "set excused=true (with excuse_reason) when it applies. Only report genuine violations.\n"
    'Respond with JSON only: {"violations": [{"chunk_index": <int>, "rule_id": "<id>", '
    '"original_text": "<quote>", "description": "<what\'s wrong>", "rationale": '
    '"<why it violates the rule>", "fix_direction": "<suggested revision>", "excused": '
    '<bool>, "excuse_reason": "<string or null>"}, ...]}'
)


def _rule_block(rule: RuleDef) -> str:
    return f"{rule.rule_id} ({rule.category_label}): {rule.text}\n  exception condition: {rule.exception_text or '없음'}"


def _build_prompt(chunks: list[Chunk], rules: list[RuleDef], global_context: str) -> str:
    rule_block = "\n".join(_rule_block(rule) for rule in rules)
    chunk_block = "\n\n".join(f"[{i}] ({chunk.location})\n{chunk.text}" for i, chunk in enumerate(chunks))
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    return f"{context_block}Rules to check:\n{rule_block}\n\nChunks:\n{chunk_block}\n\nReturn the violations JSON."


def _is_reference_excused(rule_id: str, rulebook: RuleBook, original_text: str, doc_id: str, level: Level, location: str, source_text: str) -> bool:
    """Same §3 deterministic proxy gemini_lite's confirmer.py uses — duplicated rather than
    imported since that module is baseline structure code (제안5) this structure must not
    depend on or touch, per the additive-only rule."""
    if rule_id not in rulebook.reference_exception_rule_ids:
        return False
    probe = Issue(doc_id=doc_id, level=level.value, rule_id=rule_id, location=location, description="", original_text=original_text)
    return has_valid_reference_exception(probe, source_text)


def _review_tier(
    chunks: list[Chunk], rules: list[RuleDef], level: Level, global_context: str, doc_id: str, source_text: str, rulebook: RuleBook, llm: LLMClient
) -> list[Issue]:
    response = llm.complete_json(system=_SYSTEM, prompt=_build_prompt(chunks, rules, global_context))
    raw_violations = response.get("violations", []) if isinstance(response, dict) else []
    valid_rule_ids = {rule.rule_id for rule in rules}

    issues: list[Issue] = []
    for item in raw_violations:
        if not isinstance(item, dict):
            continue
        chunk_index, rule_id = item.get("chunk_index"), item.get("rule_id")
        if not (isinstance(chunk_index, int) and 0 <= chunk_index < len(chunks)) or rule_id not in valid_rule_ids:
            continue
        chunk = chunks[chunk_index]
        original_text = str(item.get("original_text") or "").strip()
        excused = bool(item.get("excused")) or _is_reference_excused(rule_id, rulebook, original_text, doc_id, level, chunk.location, source_text)
        if excused:
            continue
        issues.append(
            Issue(
                doc_id=doc_id,
                level=level.value,
                rule_id=rule_id,
                location=chunk.location,
                description=str(item.get("description") or "").strip(),
                source="review_agent",
                original_text=original_text or None,
                rationale=str(item.get("rationale") or "").strip() or None,
                fix_direction=str(item.get("fix_direction") or "").strip() or None,
            )
        )
    return issues


def review_document(
    doc_id: str, document_text: str, rulebook: RuleBook, screen_llm: LLMClient, confirm_llm: LLMClient
) -> ReviewResult:
    """제안0 — floor baseline for "is the 2-stage screen→confirm split worth its extra
    calls at all?": same tier chunking/category assignment as 제안5, but one call per tier
    goes straight to a final verdict. `screen_llm` is unused (kept only so this matches the
    `experiment.ReviewFn` shape every structure plugs into the same harness with) — point
    both --screen-model/--verify-model at the same model, or ignore --screen-model."""
    del screen_llm
    tier_errors: list[str] = []
    events: list[CallEvent] = []

    try:
        global_context = record_call(
            confirm_llm,
            stage="context",
            tier=None,
            rule_ids=(),
            events=events,
            call=lambda: extract_global_context(document_text, confirm_llm),
        )
    except Exception as error:  # noqa: BLE001 - one tier's failure shouldn't sink the whole review
        global_context = ""
        tier_errors.append(f"Global Context 추출 실패: {error}")

    tree = parse_document(doc_id, document_text)
    all_issues: list[Issue] = []
    for level in TIER_ORDER:
        chunks = list(tree.chunks_for(level))
        rules = rules_for_tier(rulebook, level)
        if not chunks or not rules:
            continue
        tier_rule_ids = tuple(rule.rule_id for rule in rules)
        try:
            issues = record_call(
                confirm_llm,
                stage="single_pass",
                tier=level,
                rule_ids=tier_rule_ids,
                events=events,
                call=lambda: _review_tier(chunks, rules, level, global_context, doc_id, document_text, rulebook, confirm_llm),
            )
            all_issues.extend(issues)
        except Exception as error:  # noqa: BLE001 - see above
            tier_errors.append(f"{level.value} 위계 검토 실패: {error}")

    return ReviewResult(
        doc_id=doc_id,
        global_context=global_context,
        issues=tuple(dedupe_issues(all_issues)),
        tier_errors=tuple(tier_errors),
        call_events=tuple(events),
    )
