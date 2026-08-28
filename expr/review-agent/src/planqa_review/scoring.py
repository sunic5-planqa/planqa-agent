from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from planqa_review.schema import Issue

GOLDEN_SHEET_NAME = "golden dataset"


@dataclass(frozen=True, slots=True)
class GoldenRow:
    doc_id: str
    level: str
    rule_id: str
    location: str


def load_golden_rows(xlsx_path: Path, sheet_name: str = GOLDEN_SHEET_NAME) -> tuple[GoldenRow, ...]:
    """The sheet has stray blank rows (spacer rows between entries) that carry no doc_id/
    rule_id — those are skipped rather than turned into empty GoldenRows."""
    workbook = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    worksheet = workbook[sheet_name]

    rows: list[GoldenRow] = []
    for raw in worksheet.iter_rows(min_row=2, values_only=True):
        doc_id = raw[0] if len(raw) > 0 else None
        level = raw[2] if len(raw) > 2 else None
        location = raw[3] if len(raw) > 3 else None
        rule_id = raw[5] if len(raw) > 5 else None
        if not doc_id or not rule_id:
            continue
        rows.append(
            GoldenRow(
                doc_id=str(doc_id).strip(),
                level=str(level).strip() if level else "",
                rule_id=str(rule_id).strip(),
                location=str(location).strip() if location else "",
            )
        )
    return tuple(rows)


def _normalize_location(text: str) -> str:
    return " ".join(text.split()).lower()


def _locations_overlap(a: str, b: str) -> bool:
    """Containment, not exact-equality — golden 위치 strings often name both sides of a
    cross-tier comparison (e.g. "1-5. 사용자 정의 ↔ 5-2. KPI 현황") while a predicted issue's
    location names only the flagged side, so one string merely needs to appear inside the
    other."""
    normalized_a, normalized_b = _normalize_location(a), _normalize_location(b)
    if not normalized_a or not normalized_b:
        return False
    return normalized_a in normalized_b or normalized_b in normalized_a


def category_of(rule_id: str) -> str:
    return rule_id.split("-")[0]


@dataclass(frozen=True, slots=True)
class ScoreCounts:
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def recall(self) -> float | None:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else None

    @property
    def precision(self) -> float | None:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else None

    def __add__(self, other: ScoreCounts) -> ScoreCounts:
        return ScoreCounts(
            true_positives=self.true_positives + other.true_positives,
            false_positives=self.false_positives + other.false_positives,
            false_negatives=self.false_negatives + other.false_negatives,
        )


@dataclass(frozen=True, slots=True)
class ScoreResult:
    overall: ScoreCounts
    by_rule: dict[str, ScoreCounts]
    by_category: dict[str, ScoreCounts]
    matched_golden: tuple[GoldenRow, ...] = ()
    missed_golden: tuple[GoldenRow, ...] = ()
    unmatched_issues: tuple[Issue, ...] = ()


def _bump(buckets: dict[str, ScoreCounts], key: str, **counts: int) -> None:
    buckets[key] = buckets.get(key, ScoreCounts()) + ScoreCounts(**counts)


def score_issues(doc_id: str, issues: Iterable[Issue], golden_rows: Iterable[GoldenRow]) -> ScoreResult:
    """Deterministic, no-LLM matching: a predicted issue matches an unclaimed golden row
    when rule_id is identical and their locations overlap (see `_locations_overlap`).
    Matching is greedy first-fit per issue, not a global optimum — good enough since a
    document rarely has two golden rows for the same rule_id at overlapping locations."""
    unmatched_golden = [row for row in golden_rows if row.doc_id == doc_id]
    matched_golden: list[GoldenRow] = []
    unmatched_issues: list[Issue] = []

    for issue in issues:
        if issue.doc_id != doc_id:
            continue
        match = next(
            (
                row
                for row in unmatched_golden
                if row.rule_id == issue.rule_id and _locations_overlap(row.location, issue.location)
            ),
            None,
        )
        if match is None:
            unmatched_issues.append(issue)
        else:
            unmatched_golden.remove(match)
            matched_golden.append(match)

    by_rule: dict[str, ScoreCounts] = {}
    by_category: dict[str, ScoreCounts] = {}

    for row in matched_golden:
        _bump(by_rule, row.rule_id, true_positives=1)
        _bump(by_category, category_of(row.rule_id), true_positives=1)
    for row in unmatched_golden:
        _bump(by_rule, row.rule_id, false_negatives=1)
        _bump(by_category, category_of(row.rule_id), false_negatives=1)
    for issue in unmatched_issues:
        _bump(by_rule, issue.rule_id, false_positives=1)
        _bump(by_category, category_of(issue.rule_id), false_positives=1)

    overall = ScoreCounts(
        true_positives=len(matched_golden),
        false_positives=len(unmatched_issues),
        false_negatives=len(unmatched_golden),
    )
    return ScoreResult(
        overall=overall,
        by_rule=by_rule,
        by_category=by_category,
        matched_golden=tuple(matched_golden),
        missed_golden=tuple(unmatched_golden),
        unmatched_issues=tuple(unmatched_issues),
    )


def merge_score_results(results: Iterable[ScoreResult]) -> ScoreResult:
    """Combines per-document ScoreResults into one benchmark-wide result — the experiment
    runner scores each document independently, then calls this once to get overall/by_rule/
    by_category numbers across the whole benchmark set."""
    overall = ScoreCounts()
    by_rule: dict[str, ScoreCounts] = {}
    by_category: dict[str, ScoreCounts] = {}
    matched_golden: list[GoldenRow] = []
    missed_golden: list[GoldenRow] = []
    unmatched_issues: list[Issue] = []

    for result in results:
        overall = overall + result.overall
        for key, counts in result.by_rule.items():
            by_rule[key] = by_rule.get(key, ScoreCounts()) + counts
        for key, counts in result.by_category.items():
            by_category[key] = by_category.get(key, ScoreCounts()) + counts
        matched_golden.extend(result.matched_golden)
        missed_golden.extend(result.missed_golden)
        unmatched_issues.extend(result.unmatched_issues)

    return ScoreResult(
        overall=overall,
        by_rule=by_rule,
        by_category=by_category,
        matched_golden=tuple(matched_golden),
        missed_golden=tuple(missed_golden),
        unmatched_issues=tuple(unmatched_issues),
    )
