from __future__ import annotations

from planqa_review.schema import Issue
from planqa_review.verifier import has_valid_reference_exception


def _issue(**overrides) -> Issue:
    defaults = dict(
        doc_id="DOC-TEST",
        level="Paragraph",
        rule_id="LG-03",
        location="2-4",
        description="d",
    )
    defaults.update(overrides)
    return Issue(**defaults)


def test_has_valid_reference_exception_true_for_doc_code_citation():
    golden = _issue(original_text="빠른 시일 내 환불 처리")
    source_text = "빠른 시일 내 환불 처리. 반품/교환 정책서(DOC-005) 참고."
    assert has_valid_reference_exception(golden, source_text) is True


def test_has_valid_reference_exception_false_when_citation_is_a_different_paragraph():
    # Rulebook §3's own counter-example (DOC-006 2-3): a "(DOC-005) 참고" citation in its
    # own paragraph must NOT excuse text it doesn't share a block with.
    golden = _issue(original_text="빠른 시일 내 환불 처리")
    source_text = "빠른 시일 내 환불 처리.\n\n반품/교환 정책서(DOC-005) 참고."
    assert has_valid_reference_exception(golden, source_text) is False


def test_has_valid_reference_exception_false_without_source_text():
    golden = _issue(original_text="x")
    assert has_valid_reference_exception(golden, None) is False


def test_has_valid_reference_exception_true_for_prose_citation_without_doc_code():
    # The "예외조건 data" QA-dataset rows all cite this way ("「제목」 2-4 '...'을 따른다")
    # instead of the "(DOC-XXX) 참고" shorthand the original regex assumed — found while
    # computing a real defense-rate figure against that dataset (planqa-agent PR #32,
    # 2026-08-12). Ported verbatim from eval-agent's test_verifier.py.
    golden = _issue(rule_id="LG-03", original_text="가족 대표 회선은 월 최대 10GB까지 데이터를 선물할 수 있다.")
    source_text = (
        "가족 대표 회선은 월 최대 10GB까지 데이터를 선물할 수 있다. 월 한도 설정의 도입 근거는 "
        "「5G 가족결합 운영전략서」 2-4 '과도한 데이터 이전 방지 원칙'을 따른다."
    )
    assert has_valid_reference_exception(golden, source_text) is True


def test_has_valid_reference_exception_true_for_prose_citation_with_haedanghaneun_gyeong():
    golden = _issue(rule_id="GA-03", original_text="긴급공지 작성자는 '긴급 발행'을 선택할 수 있다.")
    source_text = (
        "긴급공지 작성자는 「SKT 전사 중요공지 발행 정책·기능서」 2-2 '하위 재량 허용 범위'에 "
        "해당하는 경우에만 '긴급 발행'을 선택할 수 있다."
    )
    assert has_valid_reference_exception(golden, source_text) is True
