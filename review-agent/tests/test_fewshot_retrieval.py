from __future__ import annotations

from planqa_review.structures.fewshot_bank import FewShotExample
from planqa_review.structures.fewshot_retrieval import top_k_examples

_POOL = {
    "MI-01": [
        FewShotExample("고객이 결제 버튼을 누르면 즉시 주문이 생성된다", "동작 설명"),
        FewShotExample("배송이 완료되면 알림이 발송된다", "다른 동작 설명"),
        FewShotExample("고객이 결제 버튼을 누르면 포인트가 즉시 적립된다", "결제 버튼과 유사한 동작"),
    ]
}


def test_top_k_returns_the_most_similar_example_first():
    # Closely overlaps with the first and third pool entries (both mention "결제 버튼을
    # 누르면") — one of those two must rank above the unrelated "배송이 완료되면" entry.
    reference_text = "고객이 결제 버튼을 누르면 무슨 일이 일어나는지 정의되지 않았다"
    result = top_k_examples(reference_text, "MI-01", k=1, candidates=_POOL)

    [top] = result
    assert "결제 버튼" in top.original_text


def test_top_k_respects_the_k_limit():
    result = top_k_examples("아무 상관 없는 문장", "MI-01", k=2, candidates=_POOL)
    assert len(result) == 2


def test_top_k_returns_empty_list_for_a_rule_with_no_candidates():
    result = top_k_examples("무엇이든", "AE-03", k=2, candidates=_POOL)
    assert result == []


def test_top_k_falls_back_to_curated_order_when_nothing_overlaps():
    # No shared bigrams with any pool entry — every score is 0.0, so the stable sort must
    # preserve the pool's own best-first curated order rather than reshuffling arbitrarily.
    result = top_k_examples("zzz999###", "MI-01", k=3, candidates=_POOL)
    assert [example.original_text for example in result] == [example.original_text for example in _POOL["MI-01"]]


def test_top_k_uses_the_real_bank_by_default():
    # Default `candidates=None` should read from fewshot_bank.ALL_VIOLATION_CANDIDATES —
    # TM-01 has exactly 1 real candidate there under the 2026-08-12 widened leakage scope
    # (see test_fewshot_bank.py; AE-03 has 0 under that same scope, so it can't be used here).
    result = top_k_examples("아무 문장", "TM-01", k=2)
    assert len(result) == 1
