from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

from planqa_review.dedupe import dedupe_issues
from planqa_review.document import Chunk, DocumentTree, parse_document, resolve_reported_level
from planqa_review.instrumentation import CallEvent, isolate_client, merge_usage, record_call
from planqa_review.llm.base import LLMClient
from planqa_review.pipeline import ReviewResult
from planqa_review.rulebook import RuleBook, RuleDef
from planqa_review.schema import Issue, Level
from planqa_review.structures.fewshot_bank import EXCEPTION_EXAMPLES, VIOLATION_EXAMPLES
from planqa_review.structures.fewshot_retrieval import _char_bigrams, _jaccard
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
    "consistent with what this document set out to do. Keep it to a few sentences. "
    "Separately, also list every distinct named term, concept, or entity the document "
    "introduces (product/feature names, policy names, roles, key numbers/limits) along with "
    "a short definition of what it means IN THIS document — this is a glossary, not a "
    "summary, so be exhaustive about terms even if the summary above already mentions some "
    "of them; a later reviewer will use this list to tell whether a term seen in one section "
    "is a genuinely new concept or just a reworded reference to one already defined here.\n"
    'Respond with JSON only: {"summary": "<compact Korean summary>", "terms": '
    '[{"term": "<term as it appears>", "definition": "<short definition>"}, ...]}'
)


def _extract_global_context(document_text: str, llm: LLMClient) -> tuple[str, str]:
    response = llm.complete_json(system=_GLOBAL_CONTEXT_SYSTEM, prompt=document_text)
    summary = response.get("summary") if isinstance(response, dict) else None
    raw_terms = response.get("terms") if isinstance(response, dict) else None
    glossary_lines = [
        f"- {item['term']}: {item['definition']}"
        for item in (raw_terms if isinstance(raw_terms, list) else [])
        if isinstance(item, dict) and item.get("term") and item.get("definition")
    ]
    return (
        summary.strip() if isinstance(summary, str) and summary.strip() else "",
        "\n".join(glossary_lines),
    )


_MI_VERIFY_SYSTEM = (
    "You are double-checking a document-review agent's claim that specific information is "
    "missing from a document — this exact failure mode (claiming X is missing when X is "
    "actually stated elsewhere in the document, because the agent's own review only saw one "
    "narrow chunk of it) has been observed live in production. You will be given the FULL "
    "document text and the agent's claim. Re-read the ENTIRE document carefully, not just "
    "whatever section the agent focused on, before deciding. This check has been over-"
    "correcting in practice, throwing out real findings — only answer actually_missing=false "
    "when you can point to the specific sentence elsewhere in the document that clearly states "
    "the missing information; if you're not confident, or the closest match is only loosely "
    "related, keep actually_missing=true.\n"
    'Respond with JSON only: {"actually_missing": <bool>, "reason": "<one short sentence>"}'
)

_AE_VERIFY_SYSTEM = (
    "You are double-checking a document-review agent's claim that a specific phrase is "
    "ambiguous/vague (모호한 표현) — this category is vulnerable to the same narrow-context "
    "failure mode as missing-information claims: a number, referent, or actor that looks "
    "unspecified in isolation may actually be defined or referenced elsewhere in the same "
    "document (e.g. a quantity defined in another section and referenced here per AE-01's own "
    "exception condition, a pronoun whose antecedent is clear from surrounding context, an "
    "actor implied by a system-wide policy stated elsewhere per AE-04's exception). You will "
    "be given the FULL document text and the agent's claim. Re-read the ENTIRE document "
    "carefully, not just whatever section the agent focused on, before deciding whether the "
    "flagged text is genuinely ambiguous in context. This check has been over-correcting in "
    "practice, throwing out real findings — only answer actually_ambiguous=false when you can "
    "point to the specific sentence elsewhere in the document that clearly resolves the "
    "ambiguity; if you're not confident, or the closest match is only loosely related, keep "
    "actually_ambiguous=true.\n"
    'Respond with JSON only: {"actually_ambiguous": <bool>, "reason": "<one short sentence>"}'
)


# MI(정보 누락)/AE(모호한 표현) 둘 다 Paragraph 단위로만 검토돼서(GA/LG/LF와 달리 문서 전체
# 시야가 없음), confirm이 "이 chunk엔 없다/모호하다"를 "문서 전체에 없다/모호하다"로 착각하는
# 오탐이 실사용 중 확인됨(planqa-agent PR #28/#55, 백엔드는 review_agent 벤더링 정책상 소스를
# 직접 못 고쳐서 qa_jobs.py에 우회로 추가했지만, 여긴 소스를 직접 소유하므로 정식으로 구현).
# MI/AE만 검증하는 이유: 이 둘만 "문서 전체를 봐야 판단 가능한 예외조건"을 갖고 있고(AE-01/
# AE-04의 "다른 곳에 정의/참조되면 예외"), 모든 카테고리에 걸면 비용/시간이 크게 늘어난다.
# 2026-08-21: 백엔드 qa_jobs.py에 남아있던 같은 검증(우회 구현)과 여기 것이 이중으로 돌면서
# 과탐지 방지가 의도보다 훨씬 공격적으로 동작하는 게 확인돼, 백엔드 쪽은 제거하고 여기 프롬프트는
# "명확한 근거를 못 찾으면 원래 판정을 유지하라"는 방향으로 완화했다(로직 구조는 그대로).
def _verify_mi_finding(document_text: str, issue: Issue, llm: LLMClient) -> bool:
    prompt = (
        f"Full document:\n{document_text}\n\n"
        f"Agent's claim — location: {issue.location!r}\n"
        f"  what's allegedly missing: {issue.description!r}\n"
        f"  rationale: {issue.rationale!r}\n"
        f"  quoted context: {issue.original_text!r}\n\n"
        "Return the JSON."
    )
    try:
        response = llm.complete_json(system=_MI_VERIFY_SYSTEM, prompt=prompt)
    except Exception:  # noqa: BLE001 - a verification failure must not block/hide the original finding
        return True
    if not isinstance(response, dict):
        return True
    return bool(response.get("actually_missing", True))


def _verify_ae_finding(document_text: str, issue: Issue, llm: LLMClient) -> bool:
    prompt = (
        f"Full document:\n{document_text}\n\n"
        f"Agent's claim — location: {issue.location!r}\n"
        f"  flagged text: {issue.original_text!r}\n"
        f"  what's allegedly ambiguous: {issue.description!r}\n"
        f"  rationale: {issue.rationale!r}\n\n"
        "Return the JSON."
    )
    try:
        response = llm.complete_json(system=_AE_VERIFY_SYSTEM, prompt=prompt)
    except Exception:  # noqa: BLE001 - a verification failure must not block/hide the original finding
        return True
    if not isinstance(response, dict):
        return True
    return bool(response.get("actually_ambiguous", True))


_FALSE_POSITIVE_VERIFIERS: dict[str, Callable[[str, Issue, LLMClient], bool]] = {
    "MI": _verify_mi_finding,
    "AE": _verify_ae_finding,
}


def _verify_false_positives(
    issues: tuple[Issue, ...], document_text: str, rulebook: RuleBook, llm: LLMClient, events: list[CallEvent]
) -> tuple[Issue, ...]:
    verified: list[Issue] = []
    for issue in issues:
        verify = _FALSE_POSITIVE_VERIFIERS.get(rulebook.category_of(issue.rule_id) or "")
        if verify is None:
            verified.append(issue)
            continue
        kept = record_call(
            llm,
            stage="verify_fp",
            tier=None,
            rule_ids=(issue.rule_id,),
            events=events,
            call=lambda issue=issue, verify=verify: verify(document_text, issue, llm),
        )
        if kept:
            verified.append(issue)
    return tuple(verified)


# 팀 프레이밍 규칙(Notion "Ver 1/Ver 2 - 프레임 유형 구분", 2026-08-06, 사용자가 Ver2 선택)의
# MI(정보 누락) 삽입 프레이밍 표를 그대로 구현 — 단어 누락은 그 문장으로, 문장 누락은 해당
# 소주제(Paragraph 청크) 전체로, 소주제/대주제 누락은 앞뒤 인접 소주제/대주제까지로 넓힌다.
# 프론트의 object 렌더러는 "주어진 텍스트로 박스 하나"만 그리므로, 별도 프론트 변경 없이도
# original_text를 넓히는 것만으로 화면에 바로 반영된다(발견5의 RD 두 번째 박스와 달리).
def _widen_along(chunks: tuple[Chunk, ...], location: str, fallback: str) -> str:
    index = next((i for i, chunk in enumerate(chunks) if chunk.location == location), None)
    if index is None:
        return fallback
    neighbors = [chunks[i].text for i in (index - 1, index, index + 1) if 0 <= i < len(chunks)]
    widened = "\n\n".join(text for text in neighbors if text)
    return widened or fallback


def _widen_mi_finding(issue: Issue, tree: DocumentTree) -> Issue:
    try:
        level = Level(issue.level)
    except ValueError:
        return issue
    original_text = issue.original_text or ""

    if level is Level.SENTENCE:
        # A sub-sentence fragment (a word/phrase the model could only point at, not a full
        # sentence) maps to Notion's "단어 누락 → 문장" row: narrow/promote up to the one
        # containing sentence and stop there, rather than the whole-paragraph widening below
        # (which is reserved for when an entire sentence, not just a word, is missing).
        containing_sentence = next(
            (s for s in tree.sentences if s.location == issue.location and original_text and original_text in s.text),
            None,
        )
        if containing_sentence is not None and len(original_text) < len(containing_sentence.text):
            return replace(issue, original_text=containing_sentence.text)
        paragraph = next((p for p in tree.paragraphs if p.location == issue.location), None)
        return replace(issue, original_text=paragraph.text) if paragraph is not None else issue

    if level is Level.PARAGRAPH:
        return replace(issue, original_text=_widen_along(tree.paragraphs, issue.location, original_text))

    if level in (Level.LOGICAL_UNIT, Level.DOCUMENT):
        return replace(issue, original_text=_widen_along(tree.logical_units, issue.location, original_text))

    return issue


def _widen_mi_findings(issues: tuple[Issue, ...], tree: DocumentTree, rulebook: RuleBook) -> tuple[Issue, ...]:
    return tuple(
        _widen_mi_finding(issue, tree) if rulebook.category_of(issue.rule_id) == "MI" else issue for issue in issues
    )


_RELATIONAL_CATEGORIES = frozenset({"LG", "LF", "GA"})
# RD(중복) findings are also inherently tied to a second location (the other copy of the
# duplicated content) — separate from _RELATIONAL_CATEGORIES because RD stays dispatched at
# Paragraph tier (unlike LG/LF/GA's Document-tier move) and doesn't get the "actively search
# the rest of the document" instruction that assumes that wider visibility; this set only
# gates whether related_location/related_original_text get filled in _confirm_pass.
_DUAL_LOCATION_CATEGORIES = _RELATIONAL_CATEGORIES | {"RD"}

# Three category mix-ups come up often enough in real usage to call out specifically — the
# rule text alone doesn't state each category's own one-line definition, and the surface
# symptom of all three confusions ("two sentences look different") is genuinely ambiguous
# without it. First two paragraphs ported verbatim from
# github.com/sunic5-planqa/planqa-agent PR #27 (issue #26, alpha-test usage); third
# (LF vs GA/LG) added 2026-08-12 from real user feedback (a coupon-count contradiction was
# flagged as LF when LF's definition is purely about flow/ordering, not truth).
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
    "referent exists, and reserve MI for things the document doesn't address at all.\n"
    "Separately again: LF (논리 흐름, flow) is purely about sentence/paragraph ordering and "
    "connectivity being awkward or hard to follow — it has nothing to do with whether the "
    "content itself is true or consistent. If two statements assert different or "
    "conflicting facts (e.g. one says 2 coupons, another says 1), that is a GA or LG "
    "problem, never LF, no matter how adjacent or disconnected the two statements read. "
    "Only flag LF when the actual claims agree and the problem is purely how they're "
    "sequenced or connected."
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
    "You are the precise, expensive second pass of a two-stage document QA pipeline. Every "
    "rule you might need is given upfront as its own defined text plus a few labeled "
    "examples of a real violation and a real excused (non-violation) case — use the "
    "examples only to calibrate borderline cases, the rule text is the authoritative "
    "definition. Each candidate below names its rule_id; look that rule up in the set given "
    "upfront rather than expecting its text repeated per candidate. Decide, precisely "
    "this time, whether each flagged span actually violates its rule — the screening pass "
    "over-flags on purpose, so most candidates should come back violated=false. If it does "
    "violate: quote the exact evidence sentence from the document (original_text), state "
    "what's wrong (description), explain why it breaks the rule (rationale), and write a "
    "concrete revised version of the text that would fix it (fix_direction) — phrase it as "
    "a suggestion, not a command. Write fix_direction in plain, jargon-free Korean a "
    "non-technical business reader can follow at a glance — no rule-code references, no "
    "review-jargon (e.g. don't say things like '정합성을 맞추세요' when you can just say what "
    "specific words to change) — keep it to one short, concrete sentence. Also apply the "
    "rule's own exception condition if given; "
    "set excused=true (with excuse_reason) when it applies. For the LG/LF/GA/RD categories "
    "specifically, a violation is by definition tied to a second location elsewhere in the "
    "document (the conflicting statement for LG/LF/GA, the other copy of the duplicated "
    "content for RD) — if you can identify that other location from what you were given, "
    "name it (related_location) using the same label style as the location you were given, "
    "AND quote its exact evidence sentence (related_original_text) the same way you quoted "
    "original_text; leave both null for every other category, or if no specific second "
    "location can be identified. For GA/LG/LF "
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
    "granularity, but the actual violation may not match that granularity exactly — say so "
    "with \"level\": if it spans a broader unit than the chunk, name the coarser level it "
    "really belongs at (\"Document\", \"Logical Unit\", \"Paragraph\", or \"Sentence\", "
    "coarsest to finest); if instead the problem is really confined to just one specific "
    "sentence within a larger chunk you were given, name \"Sentence\" — original_text "
    "should already be that exact sentence, so this is just labeling the scope you already "
    "quoted. Omit \"level\" (or repeat the chunk's own level) only when the finding's true "
    "scope genuinely matches the chunk you were given, neither broader nor narrower.\n"
    f"{_CATEGORY_BOUNDARY_NOTES} A candidate you're confirming was already assigned its "
    "rule_id by the screening pass, which can mis-tag exactly these confusions — if the "
    "candidate doesn't actually fit the rule you were given for that reason, set "
    "violated=false rather than confirming a violation of the wrong rule.\n"
    'Respond with JSON only: {"verdicts": [{"index": <int>, "violated": <bool>, '
    '"original_text": "<quote>", "description": "<what\'s wrong>", "rationale": '
    '"<why it violates the rule>", "fix_direction": "<suggested revision>", "excused": '
    '<bool>, "excuse_reason": "<string or null>", "related_location": "<string or null>", '
    '"related_original_text": "<string or null>", '
    '"level": "<Document|Logical Unit|Paragraph|Sentence, or null>"}, ...]}'
)


# document.py's chunk-splitting drops heading lines from chunk.text (they only end up in
# chunk.location, not the body) — but the prompt's chunk_block shows both together
# (f"[{i}] ({chunk.location})\n{chunk.text}"), so nothing ever checked that the model's
# quoted_text/original_text is actually IN the body rather than a lifted copy of the
# location label. That's the root cause of highlights landing on section headings instead
# of the actual evidence sentence (real user report, 2026-08-12) — this resolves any quoted
# span back onto a genuine substring of chunk.text before it ever becomes an Issue.
def _resolve_quoted_span(quoted: str, chunk_text: str) -> str:
    quoted = quoted.strip()
    if not quoted or quoted in chunk_text:
        return quoted
    normalized_chunk, index_map = _normalize_whitespace_with_map(chunk_text)
    normalized_quoted = " ".join(quoted.split())
    if normalized_quoted:
        pos = normalized_chunk.find(normalized_quoted)
        if pos != -1:
            start, end = index_map[pos], index_map[pos + len(normalized_quoted) - 1] + 1
            return chunk_text[start:end]
    return _nearest_substring(quoted, chunk_text)


def _normalize_whitespace_with_map(text: str) -> tuple[str, list[int]]:
    """Collapses each whitespace run to a single space, returning (normalized, index_map)
    where index_map[i] is text's original index for normalized[i] — lets a match found in
    the normalized string (whitespace/newline differences only) be sliced back out of the
    original text verbatim, instead of returning the whitespace-mangled normalized form."""
    chars: list[str] = []
    index_map: list[int] = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            chars.append(" ")
            index_map.append(i)
            while i < n and text[i].isspace():
                i += 1
        else:
            chars.append(text[i])
            index_map.append(i)
            i += 1
    return "".join(chars), index_map


def _sentence_spans(text: str) -> list[str]:
    spans = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    return spans if spans else ([text.strip()] if text.strip() else [])


# Character-bigram Jaccard, reused from fewshot_retrieval.py's dynamic-fewshot ranking —
# same reasoning applies here (Korean doesn't tokenize on whitespace, so word n-grams don't
# work, and this is a best-effort fallback, not a claim of finding THE correct span: a
# quote that was never really in this chunk (e.g. a lifted heading label) has no correct
# answer, only a closest one).
def _nearest_substring(quoted: str, chunk_text: str) -> str:
    spans = _sentence_spans(chunk_text)
    if not spans:
        return chunk_text.strip()
    quoted_bigrams = _char_bigrams(quoted)
    return max(spans, key=lambda span: _jaccard(quoted_bigrams, _char_bigrams(span)))


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
    # rule_block is identical for every call at this tier across all 20 documents in a run
    # (it's derived only from the rulebook + fewshot bank, never from document/chunk content)
    # — sent as cache_prefix instead of inlined in `prompt` so Anthropic's prompt caching can
    # bill it once instead of on every call (속도/비용 최적화 #1). Put first in the message
    # (see llm/anthropic.py) so the cache hit covers exactly this unchanging span.
    rule_block = "\n".join(_hybrid_block(rule) for rule in rules)
    chunk_block = "\n\n".join(f"[{i}] ({chunk.location})\n{chunk.text}" for i, chunk in enumerate(chunks))
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    cache_prefix = f"Rules to check (text + examples):\n{rule_block}\n\n"
    prompt = f"{context_block}Chunks:\n{chunk_block}\n\nReturn the candidates JSON."

    response = llm.complete_json(system=_SCREEN_HYBRID_SYSTEM, prompt=prompt, cache_prefix=cache_prefix)
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
                quoted_text=_resolve_quoted_span(str(item.get("quoted_text", "")), chunks[chunk_index].text),
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
    term_glossary: str,
    source_text: str,
    rulebook: RuleBook,
    llm: LLMClient,
) -> list[Issue]:
    # rule_block covers every rule at this tier (same set _screen_pass was given), not just
    # the ones candidates happen to reference — kept identical to _screen_pass's cache_prefix
    # on purpose so it's the same cached span reused across screen+confirm+every document in
    # a run, instead of a per-call filtered subset that would miss the cache every time
    # (속도/비용 최적화 #1+#2: this also replaces the old per-candidate `_hybrid_block(rule)`
    # repeat, which duplicated the same rule's full text+examples once per candidate sharing
    # that rule_id).
    rule_block = "\n".join(_hybrid_block(rule) for rule in rules_by_id.values())
    cache_prefix = f"Rules to check (text + examples):\n{rule_block}\n\n"
    blocks = []
    for i, candidate in enumerate(candidates):
        chunk = chunks[candidate.chunk_index]
        blocks.append(
            f"[{i}] rule_id: {candidate.rule_id}\n"
            f"  location: {chunk.location}\n"
            f"  full unit text: {chunk.text!r}\n"
            f"  screened span: {candidate.quoted_text!r} (screening reason: {candidate.reason})"
        )
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    # 발견7: TC(용어 일관성)는 앞서 이 문단 이전에 쓰인 용어를 알아야 판정 가능한데,
    # global_context는 서술형 요약이라 개별 용어가 대부분 빠져 있다(용어집이 아님) — TC
    # candidate가 있을 때만 명시적 용어 목록을 추가로 준다(다른 카테고리엔 불필요한 토큰).
    if term_glossary and any(rules_by_id[c.rule_id].category == "TC" for c in candidates):
        context_block += (
            f"Known terms/definitions catalogued so far (not exhaustive — absence here does "
            f"NOT mean a term is new, only that it wasn't catalogued):\n{term_glossary}\n\n"
        )
    prompt = f"{context_block}{chr(10).join(blocks)}\n\nReturn the verdicts JSON."

    response = llm.complete_json(system=_CONFIRM_HYBRID_SYSTEM, prompt=prompt, cache_prefix=cache_prefix)
    raw_verdicts = response.get("verdicts", []) if isinstance(response, dict) else []
    by_index = {item["index"]: item for item in raw_verdicts if isinstance(item, dict) and "index" in item}

    issues: list[Issue] = []
    for i, candidate in enumerate(candidates):
        values = by_index.get(i)
        if values is None or not values.get("violated"):
            continue
        chunk = chunks[candidate.chunk_index]
        original_text = _resolve_quoted_span(str(values.get("original_text") or candidate.quoted_text), chunk.text)
        excused = bool(values.get("excused")) or is_reference_excused_by_rule(
            candidate.rule_id, rulebook, original_text, doc_id, level, chunk.location, source_text
        )
        if excused:
            continue
        related_location = None
        related_original_text = None
        if rules_by_id[candidate.rule_id].category in _DUAL_LOCATION_CATEGORIES:
            raw_related = values.get("related_location")
            related_location = str(raw_related).strip() or None if raw_related else None
            raw_related_text = values.get("related_original_text")
            related_original_text = str(raw_related_text).strip() or None if raw_related_text else None
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
                related_original_text=related_original_text,
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
    term_glossary: str,
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
                term_glossary,
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
        global_context, term_glossary = record_call(
            confirm_llm,
            stage="context",
            tier=None,
            rule_ids=(),
            events=events,
            call=lambda: _extract_global_context(document_text, confirm_llm),
        )
    except Exception as error:  # noqa: BLE001 - one pass's failure shouldn't sink the whole review
        global_context = ""
        term_glossary = ""
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
            level, rules, chunks, doc_id, global_context, term_glossary, document_text, rulebook, screen_llm, confirm_llm
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
                    term_glossary,
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

    deduped_issues = tuple(dedupe_issues(all_issues))
    try:
        verified_issues = _verify_false_positives(deduped_issues, document_text, rulebook, confirm_llm, events)
    except Exception as error:  # noqa: BLE001 - a verification-stage failure must not drop every finding
        verified_issues = deduped_issues
        tier_errors.append(f"MI/AE 오탐 재검증 실패: {error}")

    try:
        final_issues = _widen_mi_findings(verified_issues, tree, rulebook)
    except Exception as error:  # noqa: BLE001 - a framing-widening failure must not drop every finding
        final_issues = verified_issues
        tier_errors.append(f"MI 프레이밍 확장 실패: {error}")

    return ReviewResult(
        doc_id=doc_id,
        global_context=global_context,
        issues=final_issues,
        tier_errors=tuple(tier_errors),
        call_events=tuple(events),
    )
