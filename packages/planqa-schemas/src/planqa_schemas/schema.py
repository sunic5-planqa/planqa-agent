from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Level(StrEnum):
    DOCUMENT = "Document"
    LOGICAL_UNIT = "Logical Unit"
    PARAGRAPH = "Paragraph"
    SENTENCE = "Sentence"
    WORD = "Word"


# rulebook.md uses Korean 위계 names in its per-rule "위계" column (RD/GA categories);
# the xlsx Level columns already use the English names above, so this maps only the former.
KOREAN_LEVEL_NAMES: dict[str, Level] = {
    "문서": Level.DOCUMENT,
    "논리 단위": Level.LOGICAL_UNIT,
    "문단": Level.PARAGRAPH,
    "문장": Level.SENTENCE,
    "단어": Level.WORD,
}


@dataclass(frozen=True, slots=True)
class Issue:
    """Common schema every parser normalizes into: golden dataset rows, review-agent JSON
    output, and human Review1-6 sheet rows all become this shape."""

    doc_id: str
    level: str
    rule_id: str
    location: str
    description: str
    exception_ref: str | None = None
    source: str = ""
    issue_id: str | None = None
    original_text: str | None = None
    rationale: str | None = None
    fix_direction: str | None = None
    # LG(논리 비약)/LF(논리 흐름)/GA(상위 목표와의 정합성)는 정의상 두 위치 간의 관계
    # 오류라 프론트가 "범위 프레임"을 그리려면 두 번째 위치가 필요함 — 그 외 카테고리는
    # 단일 위치 오류라 항상 None. 채워지는 곳: confirm 단계 verdict 응답.
    # (github.com/sunic5-planqa/planqa-agent issue #4)
    related_location: str | None = None
    # related_location은 라벨 문자열("5-2. 환불 정책")뿐이라 프론트가 그 위치의 실제 문구를
    # 수정 제안하지 못함 — original_text와 같은 성격의, 두 번째 위치의 정확한 인용문. 같은
    # 자리·같은 조건(related_location과 함께, LG/LF/GA일 때만 채워지고 나머지는 항상 None).
    # (github.com/sunic5-planqa/planqa-agent issue #29)
    related_original_text: str | None = None
    # 타문서 정합성(XDC) 카테고리 전용 — related_location/related_original_text가 "같은 문서
    # 안의 두 번째 위치"를 가리키는 것과 대칭으로, 이 네 필드는 "현재 검토 중인 문서가 아닌
    # 참고문서 쪽의 근거"를 가리킨다. XDC 위반이 확정됐을 때만 채워지고, 그 외 모든 카테고리는
    # 항상 None. reference_document/reference_section은 위치 라벨, reference_quote는
    # 그 위치의 정확한 인용문(원본 문구를 그대로 보여주기 위함 — related_original_text와 같은
    # 이유), difference_type은 두 문서가 어떤 축(예: value/scope/condition)에서 다른지의 분류.
    # (github.com/sunic5-planqa/planqa-agent — 타문서 정합성 룰북 Section 1)
    reference_document: str | None = None
    reference_section: str | None = None
    reference_quote: str | None = None
    difference_type: str | None = None
