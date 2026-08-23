from __future__ import annotations

import json

from planqa_review.structures import xdc


def _record(
    doc_id: str = "DOC-REF",
    location: str = "1-1",
    quote: str = "신청 기한: 상품 수령일로부터 14일 이내",
    policy_subject: str = "반품",
    attribute: str = "신청 기한",
    canonical_terms: tuple[str, ...] = ("반품", "신청 기한", "14일"),
) -> xdc.DecisionRecord:
    return xdc.DecisionRecord(
        doc_id=doc_id,
        location=location,
        quote=quote,
        policy_subject=policy_subject,
        attribute=attribute,
        action=None,
        scope=None,
        condition_exception=None,
        value="14",
        unit="일",
        time_basis="상품 수령일",
        canonical_terms=canonical_terms,
    )


def test_content_hash_is_deterministic_and_sensitive_to_text():
    assert xdc.content_hash("가") == xdc.content_hash("가")
    assert xdc.content_hash("가") != xdc.content_hash("나")


def test_parse_decision_records_builds_records_keyed_by_chunk_location():
    from planqa_review.document import Chunk
    from planqa_schemas.schema import Level

    chunks = [Chunk(level=Level.PARAGRAPH, location="1-1", text="x")]
    raw = [
        {
            "chunk_index": 0,
            "quote": "신청 기한: 상품 수령일로부터 14일 이내",
            "policy_subject": "반품",
            "attribute": "신청 기한",
            "value": "14",
            "unit": "일",
            "canonical_terms": ["반품", "14일"],
        }
    ]
    [record] = xdc.parse_decision_records(raw, "DOC-REF", chunks)
    assert record.location == "1-1"
    assert record.doc_id == "DOC-REF"
    assert record.canonical_terms == ("반품", "14일")


def test_parse_decision_records_skips_incomplete_or_out_of_range_items():
    from planqa_review.document import Chunk
    from planqa_schemas.schema import Level

    chunks = [Chunk(level=Level.PARAGRAPH, location="1-1", text="x")]
    raw = [
        {"chunk_index": 0, "quote": "", "policy_subject": "반품", "attribute": "신청 기한"},  # 빈 quote
        {"chunk_index": 5, "quote": "q", "policy_subject": "반품", "attribute": "신청 기한"},  # 범위 밖
        "not a dict",
    ]
    assert xdc.parse_decision_records(raw, "DOC-REF", chunks) == []


def test_match_candidates_signal_a_structured_key_match():
    current = _record(quote="단순 변심 | 상품 수령일로부터 7일 이내", canonical_terms=("반품", "신청 기한", "7일"))
    reference = _record()  # 같은 policy_subject/attribute, 다른 value
    index = xdc.ReferenceIndex(doc_id="DOC-REF", records=(reference,))
    matched = xdc.match_candidates(current, [index], aliases={})
    assert matched == [reference]


def test_match_candidates_signal_b_alias_match():
    current = _record(
        quote="단순 사유로 인한 취소는 2주 이내",
        policy_subject="반품",
        attribute="기타",  # attribute 자체는 다르게 해서 신호 A는 안 걸리게
        canonical_terms=("단순 사유", "2주"),
    )
    reference = _record(policy_subject="배송", attribute="다른 속성", canonical_terms=("단순 변심", "14일"))
    aliases = {"단순 사유": "단순 변심", "2주": "14일"}
    index = xdc.ReferenceIndex(doc_id="DOC-REF", records=(reference,))
    matched = xdc.match_candidates(current, [index], aliases=aliases)
    assert matched == [reference]


def test_match_candidates_returns_empty_when_no_signal_hits():
    current = _record(
        quote="전혀 다른 주제입니다",
        policy_subject="쿠폰",
        attribute="발급 조건",
        canonical_terms=("쿠폰", "발급"),
    )
    reference = _record(policy_subject="반품", attribute="신청 기한", canonical_terms=("반품", "신청 기한"))
    index = xdc.ReferenceIndex(doc_id="DOC-REF", records=(reference,))
    assert xdc.match_candidates(current, [index], aliases={}) == []


def test_match_candidates_caps_at_top_k():
    current = _record(quote="단순 변심 | 상품 수령일로부터 7일 이내")
    references = [_record(location=f"1-{i}", quote=f"신청 기한: 상품 수령일로부터 {i}일 이내") for i in range(5)]
    index = xdc.ReferenceIndex(doc_id="DOC-REF", records=tuple(references))
    matched = xdc.match_candidates(current, [index], aliases={}, top_k=3)
    assert len(matched) == 3


def test_load_aliases_returns_empty_dict_for_missing_file(tmp_path):
    assert xdc.load_aliases(tmp_path / "missing.json") == {}


def test_load_aliases_reads_json_file(tmp_path):
    path = tmp_path / "aliases.json"
    path.write_text(json.dumps({"단순 사유": "단순 변심"}), encoding="utf-8")
    assert xdc.load_aliases(path) == {"단순 사유": "단순 변심"}
