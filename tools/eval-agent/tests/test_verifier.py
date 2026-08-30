from __future__ import annotations

from planqa_schemas.rulebook import parse_rulebook
from planqa_schemas.schema import Issue
from planqa_eval.verifier import has_valid_reference_exception, verify_matches, verify_misses


def _issue(**kwargs) -> Issue:
    defaults = dict(doc_id="DOC-001", level="Sentence", rule_id="AE-03", location="x", description="y")
    defaults.update(kwargs)
    return Issue(**defaults)


def test_verify_matches_flags_rule_and_level_mismatch():
    golden = _issue(rule_id="AE-01", level="Sentence")
    predicted = _issue(rule_id="AE-03", level="Paragraph")
    [verified] = verify_matches([(golden, predicted)])
    assert verified.rule_id_match is False
    assert verified.level_match is False
    assert verified.fully_correct is False


def test_verify_matches_fully_correct():
    golden = _issue(rule_id="AE-01", level="Sentence")
    predicted = _issue(rule_id="AE-01", level="Sentence")
    [verified] = verify_matches([(golden, predicted)])
    assert verified.fully_correct is True


def test_doc006_ae01_citation_does_not_excuse_the_miss(rulebook_path, source_dir):
    # Rulebook §3's own counter-example: a "반품/교환 정책서(DOC-005) 참고" citation in 2-3
    # refers to return-handling criteria, not to the vague SLA wording ("빠른 시일 내" etc.)
    # AE-01 flags — it must NOT excuse a missed prediction for that golden issue.
    rulebook = parse_rulebook(rulebook_path)
    golden = _issue(
        doc_id="DOC-006",
        rule_id="AE-01",
        level="Logical Unit",
        location="2-1~2-4 전반",
        original_text='"빠른 시일 내", "신속하게", "즉시", "가능한 한 빨리", "최대한 빠르게" (2-1~2-4)',
        description="SLA가 정량화 가능한데 정성적 표현으로만 서술됨",
    )
    [miss] = verify_misses([golden], rulebook, source_dir)
    assert miss.excused is False
    assert miss.is_false_negative is True


def test_non_reference_exception_rule_is_never_excused(rulebook_path, source_dir):
    rulebook = parse_rulebook(rulebook_path)
    golden = _issue(doc_id="DOC-006", rule_id="AE-03")  # not in the reference-exception set
    [miss] = verify_misses([golden], rulebook, source_dir)
    assert miss.excused is False
    assert miss.excuse_reason is None


def test_has_valid_reference_exception_true_when_citation_shares_a_paragraph():
    golden = _issue(original_text="「최대 지연 3일」")
    source_text = "일부 처리에는 지연이 있을 수 있다. 세부 기준은 운영정책서(DOC-020) 참고. 「최대 지연 3일」로 안내한다."
    assert has_valid_reference_exception(golden, source_text) is True


def test_has_valid_reference_exception_false_when_citation_is_a_different_paragraph():
    golden = _issue(original_text="「최대 지연 3일」")
    source_text = "세부 기준은 운영정책서(DOC-020) 참고.\n\n배송은 「최대 지연 3일」 이내로 안내한다."
    assert has_valid_reference_exception(golden, source_text) is False


def test_has_valid_reference_exception_false_without_source_text():
    golden = _issue()
    assert has_valid_reference_exception(golden, None) is False


def test_has_valid_reference_exception_true_for_prose_citation_without_doc_code():
    # The "예외조건 data" QA-dataset rows all cite this way ("「제목」 2-4 '...'을 따른다")
    # instead of the "(DOC-XXX) 참고" shorthand the original regex assumed — found while
    # computing a real defense-rate figure against that dataset (2026-08-12).
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
