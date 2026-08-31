from __future__ import annotations

from typing import Any

from conftest import ScriptedLLM

from planqa_schemas.rulebook import parse_rulebook
from planqa_schemas.schema import Issue, Level
from planqa_review.structures.bundled_screen_hybrid import _verify_ae_finding, _verify_mi_finding, review_document

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


def test_extra_absence_check_rule_ids_routes_a_normally_paragraph_rule_to_document(rulebook_path):
    # ABSENCE_CHECK_RULE_IDS is a closed set of two literal built-in rule_ids (LG-01,
    # TC-02) — a caller merging in rules of its own (dynamically-generated rule_ids) has no
    # way to mark one as absence-check without this extension point. MI-01 is an ordinary
    # paragraph-tier rule here only to prove the override actually moves dispatch, not
    # because it's realistically absence-check shaped.
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        keyed_responses={
            Level.DOCUMENT: [
                {
                    "verdicts": [
                        {"index": 0, "violated": True, "original_text": "x", "description": "d", "excused": False}
                    ]
                }
            ],
        },
    )
    screen_llm = ScriptedLLM(
        keyed_responses={
            Level.PARAGRAPH: [_EMPTY_CANDIDATES],
            Level.DOCUMENT: [
                {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "x", "reason": "r"}]}
            ],
        }
    )

    result = review_document(
        "DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, extra_absence_check_rule_ids=frozenset({"MI-01"})
    )

    [issue] = result.issues
    assert issue.rule_id == "MI-01"
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


# 회귀 테스트 — _run_xdc_confirm이 (네트워크 오류 등으로) 실패했을 때, 같은 패스에서 이미
# _confirm_pass가 확정해둔 일반(non-XDC) 이슈까지 통째로 버려지면 안 된다. 참고문서를 붙였다는
# 이유만으로 기존 단일문서 검토 안정성이 나빠지는 건 회귀다.
def test_xdc_confirm_failure_does_not_discard_already_confirmed_normal_issues(rulebook_path, tmp_path):
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
                "canonical_terms": ["반품", "신청 기한"],
            }
        ]
    }
    # Level.PARAGRAPH에 정상 confirm용 응답 딱 1개만 준다 — 같은 pass 안에서 XDC confirm이
    # (같은 isolated_confirm 인스턴스로) 두 번째 호출을 시도하면 ScriptedLLM의 응답 큐가
    # 바닥나 StopIteration이 나서, 실제 API 장애를 흉내낸다.
    confirm_llm = ScriptedLLM(
        [reference_decision_response, {"summary": ""}],
        keyed_responses={
            Level.PARAGRAPH: [
                {
                    "verdicts": [
                        {
                            "index": 0,
                            "violated": True,
                            "original_text": "단순 변심 | 상품 수령일로부터 7일 이내",
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
                {
                    "candidates": [
                        {
                            "chunk_index": 0,
                            "rule_id": "MI-01",
                            "quoted_text": "단순 변심 | 상품 수령일로부터 7일 이내",
                            "reason": "r",
                        }
                    ],
                    "decision_records": [
                        {
                            "chunk_index": 0,
                            "quote": "단순 변심 | 상품 수령일로부터 7일 이내",
                            "policy_subject": "반품",
                            "attribute": "신청 기한",
                            "canonical_terms": ["반품", "신청 기한"],
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

    # 정상 이슈(MI-01)는 살아남고, XDC 실패는 tier_errors로만 보고돼야 한다.
    assert [issue.rule_id for issue in result.issues] == ["MI-01"]
    assert any("XDC" in error for error in result.tier_errors)


# §1-3: 후보 매처가 "충돌 판정"이 아니라 "같은 정책일 가능성이 있는 참고문장"을 여러 참고문서
# 중에서 찾아내는 것이 목적 — 참고문서가 하나가 아니라 여러 개일 때, 관련 없는 문서(쿠폰/배송)를
# 무시하고 실제로 같은 정책(반품/신청 기한)을 다루는 문서만 골라내는지 파이프라인 전체로 확인.
def test_review_document_finds_the_right_reference_doc_among_several(rulebook_path, tmp_path):
    rulebook = parse_rulebook(rulebook_path)
    xdc_rulebook = _xdc_rulebook(tmp_path)
    current_doc = "# 반품 정책\n\n## 1. 신청 기한\n\n단순 변심 | 상품 수령일로부터 7일 이내\n"
    coupon_doc = "# 쿠폰 정책\n\n## 1. 발급 조건\n\n신규 가입 시 1회 발급\n"
    shipping_doc = "# 배송 정책\n\n## 1. 배송 권역\n\n서울 전 지역 당일 배송\n"
    refund_doc = "# 반품 정책 (참고)\n\n## 1. 신청 기한\n\n신청 기한: 상품 수령일로부터 14일 이내\n"

    def _decision_response(quote: str, subject: str, attribute: str, value: str) -> dict:
        return {
            "decision_records": [
                {
                    "chunk_index": 0,
                    "quote": quote,
                    "policy_subject": subject,
                    "attribute": attribute,
                    "value": value,
                    "canonical_terms": [subject, attribute],
                }
            ]
        }

    confirm_llm = ScriptedLLM(
        [
            _decision_response("신규 가입 시 1회 발급", "쿠폰", "발급 조건", ""),
            _decision_response("서울 전 지역 당일 배송", "배송", "배송 권역", ""),
            _decision_response("신청 기한: 상품 수령일로부터 14일 이내", "반품", "신청 기한", "14"),
            {"summary": ""},
        ],
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
        reference_documents=[("DOC-COUPON", coupon_doc), ("DOC-SHIPPING", shipping_doc), ("DOC-REFUND", refund_doc)],
        xdc_rulebook=xdc_rulebook,
    )

    [issue] = result.issues
    assert issue.reference_document == "DOC-REFUND"
    # confirm_xdc_pass에 실제로 넘어간 후보 쌍이 1개뿐이었는지(쿠폰/배송 레코드가 안 섞여
    # 들어갔는지) 프롬프트에서도 확인 — DOC-COUPON/DOC-SHIPPING 문구가 없어야 한다.
    xdc_confirm_prompt = confirm_llm.isolated[Level.PARAGRAPH].calls[-1]["prompt"]
    assert "신규 가입" not in xdc_confirm_prompt
    assert "당일 배송" not in xdc_confirm_prompt
    assert "14일 이내" in xdc_confirm_prompt


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


class _StubVerifyLLM:
    """A minimal LLMClient double for unit-testing _verify_mi_finding/_verify_ae_finding in
    isolation, without needing a full ScriptedLLM response queue — mirrors expr/review-agent's
    _StubVerifyLLM (2026-08-21, MI/AE 과탐지 검증 완화)."""

    def __init__(self, response: Any | None, *, raise_error: bool = False) -> None:
        self._response = response
        self._raise_error = raise_error

    def complete_json(self, *, system: str, prompt: str, cache_prefix: str | None = None) -> Any:
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


def test_review_document_drops_an_mi_finding_the_fp_verifier_rejects(rulebook_path):
    # End-to-end: a screened+confirmed MI candidate that _verify_mi_finding then rejects
    # must not appear in the final issues — proves the verification stage is actually wired
    # into review_document(), not just unit-tested in isolation above.
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [{"summary": ""}, {"actually_missing": False, "reason": "8장에 이미 있음"}],
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

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert result.issues == ()
    assert result.tier_errors == ()
