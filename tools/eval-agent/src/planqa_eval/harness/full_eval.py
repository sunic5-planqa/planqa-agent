from __future__ import annotations

from pathlib import Path

from planqa_eval.aggregator import AggregateReport, BaselineComparison, aggregate, compare_to_human_baseline
from planqa_eval.ensemble import JudgeAssembly
from planqa_eval.llm.base import LLMClient
from planqa_eval.parsers.golden import parse_golden_dataset
from planqa_eval.parsers.review_sheet import parse_review_sheets
from planqa_eval.pipeline import PipelineResult, run_pipeline
from planqa_schemas.rulebook import RuleBook
from planqa_schemas.schema import Issue


def run_full_evaluation(
    xlsx_path: Path,
    predicted: list[Issue],
    rulebook: RuleBook,
    source_dir: Path,
    llm: LLMClient,
    judge_assembly: JudgeAssembly | None = None,
) -> tuple[PipelineResult, AggregateReport, BaselineComparison]:
    """Re-reads the golden dataset and Review1-6 sheets fresh — this is the point where the
    "no hardcoded document list" constraint actually gets exercised: as more golden rows get
    confirmed, this picks them up with no code change.

    judge_assembly, if given, only applies to the subject `predicted` run — not the Review1-4
    baseline loop below. Aggregator never reads judge_scores (recall/precision only), so
    ensembling the baselines' judge calls would just be 4x the cost for zero effect on any
    number this function returns.
    """
    golden = parse_golden_dataset(xlsx_path)
    result = run_pipeline(golden, predicted, rulebook, source_dir, llm, judge_assembly=judge_assembly)
    report = aggregate(result)

    baselines: dict[str, AggregateReport] = {}
    for name, issues in parse_review_sheets(xlsx_path).items():
        if not issues:
            continue
        baseline_result = run_pipeline(golden, issues, rulebook, source_dir, llm)
        baselines[name] = aggregate(baseline_result)
    comparison = compare_to_human_baseline(report, baselines)

    return result, report, comparison
