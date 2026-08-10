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
