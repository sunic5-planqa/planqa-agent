from __future__ import annotations

from typing import Any

from conftest import ScriptedLLM

from planqa_review.rulebook import parse_rulebook
from planqa_review.schema import Issue, Level
from planqa_review.document import parse_document
from planqa_review.structures.bundled_screen_hybrid import (
    _extract_global_context,
    _resolve_quoted_span,
    _verify_ae_finding,
    _verify_mi_finding,
    _widen_mi_finding,
    review_document,
)

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n\n## 2. 배경\n\n두번째 문단입니다.\n"

_EMPTY_CANDIDATES = {"candidates": []}


class _StubVerifyLLM:
    """A minimal LLMClient double for unit-testing _verify_mi_finding/_verify_ae_finding in
    isolation, without needing a full ScriptedLLM response queue — mirrors the backend's
    _StubVerifyLLM in test_api_qa_jobs.py (PR #28/#55)."""

    def __init__(self, response: Any | None, *, raise_error: bool = False) -> None:
        self._response = response
        self._raise_error = raise_error

    def complete_json(self, *, system: str, prompt: str) -> Any:
        if self._raise_error:
            raise RuntimeError("boom")
        return self._response


def _mi_issue(**overrides) -> Issue:
    defaults = dict(
        doc_id="DOC-TEST",
        level="Paragraph",
        rule_id="MI-01",
        location="8. 런칭 계획",
        description="런칭일/QA 기간이 구체적으로 명시되지 않음",
        original_text="목표 런칭일: - QA 기간: ~",
        rationale="시간 조건이 정의되지 않음",
    )
    defaults.update(overrides)
    return Issue(**defaults)


def _ae_issue(**overrides) -> Issue:
    defaults = dict(
        doc_id="DOC-TEST",
        level="Paragraph",
        rule_id="AE-03",
        location="4. 처리 정책",
        description="판단 기준이 불명확함",
        original_text="적당한 기간 내에 처리한다",
        rationale="구체적 기준이 없음",
    )
    defaults.update(overrides)
    return Issue(**defaults)


def test_verify_mi_finding_keeps_the_issue_when_verification_confirms_it_is_missing():
    llm = _StubVerifyLLM({"actually_missing": True, "reason": "정말 없음"})
    assert _verify_mi_finding("문서 전문", _mi_issue(), llm) is True


def test_verify_mi_finding_drops_the_issue_when_verification_finds_it_present():
    llm = _StubVerifyLLM({"actually_missing": False, "reason": "8장에 날짜가 있음"})
    assert _verify_mi_finding("문서 전문", _mi_issue(), llm) is False


def test_verify_mi_finding_fails_safe_by_keeping_the_issue_on_llm_error():
    llm = _StubVerifyLLM(None, raise_error=True)
    assert _verify_mi_finding("문서 전문", _mi_issue(), llm) is True


def test_verify_mi_finding_fails_safe_on_malformed_response():
    llm = _StubVerifyLLM("not a dict")
    assert _verify_mi_finding("문서 전문", _mi_issue(), llm) is True


def test_verify_ae_finding_keeps_the_issue_when_verification_confirms_it_is_ambiguous():
    llm = _StubVerifyLLM({"actually_ambiguous": True, "reason": "정말 모호함"})
    assert _verify_ae_finding("문서 전문", _ae_issue(), llm) is True


def test_verify_ae_finding_drops_the_issue_when_verification_finds_it_defined_elsewhere():
    llm = _StubVerifyLLM({"actually_ambiguous": False, "reason": "3장에 기준이 정의돼 있음"})
    assert _verify_ae_finding("문서 전문", _ae_issue(), llm) is False


def test_verify_ae_finding_fails_safe_by_keeping_the_issue_on_llm_error():
    llm = _StubVerifyLLM(None, raise_error=True)
    assert _verify_ae_finding("문서 전문", _ae_issue(), llm) is True


def test_verify_ae_finding_fails_safe_on_malformed_response():
    llm = _StubVerifyLLM("not a dict")
    assert _verify_ae_finding("문서 전문", _ae_issue(), llm) is True


def test_review_document_gives_both_rule_text_and_fewshot_examples_in_both_stages(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        keyed_responses={
            Level.PARAGRAPH: [
                {
                    "verdicts": [
                        {
                            "index": 0,
                            "violated": True,
                            "original_text": "간단한 목적 설명입니다.",
                            "description": "d",
                            "fix_direction": "f",
                            "excused": False,
                        }
                    ]
                }
            ],
        },
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [
                {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "간단한 목적 설명입니다.", "reason": "r"}]}
            ],
            Level.DOCUMENT: [_EMPTY_CANDIDATES],
        }
    )

    review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    mi01_rule = rulebook.rules["MI-01"]
    paragraph_screen = screen_llm.isolated[Level.PARAGRAPH]
    paragraph_confirm = confirm_llm.isolated[Level.PARAGRAPH]
    assert mi01_rule.text in paragraph_screen.calls[0]["prompt"]
    assert mi01_rule.text in paragraph_confirm.calls[0]["prompt"]


def test_review_document_two_passes_end_to_end(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": "이 문서는 홈 화면의 목적을 설명한다."}],
        keyed_responses={
            Level.PARAGRAPH: [
                {
                    "verdicts": [
                        {
                            "index": 0,
                            "violated": True,
                            "original_text": "간단한 목적 설명입니다.",
                            "description": "목적이 구체적이지 않음",
                            "fix_direction": "목적을 구체화할 것",
                            "excused": False,
                        }
                    ]
                }
            ],
        },
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [
                {
                    "candidates": [
                        {"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "간단한 목적 설명입니다.", "reason": "불명확"}
                    ]
                }
            ],
            Level.DOCUMENT: [_EMPTY_CANDIDATES],
        }
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert result.global_context == "이 문서는 홈 화면의 목적을 설명한다."
    [issue] = result.issues
    assert issue.rule_id == "MI-01"
    assert issue.level == "Paragraph"


def test_review_document_honors_a_sentence_level_demotion_within_a_paragraph_chunk(rulebook_path):
    # The AE-03/DOC-003 golden case (level=Sentence, location kept at the paragraph's own
    # label) that resolve_reported_level's old promotion-only rule could never produce —
    # confirm's "level": "Sentence" on a Paragraph-tier chunk must now come through as-is.
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        keyed_responses={
            Level.PARAGRAPH: [
                {
                    "verdicts": [
                        {
                            "index": 0,
                            "violated": True,
                            "original_text": "간단한 목적 설명입니다.",
                            "description": "d",
                            "fix_direction": "f",
                            "excused": False,
                            "level": "Sentence",
                        }
                    ]
                }
            ],
        },
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [
                {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "간단한 목적 설명입니다.", "reason": "r"}]}
            ],
            Level.DOCUMENT: [_EMPTY_CANDIDATES],
        }
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    [issue] = result.issues
    assert issue.level == "Sentence"
    assert issue.location == "1. 목적"


def test_review_document_respects_excused_flag(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        keyed_responses={
            Level.PARAGRAPH: [
                {
                    "verdicts": [
                        {
                            "index": 0,
                            "violated": True,
                            "original_text": "x",
                            "description": "d",
                            "fix_direction": "f",
                            "excused": True,
                            "excuse_reason": "예외 적용",
                        }
                    ]
                }
            ],
        },
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [
                {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "x", "reason": "r"}]}
            ],
            Level.DOCUMENT: [_EMPTY_CANDIDATES],
        }
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)
    assert result.issues == ()


def test_review_document_dispatches_ga_at_document_level_only(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        keyed_responses={
            Level.DOCUMENT: [
                {
                    "verdicts": [
                        {
                            "index": 0,
                            "violated": True,
                            "original_text": "x",
                            "description": "d",
                            "fix_direction": "f",
                            "excused": False,
                        }
                    ]
                }
            ],
        },
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [_EMPTY_CANDIDATES],
            Level.DOCUMENT: [
                {"candidates": [{"chunk_index": 0, "rule_id": "GA-01", "quoted_text": "x", "reason": "r"}]}
            ],
        }
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    [issue] = result.issues
    assert issue.rule_id == "GA-01"
    assert issue.level == "Document"


def test_review_document_dispatches_lg_and_lf_at_document_level_too(rulebook_path):
    # LG/LF are relational categories (_RELATIONAL_CATEGORIES) just like GA — they're
    # defined as conflicts between two distant locations, so (2026-08-10 보완) they need
    # the same whole-document visibility GA already had, not a per-paragraph chunk.
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        keyed_responses={
            Level.DOCUMENT: [
                {
                    "verdicts": [
                        {
                            "index": 0,
                            "violated": True,
                            "original_text": "x",
                            "description": "d",
                            "fix_direction": "f",
                            "excused": False,
                            "related_location": "다른 위치",
                            "related_original_text": "다른 위치의 실제 문장",
                        }
                    ]
                }
            ],
        },
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [_EMPTY_CANDIDATES],
            Level.DOCUMENT: [
                {"candidates": [{"chunk_index": 0, "rule_id": "LG-02", "quoted_text": "x", "reason": "r"}]}
            ],
        }
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    [issue] = result.issues
    assert issue.rule_id == "LG-02"
    assert issue.level == "Document"
    assert issue.related_location == "다른 위치"
    assert issue.related_original_text == "다른 위치의 실제 문장"


def test_review_document_leaves_related_original_text_null_for_non_relational_categories(rulebook_path):
    # PR #30 gates related_original_text the same way related_location already is —
    # even if a confirm response somehow includes it for a non-relational category
    # (e.g. MI), it must not leak through onto the Issue.
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        keyed_responses={
            Level.PARAGRAPH: [
                {
                    "verdicts": [
                        {
                            "index": 0,
                            "violated": True,
                            "original_text": "간단한 목적 설명입니다.",
                            "description": "d",
                            "fix_direction": "f",
                            "excused": False,
                            "related_location": "다른 위치",
                            "related_original_text": "다른 위치의 실제 문장",
                        }
                    ]
                }
            ],
        },
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [
                {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "간단한 목적 설명입니다.", "reason": "r"}]}
            ],
            Level.DOCUMENT: [_EMPTY_CANDIDATES],
        }
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    [issue] = result.issues
    assert issue.related_location is None
    assert issue.related_original_text is None


def test_review_document_fills_related_location_for_rd(rulebook_path):
    # 발견5: RD(중복)도 LG/LF/GA와 마찬가지로 두 번째 위치를 표현할 수 있어야 한다(항상
    # 두 곳을 각각 독립적으로 프레임하는 Notion 규칙) — RD는 Paragraph 위계에 그대로 남지만
    # (실제 dispatch tier는 안 바꿈), 관련 위치 필드는 채워지는지 확인.
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        keyed_responses={
            Level.PARAGRAPH: [
                {
                    "verdicts": [
                        {
                            "index": 0,
                            "violated": True,
                            "original_text": "간단한 목적 설명입니다.",
                            "description": "d",
                            "fix_direction": "f",
                            "excused": False,
                            "related_location": "2. 배경",
                            "related_original_text": "두번째 문단입니다.",
                        }
                    ]
                }
            ],
        },
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [
                {"candidates": [{"chunk_index": 0, "rule_id": "RD-01", "quoted_text": "간단한 목적 설명입니다.", "reason": "r"}]}
            ],
            Level.DOCUMENT: [_EMPTY_CANDIDATES],
        }
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    [issue] = result.issues
    assert issue.rule_id == "RD-01"
    assert issue.level == "Paragraph"  # RD는 여전히 Paragraph 위계로 dispatch됨(문서 tier 이동 없음)
    assert issue.related_location == "2. 배경"
    assert issue.related_original_text == "두번째 문단입니다."


def test_widen_mi_finding_promotes_a_sub_sentence_fragment_up_to_its_whole_sentence():
    # Notion "단어 누락 → 문장" 행 — 인용문이 문장 전체보다 짧으면(단어/구 단위) 그 문장
    # 하나로만 좁힌다(더 넓은 문단으로는 넓히지 않음).
    tree = parse_document("DOC-TEST", _DOC)
    issue = _mi_issue(level="Sentence", location="1. 목적", original_text="목적")
    widened = _widen_mi_finding(issue, tree)
    assert widened.original_text == "간단한 목적 설명입니다."


def test_widen_mi_finding_widens_a_missing_sentence_to_the_whole_paragraph():
    # Notion "문장 누락 → 해당 소주제 전체" 행(사용자가 선택한 Ver2) — 인용문이 이미 문장
    # 전체와 같으면(더 좁히지 않고) 그 문장이 속한 Paragraph 청크 전체로 넓힌다.
    tree = parse_document("DOC-TEST", _DOC)
    issue = _mi_issue(level="Sentence", location="1. 목적", original_text="간단한 목적 설명입니다.")
    widened = _widen_mi_finding(issue, tree)
    assert widened.original_text == "간단한 목적 설명입니다."  # 이 문서는 문단=문장 1개뿐이라 동일


def test_widen_mi_finding_widens_a_missing_paragraph_to_adjacent_paragraphs():
    tree = parse_document("DOC-TEST", _DOC)
    issue = _mi_issue(level="Paragraph", location="1. 목적", original_text="간단한 목적 설명입니다.")
    widened = _widen_mi_finding(issue, tree)
    assert widened.original_text == "간단한 목적 설명입니다.\n\n두번째 문단입니다."


def test_widen_mi_finding_widens_a_missing_logical_unit_and_stays_one_sided_at_document_end():
    # 문서 끝(마지막 대주제)에서는 앞쪽으로만 넓혀진다("one-sided at document start/end").
    doc = (
        "# 문서\n\n## 1. 목적\n\n목적 문단.\n\n## 2. 배경\n\n배경 문단.\n\n## 3. 결론\n\n결론 문단.\n"
    )
    tree = parse_document("DOC-TEST", doc)
    issue = _mi_issue(level="Document", location="3. 결론", original_text="결론 문단.")
    widened = _widen_mi_finding(issue, tree)
    assert widened.original_text == "배경 문단.\n\n결론 문단."


def test_widen_mi_finding_leaves_the_issue_unchanged_when_location_has_no_matching_chunk():
    tree = parse_document("DOC-TEST", _DOC)
    issue = _mi_issue(level="Paragraph", location="존재하지 않는 위치", original_text="x")
    widened = _widen_mi_finding(issue, tree)
    assert widened.original_text == "x"


def test_screen_and_confirm_prompts_instruct_active_cross_location_search(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        keyed_responses={Level.DOCUMENT: [{"verdicts": [{"index": 0, "violated": False}]}]},
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [_EMPTY_CANDIDATES],
            Level.DOCUMENT: [
                {"candidates": [{"chunk_index": 0, "rule_id": "GA-01", "quoted_text": "x", "reason": "r"}]}
            ],
        }
    )

    review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    screen_system = screen_llm.isolated[Level.DOCUMENT].calls[-1]["system"]
    confirm_system = confirm_llm.isolated[Level.DOCUMENT].calls[-1]["system"]
    assert "goal/KPI" in screen_system
    assert "actively search" in confirm_system


def test_screen_and_confirm_prompts_include_category_boundary_notes(rulebook_path):
    # 발견1(PR #27)+발견4(2026-08-12): GA/TC/MI/LF 경계 혼동을 막는 프롬프트 보강이
    # 실제로 두 시스템 프롬프트 모두에 들어가는지 확인.
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        keyed_responses={Level.DOCUMENT: [{"verdicts": [{"index": 0, "violated": False}]}]},
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [_EMPTY_CANDIDATES],
            Level.DOCUMENT: [
                {"candidates": [{"chunk_index": 0, "rule_id": "GA-01", "quoted_text": "x", "reason": "r"}]}
            ],
        }
    )

    review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    screen_system = screen_llm.isolated[Level.DOCUMENT].calls[-1]["system"]
    confirm_system = confirm_llm.isolated[Level.DOCUMENT].calls[-1]["system"]
    for system in (screen_system, confirm_system):
        assert "GA (상위 목표와 세부 내용의 정합성)" in system
        assert "TC (용어 및 단어의 일관성)" in system
        assert "LF (논리 흐름, flow) is purely about" in system


def test_resolve_quoted_span_returns_exact_match_unchanged():
    assert _resolve_quoted_span("간단한 목적 설명입니다.", "간단한 목적 설명입니다.") == "간단한 목적 설명입니다."


def test_resolve_quoted_span_recovers_the_original_formatting_across_whitespace_differences():
    # confirm re-typed the quote with a collapsed space instead of the original newline —
    # still the same content, so the corrected value should come back as the chunk's own
    # verbatim substring (newline included), not the model's re-typed version.
    chunk_text = "첫 줄입니다.\n둘째 줄입니다."
    assert _resolve_quoted_span("첫 줄입니다. 둘째 줄입니다.", chunk_text) == chunk_text


def test_resolve_quoted_span_falls_back_to_nearest_sentence_when_quote_is_a_heading_label():
    # The actual root cause this fixes (2026-08-12): a chunk's location label ("2. 성공지표")
    # sat right next to its body text in the prompt, and nothing ever verified the model
    # quoted the body instead of just copying the label back — real user reports of
    # highlights landing on section headings traced to exactly this.
    chunk_text = "간단한 목적 설명입니다."
    assert _resolve_quoted_span("2. 성공지표", chunk_text) == "간단한 목적 설명입니다."


def test_resolve_quoted_span_handles_empty_chunk_text():
    assert _resolve_quoted_span("아무 말", "") == ""


def test_review_document_corrects_original_text_when_confirm_quotes_the_heading_label(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        keyed_responses={
            Level.PARAGRAPH: [
                {
                    "verdicts": [
                        {
                            "index": 0,
                            "violated": True,
                            "original_text": "1. 목적",  # the chunk's own location label, not its body
                            "description": "d",
                            "fix_direction": "f",
                            "excused": False,
                        }
                    ]
                }
            ],
        },
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [
                {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "1. 목적", "reason": "r"}]}
            ],
            Level.DOCUMENT: [_EMPTY_CANDIDATES],
        }
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    # 발견6(MI 프레이밍 확장)이 이 MI 이슈(Paragraph 위계)를 인접 문단까지 추가로 넓히므로,
    # 여기서는 발견3 자체(헤더 라벨이 아니라 실제 본문으로 교정됐는지)만 substring으로 확인.
    [issue] = result.issues
    assert "간단한 목적 설명입니다." in issue.original_text
    assert "1. 목적" != issue.original_text


def test_extract_global_context_returns_summary_and_term_glossary():
    llm = ScriptedLLM(
        [
            {
                "summary": "요약문",
                "terms": [{"term": "MAU", "definition": "월간 활성 사용자"}, {"term": "PM", "definition": "제품 관리자"}],
            }
        ]
    )
    summary, glossary = _extract_global_context("문서 전문", llm)
    assert summary == "요약문"
    assert "MAU: 월간 활성 사용자" in glossary
    assert "PM: 제품 관리자" in glossary


def test_extract_global_context_handles_missing_terms_field():
    llm = ScriptedLLM([{"summary": "요약문"}])
    summary, glossary = _extract_global_context("문서 전문", llm)
    assert summary == "요약문"
    assert glossary == ""


def test_extract_global_context_skips_malformed_term_entries():
    llm = ScriptedLLM([{"summary": "s", "terms": ["not a dict", {"term": "X"}, {"term": "Y", "definition": "def"}]}])
    _summary, glossary = _extract_global_context("문서 전문", llm)
    assert glossary == "- Y: def"


def test_confirm_prompt_includes_term_glossary_only_for_tc_candidates(rulebook_path):
    # 발견7: TC는 문단 이전에 쓰인 용어를 알아야 판정 가능한데 global_context(서술형 요약)엔
    # 개별 용어가 대부분 빠져 있음 — TC candidate가 있을 때만 명시적 용어 목록을 confirm
    # 프롬프트에 추가로 넘기는지(그리고 없을 땐 안 넘기는지) 확인.
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": "", "terms": [{"term": "MAU", "definition": "월간 활성 사용자"}]}],
        keyed_responses={
            Level.PARAGRAPH: [{"verdicts": [{"index": 0, "violated": False}, {"index": 1, "violated": False}]}],
        },
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [
                {
                    "candidates": [
                        {"chunk_index": 0, "rule_id": "TC-01", "quoted_text": "x", "reason": "r"},
                        {"chunk_index": 1, "rule_id": "MI-01", "quoted_text": "y", "reason": "r"},
                    ]
                }
            ],
            Level.DOCUMENT: [_EMPTY_CANDIDATES],
        }
    )

    review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    confirm_prompt = confirm_llm.isolated[Level.PARAGRAPH].calls[-1]["prompt"]
    assert "MAU: 월간 활성 사용자" in confirm_prompt


def test_confirm_prompt_omits_term_glossary_when_no_tc_candidates(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": "", "terms": [{"term": "MAU", "definition": "월간 활성 사용자"}]}],
        keyed_responses={Level.PARAGRAPH: [{"verdicts": [{"index": 0, "violated": False}]}]},
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [
                {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "x", "reason": "r"}]}
            ],
            Level.DOCUMENT: [_EMPTY_CANDIDATES],
        }
    )

    review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    confirm_prompt = confirm_llm.isolated[Level.PARAGRAPH].calls[-1]["prompt"]
    assert "MAU: 월간 활성 사용자" not in confirm_prompt


def test_review_document_drops_mi_false_positive_but_keeps_other_issues(rulebook_path):
    # 발견2 (planqa-agent PR #28/#55 패턴): MI 재검증이 "실제로 문서에 있음"이라고 판단하면
    # 그 이슈는 최종 결과에서 빠지고, 같은 실행의 다른(관계형) 카테고리 이슈는 그대로 남는다.
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": ""}, {"actually_missing": False, "reason": "실제로는 문서에 있음"}],
        keyed_responses={
            Level.PARAGRAPH: [
                {
                    "verdicts": [
                        {
                            "index": 0,
                            "violated": True,
                            "original_text": "간단한 목적 설명입니다.",
                            "description": "d",
                            "fix_direction": "f",
                            "excused": False,
                        }
                    ]
                }
            ],
            Level.DOCUMENT: [
                {
                    "verdicts": [
                        {"index": 0, "violated": True, "original_text": "x", "description": "d", "fix_direction": "f", "excused": False}
                    ]
                }
            ],
        },
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [
                {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "간단한 목적 설명입니다.", "reason": "r"}]}
            ],
            Level.DOCUMENT: [
                {"candidates": [{"chunk_index": 0, "rule_id": "GA-01", "quoted_text": "x", "reason": "r"}]}
            ],
        }
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert [issue.rule_id for issue in result.issues] == ["GA-01"]


def test_review_document_reports_a_clear_error_if_a_plain_scripted_llm_is_used(rulebook_path):
    # A plain ScriptedLLM([...]) (no keyed_responses) used against a structure that
    # dispatches concurrently must fail with a clear, specific message in tier_errors —
    # never silently reintroduce the shared-iterator race keyed_responses exists to
    # prevent. isolate_client() failures degrade into a tier_error like any other pass
    # failure (review_document itself must not crash), so this checks the error message
    # landed there rather than propagating as a raised exception.
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM([{"summary": ""}])
    screen_llm = ScriptedLLM([_EMPTY_CANDIDATES, _EMPTY_CANDIDATES])

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert any("keyed_responses" in error for error in result.tier_errors)
