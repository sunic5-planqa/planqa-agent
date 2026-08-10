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


def _scope_to_predicted_docs(golden: list[Issue], predicted: list[Issue]) -> list[Issue]:
    # Scoring against the whole golden set when `predicted` only covers a handful of
    # documents makes every un-reviewed document's golden rows count as automatic misses,
    # crushing "overall" recall/precision toward 0 regardless of how the reviewed documents
    # actually did. Score only against documents `predicted` actually covers instead. If
    # predicted is empty we can't tell which document(s) were intended, so fall back to the
    # full set rather than silently scoping to nothing (which would look artificially
    # perfect — 0 golden rows means 0 false negatives).
    if not predicted:
        return golden
    doc_ids = {issue.doc_id for issue in predicted}
    return [g for g in golden if g.doc_id in doc_ids]


def run_full_evaluation(
    xlsx_path: Path,
    predicted: list[Issue],
    rulebook: RuleBook,
    source_dir: Path,
    llm: LLMClient,
    judge_assembly: JudgeAssembly | None = None,
    include_baseline: bool = False,
) -> tuple[PipelineResult, AggregateReport, BaselineComparison | None]:
    """Re-reads the golden dataset fresh — this is the point where the "no hardcoded
    document list" constraint actually gets exercised: as more golden rows get confirmed,
    this picks them up with no code change.

    include_baseline defaults to False: the Review1-6 human-baseline loop re-runs the full
    judge/matcher pipeline once per reviewer sheet against the same golden set, which is
    several times the cost/time of just scoring `predicted` — not something a normal
    "how good is this run" check needs, and it's what was burning through the free-tier
    Gemini quota on every `evaluate` call. Pass include_baseline=True to get it back.

    judge_assembly, if given, only applies to the subject `predicted` run — not the Review1-4
    baseline loop below. Aggregator never reads judge_scores (recall/precision only), so
    ensembling the baselines' judge calls would just be 4x the cost for zero effect on any
    number this function returns.
    """
    golden = parse_golden_dataset(xlsx_path)
    scoped_golden = _scope_to_predicted_docs(golden, predicted)
    result = run_pipeline(scoped_golden, predicted, rulebook, source_dir, llm, judge_assembly=judge_assembly)
    report = aggregate(result)

    if not include_baseline:
        return result, report, None

    # Same scope as the subject run — comparing "subject on docs X" against "reviewer on
    # every doc they ever touched" would be exactly the mismatch this function just fixed,
    # one level up.
    baselines: dict[str, AggregateReport] = {}
    for name, issues in parse_review_sheets(xlsx_path).items():
        if not issues:
            continue
        baseline_result = run_pipeline(scoped_golden, issues, rulebook, source_dir, llm)
        baselines[name] = aggregate(baseline_result)
    comparison = compare_to_human_baseline(report, baselines)

    return result, report, comparison
