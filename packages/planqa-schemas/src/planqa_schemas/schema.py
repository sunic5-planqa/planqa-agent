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
