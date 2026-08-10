from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from planqa_review.dedupe import dedupe_issues
from planqa_review.document import Chunk, parse_document, resolve_reported_level
from planqa_review.instrumentation import CallEvent, isolate_client, merge_usage, record_call
from planqa_review.llm.base import LLMClient
from planqa_review.pipeline import ReviewResult
from planqa_schemas.rulebook import RuleBook, RuleDef
from planqa_schemas.schema import Issue, Level
from planqa_review.structures.fewshot_bank import EXCEPTION_EXAMPLES, VIOLATION_EXAMPLES
from planqa_review.tiers import ABSENCE_CHECK_RULE_IDS
from planqa_review.verifier import is_reference_excused_by_rule

# bundled_screen_hybrid — bundled_screen(룰텍스트만)과 bundled_screen_fewshot(퓨샷만) 사이의
# 세 번째 콘텐츠 조합. 콜통합 버전이라 카테고리별로 안 쪼개고 패스당 screen 1콜+confirm
# 1콜에 룰텍스트+퓨샷 예시를 함께 담는다.
#
# GA/LG/LF(관계형 카테고리, _RELATIONAL_CATEGORIES 참고)는 문서 전체를 한 번에 보는 pass로
# 간다(2026-08-10 보완) — 이 세 카테고리는 정의상 서로 다른 두 위치를 비교해야 하는데,
# LG-02~05/LF 전체가 원래 문단 단위로 쪼개져 있어서 애초에 먼 섹션끼리 비교할 시야가 없었다
# (실제로 DOC-001의 LG-05, DOC-012의 GA-01을 완전히 놓친 사례로 확인됨 — golden도 둘 다
# Level=Document로 라벨링돼 있어 이 배치가 golden 기대와도 맞음).

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

# The two paragraphs below (GA-vs-TC, TC-vs-MI) address real category-mix-ups seen in
# alpha-test usage (github.com/sunic5-planqa/planqa-agent issue #26) — the rule text alone
# doesn't state each category's own one-line definition, and the surface symptom of both
# confusions ("two sentences look different") is genuinely ambiguous without it.
_CATEGORY_BOUNDARY_NOTES = (
    "Two category mix-ups come up often enough to call out specifically. GA (상위 목표와 "
    "세부 내용의 정합성) is about two statements making genuinely DIFFERENT or CONFLICTING "
    "claims about what happens, is true, or is allowed — e.g. one statement says a "
    "combination is permitted, another says it isn't. TC (용어 및 단어의 일관성) is about "
    "the SAME claim/fact being restated with inconsistent wording or naming while both "
    "sides still agree on what's actually true. If two statements disagree on the facts, "
    "that's GA, never TC, regardless of how differently worded they are — TC only fires "
    "when the wording differs but the underlying claim doesn't.\n"
    "Separately: before flagging something as MI (정보 누락, missing information) because a "
    "term or concept seems undefined, consider whether it might just be a reworded "
    "reference to something already established elsewhere in the document (a synonym, an "
    "abbreviation, a paraphrase) — that's TC (inconsistent naming for something that does "
    "exist), not MI. You're only given a short document-context summary here, not a full "
    "glossary of every term used so far, so a term's absence from that summary is not "
    "evidence it's genuinely new; lean toward TC over MI whenever a plausible earlier "
    "referent exists, and reserve MI for things the document doesn't address at all."
)

_SCREEN_HYBRID_SYSTEM = (
    "You are the cheap, wide first pass of a two-stage document QA pipeline (screen now, "
    "a stronger model verifies later) — favor recall over precision, flag anything even "
    "mildly suspicious. Each rule below is given as its own defined text plus a few labeled "
    "examples of a real violation — use the examples only to calibrate borderline cases, "
    "the rule text is the authoritative definition. For each numbered chunk below, check it "
    "against the numbered rules (which may span several review categories at once) and list "
    "every span that might violate one, however uncertain. If any of the rules below belong "
    "to the GA/LG/LF categories (each is by definition a conflict between two separate "
    "statements elsewhere in the input, never a single-point issue), don't just scan "
    "linearly for those — first mentally collect every stated goal/KPI/policy sentence and, "
    "separately, every stated constraint/capability/schedule sentence across the whole "
    "input, then check each pairing for a genuine conflict before flagging one.\n"
    f"{_CATEGORY_BOUNDARY_NOTES}\n"
    'Respond with JSON only: {"candidates": [{"chunk_index": <int>, "rule_id": "<id>", '
    '"quoted_text": "<exact span from the chunk>", "reason": "<one short line>"}, ...]}'
)

_CONFIRM_HYBRID_SYSTEM = (
    "You are the precise, expensive second pass of a two-stage document QA pipeline. Each "
    "rule below is given as its own defined text plus a few labeled examples of a real "
    "violation and a real excused (non-violation) case — use the examples only to calibrate "
    "borderline cases, the rule text is the authoritative definition. Decide, precisely "
    "this time, whether each flagged span actually violates its rule — the screening pass "
    "over-flags on purpose, so most candidates should come back violated=false. If it does "
    "violate: quote the exact evidence sentence from the document (original_text), state "
    "what's wrong (description), explain why it breaks the rule (rationale), and write a "
    "concrete revised version of the text that would fix it (fix_direction) — phrase it as "
    "a suggestion, not a command. Also apply the rule's own exception condition if given; "
    "set excused=true (with excuse_reason) when it applies. For the LG/LF/GA categories "
    "specifically, a violation is by definition a relationship error between two locations "
    "in the document — also name the OTHER location involved (related_location), using the "
    "same label style as the location you were given; leave related_location null for "
    "every other category, or if no specific second location can be identified. For GA/LG/LF "
    "specifically, before confirming a candidate, actively search the rest of the document "
    "context you were given for the specific other statement it conflicts with — don't rely "
    "on the screening pass's guess alone; if you can't locate a concrete conflicting "
    "statement yourself, don't confirm it. When claiming two locations conflict, first "
    "confirm they actually assert different facts — "
    "restating the same fact in different words or at different levels of detail is NOT a "
    "conflict; only flag a genuine logical contradiction. If several of the candidates "
    "above (even ones flagged under different rule_ids) are really the same underlying "
    "problem, confirm violated=true on only ONE of them and set the rest to violated=false "
    "— don't confirm every repeat. Each candidate was screened at one specific chunk's "
    "granularity, but if the violation actually spans a broader unit than that chunk, say "
    "so with \"level\": name the coarser level it really belongs at (\"Document\", "
    "\"Logical Unit\", \"Paragraph\", or \"Sentence\", coarsest to finest) instead of "
    "leaving it at the chunk's own granularity — omit it (or repeat the chunk's own level) "
    "when the finding genuinely doesn't extend beyond the one chunk.\n"
    f"{_CATEGORY_BOUNDARY_NOTES} A candidate you're confirming was already assigned its "
    "rule_id by the screening pass, which can mis-tag exactly these two confusions — if the "
    "candidate doesn't actually fit the rule you were given for that reason, set "
    "violated=false rather than confirming a violation of the wrong rule.\n"
    'Respond with JSON only: {"verdicts": [{"index": <int>, "violated": <bool>, '
    '"original_text": "<quote>", "description": "<what\'s wrong>", "rationale": '
    '"<why it violates the rule>", "fix_direction": "<suggested revision>", "excused": '
    '<bool>, "excuse_reason": "<string or null>", "related_location": "<string or null>", '
    '"level": "<Document|Logical Unit|Paragraph|Sentence, or null>"}, ...]}'
)


def _hybrid_block(rule: RuleDef) -> str:
    lines = [f"  {rule.rule_id} ({rule.category_label}): {rule.text}", f"    exception condition: {rule.exception_text or '없음'}"]
    for example in VIOLATION_EXAMPLES.get(rule.rule_id, []):
        lines.append(f"    - VIOLATION example: {example.original_text!r} — {example.rationale}")
    for exception_example in EXCEPTION_EXAMPLES.get(rule.rule_id, []):
        lines.append(
            f"    - EXCUSED example ({exception_example.exception_condition}): "
            f"{exception_example.original_text!r} — {exception_example.rationale}"
        )
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _Candidate:
    chunk_index: int
    rule_id: str
    quoted_text: str
    reason: str


def _screen_pass(chunks: list[Chunk], rules: list[RuleDef], global_context: str, llm: LLMClient) -> list[_Candidate]:
    rule_block = "\n".join(_hybrid_block(rule) for rule in rules)
    chunk_block = "\n\n".join(f"[{i}] ({chunk.location})\n{chunk.text}" for i, chunk in enumerate(chunks))
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    prompt = f"{context_block}Rules to check (text + examples):\n{rule_block}\n\nChunks:\n{chunk_block}\n\nReturn the candidates JSON."

    response = llm.complete_json(system=_SCREEN_HYBRID_SYSTEM, prompt=prompt)
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
            f"[{i}] rule:\n{_hybrid_block(rule)}\n"
            f"  location: {chunk.location}\n"
            f"  full unit text: {chunk.text!r}\n"
            f"  screened span: {candidate.quoted_text!r} (screening reason: {candidate.reason})"
        )
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    prompt = f"{context_block}{chr(10).join(blocks)}\n\nReturn the verdicts JSON."

    response = llm.complete_json(system=_CONFIRM_HYBRID_SYSTEM, prompt=prompt)
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
        if rule.category in _RELATIONAL_CATEGORIES or rule.rule_id in ABSENCE_CHECK_RULE_IDS:
            document_rules.append(rule)
        else:
            paragraph_rules.append(rule)
    return paragraph_rules, document_rules


# bundled_screen_hybrid — bundled_screen/bundled_screen_fewshot과 판정 방식·청킹은
# 동일(2단계, 문단형)하지만, screen/confirm 양쪽 프롬프트에 룰 텍스트와 fewshot 예시를
# 함께 준다.
def _run_pass(
    level: Level,
    rules: list[RuleDef],
    chunks: list[Chunk],
    doc_id: str,
    global_context: str,
    document_text: str,
    rulebook: RuleBook,
    screen_llm: LLMClient,
    confirm_llm: LLMClient,
) -> tuple[list[Issue], list[CallEvent], str | None]:
    # The passed-in screen_llm/confirm_llm are the shared originals — isolate_client() below
    # gives this pass its own private copies (record_call's usage-diffing races if two
    # passes share one client's usage list). key=level lets test doubles route scripted
    # responses by which pass is asking instead of by call order, which real backends don't
    # need (they ignore key) but is required for tests since call order across concurrently-
    # dispatched passes isn't deterministic. merge_usage folds each copy's calls back onto
    # the shared original client once this pass is done, so cli.py's run-stats (which reads
    # screen_llm.usage/confirm_llm.usage on the *original* objects directly) still sees
    # every call.
    events: list[CallEvent] = []
    # Isolation itself happens inside the try (not before it) — if isolate_client() ever
    # raises, this pass must still degrade into a tier_error like every other failure mode
    # here, not crash review_document() entirely.
    isolated_screen: LLMClient | None = None
    isolated_confirm: LLMClient | None = None
    try:
        isolated_screen = isolate_client(screen_llm, key=level)
        isolated_confirm = isolate_client(confirm_llm, key=level)
        candidates = record_call(
            isolated_screen,
            stage="screen",
            tier=level,
            rule_ids=tuple(rule.rule_id for rule in rules),
            events=events,
            call=lambda: _screen_pass(chunks, rules, global_context, isolated_screen),
        )
        if not candidates:
            return [], events, None
        rules_by_id = {rule.rule_id: rule for rule in rules}
        candidate_rule_ids = tuple(sorted({candidate.rule_id for candidate in candidates}))
        issues = record_call(
            isolated_confirm,
            stage="confirm",
            tier=level,
            rule_ids=candidate_rule_ids,
            events=events,
            call=lambda: _confirm_pass(
                candidates,
                chunks,
                rules_by_id,
                doc_id,
                level,
                global_context,
                document_text,
                rulebook,
                isolated_confirm,
            ),
        )
        return issues, events, None
    except Exception as error:  # noqa: BLE001 - one pass's failure shouldn't sink the whole review
        return [], events, f"{level.value} 패스 검토 실패: {error}"
    finally:
        if isolated_screen is not None:
            merge_usage(screen_llm, isolated_screen)
        if isolated_confirm is not None:
            merge_usage(confirm_llm, isolated_confirm)


def review_document(
    doc_id: str,
    document_text: str,
    rulebook: RuleBook,
    screen_llm: LLMClient,
    confirm_llm: LLMClient,
) -> ReviewResult:
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
    active_passes = [(level, rules, chunks) for level, rules, chunks in passes if chunks and rules]

    # Paragraph and Document passes only depend on the already-computed global_context, not
    # on each other, so they run concurrently instead of sequentially doubling the wall
    # time. See _run_pass for why each pass needs its own isolated client copy. When only
    # one pass is actually active (the other tier's rules/chunks were empty), there's
    # nothing to run concurrently with, so call it directly — no point paying thread-pool
    # setup/teardown for a single sequential call.
    if len(active_passes) == 1:
        level, rules, chunks = active_passes[0]
        issues, pass_events, error = _run_pass(
            level, rules, chunks, doc_id, global_context, document_text, rulebook, screen_llm, confirm_llm
        )
        all_issues.extend(issues)
        events.extend(pass_events)
        if error:
            tier_errors.append(error)
    elif active_passes:
        with ThreadPoolExecutor(max_workers=len(active_passes)) as pool:
            futures = {
                level: pool.submit(
                    _run_pass,
                    level,
                    rules,
                    chunks,
                    doc_id,
                    global_context,
                    document_text,
                    rulebook,
                    screen_llm,
                    confirm_llm,
                )
                for level, rules, chunks in active_passes
            }
            for level, future in futures.items():
                issues, pass_events, error = future.result()
                all_issues.extend(issues)
                events.extend(pass_events)
                if error:
                    tier_errors.append(error)

    return ReviewResult(
        doc_id=doc_id,
        global_context=global_context,
        issues=tuple(dedupe_issues(all_issues)),
        tier_errors=tuple(tier_errors),
        call_events=tuple(events),
    )
