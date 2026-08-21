from __future__ import annotations

from dataclasses import dataclass

from planqa_review.dedupe import dedupe_issues
from planqa_review.document import Chunk, parse_document, resolve_reported_level
from planqa_review.instrumentation import CallEvent, record_call
from planqa_review.llm.base import LLMClient
from planqa_review.pipeline import ReviewResult
from planqa_review.rulebook import RuleBook, RuleDef
from planqa_review.schema import Issue, Level
from planqa_review.structures.fewshot_bank import EXCEPTION_EXAMPLES_RATIO, VIOLATION_EXAMPLES
from planqa_review.tiers import ABSENCE_CHECK_RULE_IDS
from planqa_review.verifier import is_reference_excused_by_rule

# bundled_screen_fewshot_ratio — 퓨샷 "위반/예외 비율 조정" 축 전용 셀(콜통합판).
# bundled_screen_fewshot(재선정된 기준선: 위반 2개+예외 1개)과 완전히 동일하되, 예외 예시만
# EXCEPTION_EXAMPLES(1개) 대신 EXCEPTION_EXAMPLES_RATIO(2개)로 준다 — 2026-08-10 재설계.

_GA_CATEGORY = "GA"

_GLOBAL_CONTEXT_SYSTEM = (
    "You read one Korean product-planning document (기획서) and produce a compact context "
    "summary that will be prepended to every later review prompt about this same document, "
    "so it must stand on its own without the full document attached. Capture: the "
    "document's core purpose, its key policies/constraints, and its target KPIs/goals — "
    "exactly what a reviewer needs to judge whether *other* sections of the document stay "
    "consistent with what this document set out to do. Keep it to a few sentences.\n"
    'Respond with JSON only: {"summary": "<compact Korean summary>"}'
)


def _extract_global_context(document_text: str, llm: LLMClient) -> str:
    response = llm.complete_json(system=_GLOBAL_CONTEXT_SYSTEM, prompt=document_text)
    summary = response.get("summary") if isinstance(response, dict) else None
    return summary.strip() if isinstance(summary, str) and summary.strip() else ""


_RELATIONAL_CATEGORIES = frozenset({"LG", "LF", "GA"})

_SCREEN_FEWSHOT_SYSTEM = (
    "You are the cheap, wide first pass of a two-stage document QA pipeline (screen now, "
    "a stronger model verifies later) — favor recall over precision, flag anything even "
    "mildly suspicious. You are NOT given the rule text — only each rule's id and a few "
    "labeled examples of what a real violation looks like. For each numbered chunk below, "
    "check it against the rules (which may span several review categories at once; learn "
    "each rule_id's pattern from its examples) and list every span that might violate one, "
    "however uncertain.\n"
    'Respond with JSON only: {"candidates": [{"chunk_index": <int>, "rule_id": "<id>", '
    '"quoted_text": "<exact span from the chunk>", "reason": "<one short line>"}, ...]}'
)

_CONFIRM_FEWSHOT_SYSTEM = (
    "You are the precise, expensive second pass of a two-stage document QA pipeline. You "
    "are NOT given the rule text — only each rule's id and a few labeled examples of what a "
    "real violation and a real excused (non-violation) case look like for it. Decide, "
    "precisely this time, whether each flagged span actually matches the violation pattern "
    "shown for its rule_id — the screening pass over-flags on purpose, so most candidates "
    "should come back violated=false. If it does violate: quote the exact evidence sentence "
    "from the document (original_text), state what's wrong (description), explain why it "
    "matches the violation pattern (rationale), and write a concrete revised version of the "
    "text that would fix it (fix_direction) — phrase it as a suggestion, not a command. If "
    "the case matches an excused-example pattern instead, set excused=true (with "
    "excuse_reason). For the LG/LF/GA categories specifically, a violation is by definition "
    "a relationship error between two locations in the document — also name the OTHER "
    "location involved (related_location), using the same label style as the location you "
    "were given; leave related_location null for every other category, or if no specific "
    "second location can be identified. When claiming two locations conflict, first confirm "
    "they actually assert different facts — restating the same fact in different words or "
    "at different levels of detail is NOT a conflict; only flag a genuine logical "
    "contradiction. If several of the candidates above (even ones flagged under different "
    "rule_ids) are really the same underlying problem, confirm violated=true on only ONE of "
    "them and set the rest to violated=false — don't confirm every repeat. Each candidate "
    "was screened at one specific chunk's granularity, but if the violation actually spans "
    "a broader unit than that chunk, say so with \"level\": name the coarser level it "
    "really belongs at (\"Document\", \"Logical Unit\", \"Paragraph\", or \"Sentence\", "
    "coarsest to finest) instead of leaving it at the chunk's own granularity — omit it (or "
    "repeat the chunk's own level) when the finding genuinely doesn't extend beyond the "
    "one chunk.\n"
    'Respond with JSON only: {"verdicts": [{"index": <int>, "violated": <bool>, '
    '"original_text": "<quote>", "description": "<what\'s wrong>", "rationale": '
    '"<why it matches the rule\'s violation pattern>", "fix_direction": "<suggested '
    'revision>", "excused": <bool>, "excuse_reason": "<string or null>", '
    '"related_location": "<string or null>", "level": "<Document|Logical Unit|Paragraph|'
    'Sentence, or null>"}, ...]}'
)


def _fewshot_block(rule: RuleDef) -> str:
    lines = [f"  {rule.rule_id} ({rule.category_label}):"]
    for example in VIOLATION_EXAMPLES.get(rule.rule_id, []):
        lines.append(f"    - VIOLATION example: {example.original_text!r} — {example.rationale}")
    for exception in EXCEPTION_EXAMPLES_RATIO.get(rule.rule_id, []):
        lines.append(
            f"    - EXCUSED example ({exception.exception_condition}): {exception.original_text!r} — {exception.rationale}"
        )
    if len(lines) == 1:
        lines.append("    - (no curated example available — judge from the rule_id/category label alone)")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _Candidate:
    chunk_index: int
    rule_id: str
    quoted_text: str
    reason: str


def _screen_pass(chunks: list[Chunk], rules: list[RuleDef], global_context: str, llm: LLMClient) -> list[_Candidate]:
    fewshot_block = "\n".join(_fewshot_block(rule) for rule in rules)
    chunk_block = "\n\n".join(f"[{i}] ({chunk.location})\n{chunk.text}" for i, chunk in enumerate(chunks))
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    prompt = f"{context_block}Rules (id + examples, no rule text):\n{fewshot_block}\n\nChunks:\n{chunk_block}\n\nReturn the candidates JSON."

    response = llm.complete_json(system=_SCREEN_FEWSHOT_SYSTEM, prompt=prompt)
    raw = response.get("candidates", []) if isinstance(response, dict) else []
    valid_rule_ids = {rule.rule_id for rule in rules}

    candidates: list[_Candidate] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        chunk_index, rule_id = item.get("chunk_index"), item.get("rule_id")
        if not (isinstance(chunk_index, int) and 0 <= chunk_index < len(chunks)) or rule_id not in valid_rule_ids:
            continue
        candidates.append(
            _Candidate(
                chunk_index=chunk_index,
                rule_id=rule_id,
                quoted_text=str(item.get("quoted_text", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
            )
        )
    return candidates


def _confirm_pass(
    candidates: list[_Candidate],
    chunks: list[Chunk],
    rules_by_id: dict[str, RuleDef],
    doc_id: str,
    level: Level,
    global_context: str,
    source_text: str,
    rulebook: RuleBook,
    llm: LLMClient,
) -> list[Issue]:
    blocks = []
    for i, candidate in enumerate(candidates):
        rule = rules_by_id[candidate.rule_id]
        chunk = chunks[candidate.chunk_index]
        blocks.append(
            f"[{i}] rule {rule.rule_id} ({rule.category_label}):\n{_fewshot_block(rule)}\n"
            f"  location: {chunk.location}\n"
            f"  full unit text: {chunk.text!r}\n"
            f"  screened span: {candidate.quoted_text!r} (screening reason: {candidate.reason})"
        )
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    prompt = f"{context_block}{chr(10).join(blocks)}\n\nReturn the verdicts JSON."

    response = llm.complete_json(system=_CONFIRM_FEWSHOT_SYSTEM, prompt=prompt)
    raw_verdicts = response.get("verdicts", []) if isinstance(response, dict) else []
    by_index = {item["index"]: item for item in raw_verdicts if isinstance(item, dict) and "index" in item}

    issues: list[Issue] = []
    for i, candidate in enumerate(candidates):
        values = by_index.get(i)
        if values is None or not values.get("violated"):
            continue
        original_text = str(values.get("original_text") or candidate.quoted_text).strip()
        chunk = chunks[candidate.chunk_index]
        excused = bool(values.get("excused")) or is_reference_excused_by_rule(
            candidate.rule_id, rulebook, original_text, doc_id, level, chunk.location, source_text
        )
        if excused:
            continue
        related_location = None
        if rules_by_id[candidate.rule_id].category in _RELATIONAL_CATEGORIES:
            raw_related = values.get("related_location")
            related_location = str(raw_related).strip() or None if raw_related else None
        reported_level, reported_location = resolve_reported_level(level, chunk.location, values.get("level"))
        issues.append(
            Issue(
                doc_id=doc_id,
                level=reported_level.value,
                rule_id=candidate.rule_id,
                location=reported_location,
                description=str(values.get("description") or "").strip(),
                source="review_agent",
                original_text=original_text,
                rationale=str(values.get("rationale") or "").strip() or None,
                fix_direction=str(values.get("fix_direction") or "").strip() or None,
                related_location=related_location,
            )
        )
    return issues


def _paragraph_and_document_rules(rulebook: RuleBook) -> tuple[list[RuleDef], list[RuleDef]]:
    paragraph_rules: list[RuleDef] = []
    document_rules: list[RuleDef] = []
    for rule in rulebook.rules.values():
        if rule.category == _GA_CATEGORY or rule.rule_id in ABSENCE_CHECK_RULE_IDS:
            document_rules.append(rule)
        else:
            paragraph_rules.append(rule)
    return paragraph_rules, document_rules


def review_document(
    doc_id: str,
    document_text: str,
    rulebook: RuleBook,
    screen_llm: LLMClient,
    confirm_llm: LLMClient,
) -> ReviewResult:
    """bundled_screen_fewshot_ratio — bundled_screen_fewshot과 완전히 동일(2단계, 문단형,
    위반 예시 2개)하지만 예외 예시만 1개 대신 2개를 준다."""
    tier_errors: list[str] = []
    events: list[CallEvent] = []

    try:
        global_context = record_call(
            confirm_llm,
            stage="context",
            tier=None,
            rule_ids=(),
            events=events,
            call=lambda: _extract_global_context(document_text, confirm_llm),
        )
    except Exception as error:  # noqa: BLE001 - one pass's failure shouldn't sink the whole review
        global_context = ""
        tier_errors.append(f"Global Context 추출 실패: {error}")

    tree = parse_document(doc_id, document_text)
    paragraph_rules, document_rules = _paragraph_and_document_rules(rulebook)
    all_issues: list[Issue] = []

    passes = (
        (Level.PARAGRAPH, paragraph_rules, list(tree.chunks_for(Level.PARAGRAPH))),
        (Level.DOCUMENT, document_rules, list(tree.chunks_for(Level.DOCUMENT))),
    )
    for level, rules, chunks in passes:
        if not chunks or not rules:
            continue
        try:
            candidates = record_call(
                screen_llm,
                stage="screen",
                tier=level,
                rule_ids=tuple(rule.rule_id for rule in rules),
                events=events,
                call=lambda level=level, rules=rules, chunks=chunks: _screen_pass(chunks, rules, global_context, screen_llm),
            )
            if not candidates:
                continue
            rules_by_id = {rule.rule_id: rule for rule in rules}
            candidate_rule_ids = tuple(sorted({candidate.rule_id for candidate in candidates}))
            issues = record_call(
                confirm_llm,
                stage="confirm",
                tier=level,
                rule_ids=candidate_rule_ids,
                events=events,
                call=lambda level=level, chunks=chunks, candidates=candidates, rules_by_id=rules_by_id: _confirm_pass(
                    candidates, chunks, rules_by_id, doc_id, level, global_context, document_text, rulebook, confirm_llm
                ),
            )
            all_issues.extend(issues)
        except Exception as error:  # noqa: BLE001 - one pass's failure shouldn't sink the whole review
            tier_errors.append(f"{level.value} 패스 검토 실패: {error}")

    return ReviewResult(
        doc_id=doc_id,
        global_context=global_context,
        issues=tuple(dedupe_issues(all_issues)),
        tier_errors=tuple(tier_errors),
        call_events=tuple(events),
    )
