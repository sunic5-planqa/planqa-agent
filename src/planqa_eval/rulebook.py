from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from planqa_eval.schema import KOREAN_LEVEL_NAMES, Level

_CATEGORY_HEADING = re.compile(r"(?m)^## \d+\.\s*(.+)$")
_TABLE_ROW = re.compile(r"(?m)^\|\s*([A-Z]{2}-\d{2})\s*\|(.*)\|\s*$")
_REFERENCE_EXCEPTION_RULES = re.compile(
    r"적용\s*대상\s*룰[:：]\s*([A-Z]{2}-\d{2}(?:\s*,\s*[A-Z]{2}-\d{2})*)"
)


@dataclass(frozen=True, slots=True)
class RuleDef:
    rule_id: str
    category: str
    category_label: str
    text: str
    fixed_level: Level | None
    exception_text: str | None


@dataclass(frozen=True, slots=True)
class RuleBook:
    rules: dict[str, RuleDef]
    categories: tuple[str, ...]
    reference_exception_rule_ids: frozenset[str]

    def rule(self, rule_id: str) -> RuleDef | None:
        return self.rules.get(rule_id)

    def category_of(self, rule_id: str) -> str | None:
        rule = self.rules.get(rule_id)
        return rule.category if rule else None


def _parse_row(rule_id: str, cells_raw: str, category: str, category_label: str) -> RuleDef:
    cells = [c.strip() for c in cells_raw.split("|")]
    if len(cells) == 3:
        text, level_text, exception_text = cells
        fixed_level = KOREAN_LEVEL_NAMES.get(level_text)
    else:
        text, exception_text = cells[0], cells[-1]
        fixed_level = None
    return RuleDef(
        rule_id=rule_id,
        category=category,
        category_label=category_label,
        text=text,
        fixed_level=fixed_level,
        exception_text=None if exception_text == "-" else exception_text,
    )


def parse_rulebook(path: Path) -> RuleBook:
    text = path.read_text(encoding="utf-8")

    # The file ends with an authoring-progress tracking table ("Rule ID | 채워야 할 개수 |
    # 담당자") that reuses every Rule ID from the catalog above it — parsing it as rule rows
    # would silently overwrite the real rule definitions with (count, assignee) pairs.
    tracking_table_start = text.find("채워야 할 개수")
    if tracking_table_start != -1:
        text = text[:tracking_table_start]

    reference_match = _REFERENCE_EXCEPTION_RULES.search(text)
    reference_exception_rule_ids = (
        frozenset(rid.strip() for rid in reference_match.group(1).split(","))
        if reference_match
        else frozenset()
    )

    parts = _CATEGORY_HEADING.split(text)
    rules: dict[str, RuleDef] = {}
    categories: list[str] = []

    # parts = [intro, label_1, block_1, label_2, block_2, ...]
    for label, block in zip(parts[1::2], parts[2::2]):
        row_matches = list(_TABLE_ROW.finditer(block))
        if not row_matches:
            continue
        category = row_matches[0].group(1).split("-")[0]
        categories.append(category)
        for match in row_matches:
            rule_id, cells_raw = match.group(1), match.group(2)
            rules[rule_id] = _parse_row(rule_id, cells_raw, category, label)

    return RuleBook(
        rules=rules,
        categories=tuple(categories),
        reference_exception_rule_ids=reference_exception_rule_ids,
    )
