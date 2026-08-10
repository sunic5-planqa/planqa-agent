from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from planqa_eval.pipeline import PipelineResult
from planqa_eval.prefilter import category_of


@dataclass(frozen=True, slots=True)
class ConfusionCounts:
    true_positive: int = 0
    false_negative: int = 0
    false_positive: int = 0

    @property
    def recall(self) -> float | None:
        denom = self.true_positive + self.false_negative
        return self.true_positive / denom if denom else None

    @property
    def precision(self) -> float | None:
        denom = self.true_positive + self.false_positive
        return self.true_positive / denom if denom else None


@dataclass(frozen=True, slots=True)
class AggregateReport:
    overall: ConfusionCounts
    by_category: dict[str, ConfusionCounts] = field(default_factory=dict)
    by_level: dict[str, ConfusionCounts] = field(default_factory=dict)
    new_rule_candidate_count: int = 0
    valid_unlabeled_count: int = 0
    human_review_count: int = 0
    excused_miss_count: int = 0


def aggregate(result: PipelineResult) -> AggregateReport:
    """Rule-category and Level are both derived from the issue itself (never hardcoded),
    so this scales automatically as the golden dataset and rulebook grow.

    Counting rules:
    - A matched pair only counts as a true positive if Rule ID *and* Level are both exactly
      right (verifier.VerifiedMatch.fully_correct). A matched-but-misclassified pair is a
      miss for the golden issue's own category/level *and* a false positive for whatever
      the agent claimed instead.
    - A missed golden issue only counts as a false negative if the exception-condition
      check didn't excuse it (verifier.VerifiedMiss.excused) — excused misses are dropped
      from recall entirely, not counted as either a hit or a miss.
    - An unmatched predicted issue only counts as a false positive if new-rule triage
      concluded it's a genuine misfire ("false_positive"); "new_rule_candidate",
      "valid_but_unlabeled", and "human_review" verdicts are tracked separately and
      excluded from precision — penalizing the agent for spotting a real gap in the
      rulebook, or for correctly catching something the golden set just never happened to
      label, would both be wrong.
    """
    category_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    level_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for verified in result.verified_matches:
        golden_category = category_of(verified.golden.rule_id)
        if verified.fully_correct:
            category_counts[golden_category]["tp"] += 1
            level_counts[verified.golden.level]["tp"] += 1
        else:
            category_counts[golden_category]["fn"] += 1
            level_counts[verified.golden.level]["fn"] += 1
            predicted_category = category_of(verified.predicted.rule_id)
            category_counts[predicted_category]["fp"] += 1
            level_counts[verified.predicted.level]["fp"] += 1

    excused_miss_count = 0
    for miss in result.verified_misses:
        if miss.excused:
            excused_miss_count += 1
            continue
        category_counts[category_of(miss.golden.rule_id)]["fn"] += 1
        level_counts[miss.golden.level]["fn"] += 1

    new_rule_candidate_count = 0
    valid_unlabeled_count = 0
    human_review_count = 0
    for triage in result.triage_results:
        if triage.verdict == "false_positive":
            category_counts[category_of(triage.predicted.rule_id)]["fp"] += 1
            level_counts[triage.predicted.level]["fp"] += 1
        elif triage.verdict == "new_rule_candidate":
            new_rule_candidate_count += 1
        elif triage.verdict == "valid_but_unlabeled":
            valid_unlabeled_count += 1
        else:
            human_review_count += 1

    def to_counts(counts: dict[str, int]) -> ConfusionCounts:
        return ConfusionCounts(
            true_positive=counts.get("tp", 0),
            false_negative=counts.get("fn", 0),
            false_positive=counts.get("fp", 0),
        )

    by_category = {category: to_counts(counts) for category, counts in category_counts.items()}
    by_level = {level: to_counts(counts) for level, counts in level_counts.items()}
    overall = ConfusionCounts(
        true_positive=sum(c.true_positive for c in by_category.values()),
        false_negative=sum(c.false_negative for c in by_category.values()),
        false_positive=sum(c.false_positive for c in by_category.values()),
    )
    return AggregateReport(
        overall=overall,
        by_category=by_category,
        by_level=by_level,
        new_rule_candidate_count=new_rule_candidate_count,
        valid_unlabeled_count=valid_unlabeled_count,
        human_review_count=human_review_count,
        excused_miss_count=excused_miss_count,
    )


@dataclass(frozen=True, slots=True)
class BaselineComparison:
    subject_recall: float | None
    subject_precision: float | None
    baseline_recall_avg: float | None
    baseline_precision_avg: float | None
    per_reviewer: dict[str, AggregateReport] = field(default_factory=dict)


def compare_to_human_baseline(
    subject: AggregateReport, baselines: dict[str, AggregateReport]
) -> BaselineComparison:
    recalls = [b.overall.recall for b in baselines.values() if b.overall.recall is not None]
    precisions = [b.overall.precision for b in baselines.values() if b.overall.precision is not None]
    return BaselineComparison(
        subject_recall=subject.overall.recall,
        subject_precision=subject.overall.precision,
        baseline_recall_avg=sum(recalls) / len(recalls) if recalls else None,
        baseline_precision_avg=sum(precisions) / len(precisions) if precisions else None,
        per_reviewer=baselines,
    )
