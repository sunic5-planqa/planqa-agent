from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from planqa_eval.judge import judge_match
from planqa_eval.llm.base import LLMClient
from planqa_eval.matcher import match_all
from planqa_eval.prefilter import category_of
from planqa_eval.rulebook import RuleBook
from planqa_eval.schema import Issue


def issue_key(issue: Issue) -> str:
    return f"{issue.doc_id}::{issue.rule_id}::{issue.location}"


def stratified_sample(
    golden: list[Issue], rulebook: RuleBook, sample_size: int = 10, seed: int = 42
) -> list[Issue]:
    """Picks `sample_size` golden issues spread across Level, Rule category, and
    reference-exception-eligible-rule status as evenly as possible, by round-robining
    across those strata rather than sampling uniformly at random."""

    def strata_key(issue: Issue) -> tuple[str, str, bool]:
        return (issue.level, category_of(issue.rule_id), issue.rule_id in rulebook.reference_exception_rule_ids)

    buckets: dict[tuple[str, str, bool], list[Issue]] = defaultdict(list)
    for issue in golden:
        buckets[strata_key(issue)].append(issue)

    rng = random.Random(seed)
    bucket_list = list(buckets.values())
    for bucket in bucket_list:
        rng.shuffle(bucket)

    sample: list[Issue] = []
    target = min(sample_size, len(golden))
    i = 0
    while len(sample) < target and any(bucket_list):
        bucket = bucket_list[i % len(bucket_list)]
        if bucket:
            sample.append(bucket.pop())
        i += 1
    return sample


@dataclass(frozen=True, slots=True)
class HumanBlindLabel:
    """One human reviewer's independent, blind match + rubric score for a sampled golden
    issue — the ground truth the 2-1 gate checks Matcher/Judge agreement against."""

    golden_issue_id: str
    matched_predicted_issue_id: str | None
    root_cause_accuracy: int | None = None
    no_hallucination: int | None = None
    service_tone_fit: int | None = None
    actionability: int | None = None

    @property
    def score_average(self) -> float | None:
        scores = [
            self.root_cause_accuracy,
            self.no_hallucination,
            self.service_tone_fit,
            self.actionability,
        ]
        if any(s is None for s in scores):
            return None
        return sum(scores) / len(scores)


def save_human_label_template(sample: list[Issue], predicted: list[Issue], path: Path) -> None:
    template = [
        {
            "golden_issue_id": issue_key(golden),
            "golden_summary": f"{golden.doc_id} {golden.rule_id} {golden.location}: {golden.description}",
            "candidate_predicted_issue_ids": [
                p.issue_id for p in predicted if p.doc_id == golden.doc_id and p.issue_id
            ],
            "matched_predicted_issue_id": None,
            "root_cause_accuracy": None,
            "no_hallucination": None,
            "service_tone_fit": None,
            "actionability": None,
        }
        for golden in sample
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")


def load_human_labels(path: Path) -> list[HumanBlindLabel]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        HumanBlindLabel(
            golden_issue_id=item["golden_issue_id"],
            matched_predicted_issue_id=item.get("matched_predicted_issue_id"),
            root_cause_accuracy=item.get("root_cause_accuracy"),
            no_hallucination=item.get("no_hallucination"),
            service_tone_fit=item.get("service_tone_fit"),
            actionability=item.get("actionability"),
        )
        for item in data
    ]


@dataclass(frozen=True, slots=True)
class GateThresholds:
    matcher_agreement_min: float = 0.90
    judge_agreement_min: float = 0.80
    judge_tolerance: float = 1.0
    rule_level_accuracy_min: float = 1.0


@dataclass(frozen=True, slots=True)
class GateReport:
    sample_size: int
    matcher_agreement: float
    judge_agreement: float
    rule_level_accuracy: float
    passed: bool
    log: list[dict[str, Any]] = field(default_factory=list)


def run_confidence_gate(
    sample: list[Issue],
    predicted: list[Issue],
    human_labels: list[HumanBlindLabel],
    llm: LLMClient,
    thresholds: GateThresholds = GateThresholds(),
) -> GateReport:
    human_by_key = {label.golden_issue_id: label for label in human_labels}
    match_result = match_all(sample, predicted, llm)
    matched_by_golden_key = {issue_key(golden): pred for golden, pred in match_result.matched}

    matcher_agree = matcher_total = 0
    judge_agree = judge_total = 0
    rule_level_correct = rule_level_total = 0
    log: list[dict[str, Any]] = []

    for golden in sample:
        key = issue_key(golden)
        human = human_by_key.get(key)
        machine_match = matched_by_golden_key.get(key)

        human_match_id = human.matched_predicted_issue_id if human else None
        machine_match_id = machine_match.issue_id if machine_match else None
        matcher_total += 1
        agrees = human_match_id == machine_match_id
        matcher_agree += int(agrees)

        entry: dict[str, Any] = {
            "golden": key,
            "human_match": human_match_id,
            "matcher_match": machine_match_id,
            "matcher_agrees": agrees,
        }

        if machine_match is not None:
            rule_level_total += 1
            rule_level_correct += int(
                machine_match.rule_id == golden.rule_id and machine_match.level == golden.level
            )
            score = judge_match(golden, machine_match, llm)
            entry["judge_average"] = score.average
            if human is not None and human.score_average is not None:
                judge_total += 1
                entry["human_score_average"] = human.score_average
                judge_agree += int(abs(score.average - human.score_average) <= thresholds.judge_tolerance)

        log.append(entry)

    matcher_agreement = matcher_agree / matcher_total if matcher_total else 0.0
    judge_agreement = judge_agree / judge_total if judge_total else 0.0
    rule_level_accuracy = rule_level_correct / rule_level_total if rule_level_total else 0.0

    passed = (
        matcher_agreement >= thresholds.matcher_agreement_min
        and judge_agreement >= thresholds.judge_agreement_min
        and rule_level_accuracy >= thresholds.rule_level_accuracy_min
    )
    return GateReport(
        sample_size=len(sample),
        matcher_agreement=matcher_agreement,
        judge_agreement=judge_agreement,
        rule_level_accuracy=rule_level_accuracy,
        passed=passed,
        log=log,
    )
