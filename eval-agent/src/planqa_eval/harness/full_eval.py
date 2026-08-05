from __future__ import annotations

import json
from pathlib import Path

from planqa_eval.aggregator import AggregateReport, BaselineComparison, aggregate, compare_to_human_baseline
from planqa_eval.llm.base import LLMClient
from planqa_eval.parsers.golden import parse_golden_dataset
from planqa_eval.parsers.review_sheet import parse_review_sheets
from planqa_eval.pipeline import PipelineResult, run_pipeline
from planqa_eval.rulebook import RuleBook
from planqa_eval.schema import Issue


class GateNotPassedError(RuntimeError):
    pass


def check_gate_passed(gate_report_path: Path) -> bool:
    if not gate_report_path.exists():
        return False
    data = json.loads(gate_report_path.read_text(encoding="utf-8"))
    return bool(data.get("passed"))


def run_full_evaluation(
    xlsx_path: Path,
    predicted: list[Issue],
    rulebook: RuleBook,
    source_dir: Path,
    llm: LLMClient,
    gate_report_path: Path,
    force: bool = False,
) -> tuple[PipelineResult, AggregateReport, BaselineComparison]:
    """2-2: only runs the full golden-set evaluation once the 2-1 gate has passed (or
    --force). Re-reads the golden dataset and Review1-6 sheets fresh — this is the point
    where the "no hardcoded document list" constraint actually gets exercised: as more
    golden rows get confirmed, this picks them up with no code change."""
    if not force and not check_gate_passed(gate_report_path):
        raise GateNotPassedError(
            f"2-1 confidence gate has not passed (no passing report at {gate_report_path}). "
            "Run `planqa-eval gate` first, or pass --force to override."
        )

    golden = parse_golden_dataset(xlsx_path)
    result = run_pipeline(golden, predicted, rulebook, source_dir, llm)
    report = aggregate(result)

    baselines: dict[str, AggregateReport] = {}
    for name, issues in parse_review_sheets(xlsx_path).items():
        if not issues:
            continue
        baseline_result = run_pipeline(golden, issues, rulebook, source_dir, llm)
        baselines[name] = aggregate(baseline_result)
    comparison = compare_to_human_baseline(report, baselines)

    return result, report, comparison
