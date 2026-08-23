from __future__ import annotations

from conftest import ScriptedLLM

from planqa_schemas.rulebook import parse_rulebook
from planqa_schemas.schema import Level
from planqa_review.structures.bundled_screen_hybrid import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n\n## 2. 배경\n\n두번째 문단입니다.\n"

_EMPTY_CANDIDATES = {"candidates": []}


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


def test_review_document_ignores_related_fields_for_non_relational_categories(rulebook_path):
    # MI isn't in _RELATIONAL_CATEGORIES — even if the model tries to fill
    # related_location/related_original_text anyway (defensive against it ignoring the
    # null instruction), both must come back None.
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
                            "excused": False,
                            "related_location": "이건 무시돼야 함",
                            "related_original_text": "이것도 무시돼야 함",
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

    [issue] = result.issues
    assert issue.related_location is None
    assert issue.related_original_text is None


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
                            "related_original_text": "다른 위치의 원문 문장",
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
    assert issue.related_original_text == "다른 위치의 원문 문장"


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


def _xdc_rulebook(tmp_path):
    from planqa_schemas.rulebook import parse_rulebook

    path = tmp_path / "xdc_rulebook.md"
    path.write_text(
        "## 1. 타 문서 확정사항 불일치 Cross-Document Consistency\n\n"
        "| **Rule ID** | **정의** | **예외 조건** |\n"
        "| --- | --- | --- |\n"
        "| XDC-01 | 동일 정책의 확정 사항은 참고문서와 일치해야 한다. | - |\n",
        encoding="utf-8",
    )
    return parse_rulebook(path)


# 타문서와의_정합성_룰북_Section1_후보매처_보충본.md §1-7의 예시(현재 문서 7일 vs 참고문서
# 14일)를 그대로 골든 케이스로 씀.
def test_review_document_flags_xdc_conflict_against_reference_document(rulebook_path, tmp_path):
    rulebook = parse_rulebook(rulebook_path)
    xdc_rulebook = _xdc_rulebook(tmp_path)
    current_doc = "# 반품 정책\n\n## 1. 신청 기한\n\n단순 변심 | 상품 수령일로부터 7일 이내\n"
    reference_doc = "# 반품 정책 (참고)\n\n## 1. 신청 기한\n\n신청 기한: 상품 수령일로부터 14일 이내\n"

    reference_decision_response = {
        "decision_records": [
            {
                "chunk_index": 0,
                "quote": "신청 기한: 상품 수령일로부터 14일 이내",
                "policy_subject": "반품",
                "attribute": "신청 기한",
                "value": "14",
                "unit": "일",
                "time_basis": "상품 수령일",
                "canonical_terms": ["반품", "신청 기한", "14일"],
            }
        ]
    }
    confirm_llm = ScriptedLLM(
        [reference_decision_response, {"summary": ""}],
        keyed_responses={
            Level.PARAGRAPH: [
                {
                    "verdicts": [
                        {
                            "index": 0,
                            "violated": True,
                            "rule_id": "XDC-01",
                            "description": "신청 기한이 다름",
                            "rationale": "현재 문서는 7일, 참고문서는 14일",
                            "fix_direction": "14일로 정정",
                            "excused": False,
                            "difference_type": "value",
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
                    "candidates": [],
                    "decision_records": [
                        {
                            "chunk_index": 0,
                            "quote": "단순 변심 | 상품 수령일로부터 7일 이내",
                            "policy_subject": "반품",
                            "attribute": "신청 기한",
                            "value": "7",
                            "unit": "일",
                            "time_basis": "상품 수령일",
                            "canonical_terms": ["반품", "신청 기한", "7일"],
                        }
                    ],
                }
            ],
            Level.DOCUMENT: [_EMPTY_CANDIDATES],
        }
    )

    result = review_document(
        "DOC-CURRENT",
        current_doc,
        rulebook,
        screen_llm,
        confirm_llm,
        reference_documents=[("DOC-REF", reference_doc)],
        xdc_rulebook=xdc_rulebook,
    )

    [issue] = result.issues
    assert issue.rule_id == "XDC-01"
    assert issue.reference_document == "DOC-REF"
    assert issue.reference_quote == "신청 기한: 상품 수령일로부터 14일 이내"
    assert issue.difference_type == "value"


def test_review_document_without_reference_documents_is_unaffected_by_xdc_params(rulebook_path):
    # reference_documents=()(기본값)일 땐 xdc_rulebook을 같이 줘도 아무 XDC 콜도 안 일어나야
    # 한다 — 스크립트에 XDC용 응답을 하나도 안 준비해뒀는데도 통과해야 회귀가 없다는 뜻.
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM([{"summary": ""}], keyed_responses={Level.PARAGRAPH: [], Level.DOCUMENT: []})
    screen_llm = ScriptedLLM(keyed_responses={Level.PARAGRAPH: [_EMPTY_CANDIDATES], Level.DOCUMENT: [_EMPTY_CANDIDATES]})

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert result.issues == ()
    assert result.tier_errors == ()


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
