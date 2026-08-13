from __future__ import annotations

from planqa_review.dedupe import dedupe_issues
from planqa_review.document import Chunk, parse_document, resolve_reported_level
from planqa_review.instrumentation import CallEvent, record_call
from planqa_review.llm.base import LLMClient
from planqa_review.pipeline import ReviewResult
from planqa_review.rulebook import RuleBook, RuleDef
from planqa_review.schema import Issue, Level
from planqa_review.tiers import ABSENCE_CHECK_RULE_IDS
from planqa_review.verifier import is_reference_excused_by_rule

# bundled_verdict — ③+④ 콜통합×룰전부 셀. paragraph_verdict(②의 청킹 승자)와 판정 방식·
# 청킹은 동일하게 유지하되, 카테고리별로 독립 콜을 쪼개지 않고 한 패스(문단/문서)에 배정된
# 모든 카테고리·룰을 한 콜에 묶어서 묻는다 — proposal0.py의 콜통합 방식을 문단형 청킹에
# 적용한 버전.

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

_DIRECT_SYSTEM = (
    "You are a single-pass document QA reviewer — there is no separate cheap screening "
    "step before you, so decide directly whether each rule is actually violated (don't "
    "over-flag on the assumption something else will double-check). For each numbered "
    "chunk below, check it against the numbered rules (which may span several review "
    "categories at once). If a rule is violated: quote the exact evidence sentence from "
    "the chunk (original_text), state what's wrong (description), explain why it breaks "
    "the rule (rationale), and write a concrete revised version of the text that would fix "
    "it (fix_direction) — phrase it as a suggestion, not a command. Also apply the rule's "
    "own exception condition if given; set excused=true (with excuse_reason) when it "
    "applies. For the LG/LF/GA categories specifically, a violation is by definition a "
    "relationship error between two locations in the document — also name the OTHER "
    "location involved (related_location), using the same label style as the location you "
    "were given; leave related_location null for every other category, or if no specific "
    "second location can be identified. When claiming two locations conflict, first "
    "confirm they actually assert different facts — restating the same fact in different "
    "words or at different levels of detail is NOT a conflict; only flag a genuine "
    "logical contradiction. If the same underlying problem repeats across several of the "
    "numbered chunks below, or would technically match more than one rule listed here, "
    "report it ONCE only — pick the single chunk_index and rule_id that best represents "
    "it. You were given chunks at one specific granularity, but if the violation actually "
    "spans a broader unit than the single chunk you're citing (e.g. the same defect "
    "repeats across every chunk under one heading), say so with \"level\": name the "
    "coarser level it really belongs at (\"Document\", \"Logical Unit\", \"Paragraph\", or "
    "\"Sentence\", coarsest to finest) instead of leaving it at the chunk's own "
    "granularity — omit it (or repeat the chunk's own level) when the finding genuinely "
    "doesn't extend beyond the one chunk you cited. Only report genuine violations.\n"
    'Respond with JSON only: {"violations": [{"chunk_index": <int>, "rule_id": "<id>", '
    '"original_text": "<quote>", "description": "<what\'s wrong>", "rationale": '
    '"<why it violates the rule>", "fix_direction": "<suggested revision>", "excused": '
    '<bool>, "excuse_reason": "<string or null>", "related_location": "<string or null>", '
    '"level": "<Document|Logical Unit|Paragraph|Sentence, or null>"}, ...]}'
)


def _rule_block(rule: RuleDef) -> str:
    return f"{rule.rule_id} ({rule.category_label}): {rule.text}\n  exception condition: {rule.exception_text or '없음'}"


def _build_prompt(chunks: list[Chunk], rules: list[RuleDef], global_context: str) -> str:
    rule_block = "\n".join(_rule_block(rule) for rule in rules)
    chunk_block = "\n\n".join(f"[{i}] ({chunk.location})\n{chunk.text}" for i, chunk in enumerate(chunks))
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    return f"{context_block}Rules to check:\n{rule_block}\n\nChunks:\n{chunk_block}\n\nReturn the violations JSON."


def _review_pass(
    chunks: list[Chunk],
    rules: list[RuleDef],
    level: Level,
    global_context: str,
    doc_id: str,
    source_text: str,
    rulebook: RuleBook,
    llm: LLMClient,
) -> list[Issue]:
    response = llm.complete_json(system=_DIRECT_SYSTEM, prompt=_build_prompt(chunks, rules, global_context))
    raw_violations = response.get("violations", []) if isinstance(response, dict) else []
    rules_by_id = {rule.rule_id: rule for rule in rules}

    issues: list[Issue] = []
    for item in raw_violations:
        if not isinstance(item, dict):
            continue
        chunk_index, rule_id = item.get("chunk_index"), item.get("rule_id")
        if not (isinstance(chunk_index, int) and 0 <= chunk_index < len(chunks)) or rule_id not in rules_by_id:
            continue
        chunk = chunks[chunk_index]
        original_text = str(item.get("original_text") or "").strip()
        excused = bool(item.get("excused")) or is_reference_excused_by_rule(
            rule_id, rulebook, original_text, doc_id, level, chunk.location, source_text
        )
        if excused:
            continue
        related_location = None
        if rules_by_id[rule_id].category in _RELATIONAL_CATEGORIES:
            raw_related = item.get("related_location")
            related_location = str(raw_related).strip() or None if raw_related else None
        reported_level, reported_location = resolve_reported_level(level, chunk.location, item.get("level"))
        issues.append(
            Issue(
                doc_id=doc_id,
                level=reported_level.value,
                rule_id=rule_id,
                location=reported_location,
                description=str(item.get("description") or "").strip(),
                source="review_agent",
                original_text=original_text or None,
                rationale=str(item.get("rationale") or "").strip() or None,
                fix_direction=str(item.get("fix_direction") or "").strip() or None,
                related_location=related_location,
            )
        )
    return issues


def _paragraph_and_document_rules(rulebook: RuleBook) -> tuple[list[RuleDef], list[RuleDef]]:
    """Same 문단형 split as paragraph_verdict.py — GA and §1's 부재 확인형 rules go to the
    whole-document pass, everything else is checked per-paragraph. Unlike paragraph_verdict
    this stays a flat list (no per-category grouping), since 콜통합 bundles every category
    assigned to a pass into one call."""
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
    """bundled_verdict — paragraph_verdict와 청킹·판정 방식은 동일(1단계, 문단형)하지만,
    카테고리별로 콜을 쪼개지 않고 한 패스(문단/문서)에 배정된 모든 룰을 한 콜에 묶어서
    묻는다. `screen_llm`은 안 씀 — 다른 구조들과 동일한 `ReviewFn` 시그니처를 맞추기 위해
    인자만 유지."""
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
            issues = record_call(
                confirm_llm,
                stage="single_pass",
                tier=level,
                rule_ids=tuple(rule.rule_id for rule in rules),
                events=events,
                call=lambda level=level, rules=rules, chunks=chunks: _review_pass(
                    chunks, rules, level, global_context, doc_id, document_text, rulebook, confirm_llm
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
