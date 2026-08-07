from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from planqa_eval.aggregator import AggregateReport, BaselineComparison, ConfusionCounts
from planqa_eval.pipeline import PipelineResult


def _counts_dict(counts: ConfusionCounts) -> dict[str, Any]:
    return {
        "true_positive": counts.true_positive,
        "false_negative": counts.false_negative,
        "false_positive": counts.false_positive,
        "recall": counts.recall,
        "precision": counts.precision,
    }


def _documents(result: PipelineResult) -> dict[str, dict[str, list[dict[str, Any]]]]:
    documents: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"matches": [], "misses": [], "fp_candidates": []}
    )

    for verified, judged in zip(result.verified_matches, result.judge_scores, strict=True):
        documents[verified.golden.doc_id]["matches"].append(
            {
                "location": verified.golden.location,
                "rule_id": verified.golden.rule_id,
                "predicted_rule_id": verified.predicted.rule_id,
                "level": verified.golden.level,
                "predicted_level": verified.predicted.level,
                "rule_id_match": verified.rule_id_match,
                "level_match": verified.level_match,
                "judge_average": judged.average,
            }
        )

    for miss in result.verified_misses:
        documents[miss.golden.doc_id]["misses"].append(
            {
                "location": miss.golden.location,
                "rule_id": miss.golden.rule_id,
                "level": miss.golden.level,
                "excused": miss.excused,
                "excuse_reason": miss.excuse_reason,
            }
        )

    for triage in result.triage_results:
        documents[triage.predicted.doc_id]["fp_candidates"].append(
            {
                "location": triage.predicted.location,
                "rule_id": triage.predicted.rule_id,
                "level": triage.predicted.level,
                "verdict": triage.verdict,
                "reasoning": triage.reasoning,
            }
        )

    return dict(documents)


def to_json_dict(
    result: PipelineResult,
    report: AggregateReport,
    baseline: BaselineComparison | None = None,
    review_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "summary": {
            "overall": _counts_dict(report.overall),
            "new_rule_candidate_count": report.new_rule_candidate_count,
            "human_review_count": report.human_review_count,
            "excused_miss_count": report.excused_miss_count,
        },
        "by_category": {cat: _counts_dict(c) for cat, c in sorted(report.by_category.items())},
        "by_level": {level: _counts_dict(c) for level, c in sorted(report.by_level.items())},
        "baseline_comparison": (
            {
                "subject_recall": baseline.subject_recall,
                "subject_precision": baseline.subject_precision,
                "human_baseline_recall_avg": baseline.baseline_recall_avg,
                "human_baseline_precision_avg": baseline.baseline_precision_avg,
                "per_reviewer": {
                    name: _counts_dict(r.overall) for name, r in baseline.per_reviewer.items()
                },
            }
            if baseline
            else None
        ),
        "review_agent_stats": review_stats,
        "documents": _documents(result),
    }


def _pct(value: float | None) -> str:
    return f"{value:.0%}" if value is not None else "—"


def _counts_table_row(label: str, counts: ConfusionCounts) -> str:
    return (
        f"| {label} | {counts.true_positive} | {counts.false_negative} | "
        f"{counts.false_positive} | {_pct(counts.recall)} | {_pct(counts.precision)} |"
    )


def _usage_table_row(label: str, usage: dict[str, Any]) -> str:
    tokens = usage.get("total_tokens")
    return f"| {label} | {usage.get('call_count', '—')} | {usage.get('elapsed_seconds', '—')} | {tokens if tokens is not None else '—'} |"


def _review_stats_section(review_stats: dict[str, Any] | None) -> list[str]:
    # Pass-through display only — review-agent measured this, eval-agent just surfaces it
    # next to the quality numbers so the two don't live in separate files.
    if not review_stats:
        return []
    lines = [
        "## Review Agent Run Cost",
        "",
        f"- profile={review_stats.get('profile')} backend={review_stats.get('backend')} "
        f"screen_model={review_stats.get('screen_model')} verify_model={review_stats.get('verify_model')} "
        f"rulebook_hash={review_stats.get('rulebook_hash')}",
        f"- total_wall_seconds={review_stats.get('total_wall_seconds')}",
        "",
        "| Stage | Calls | Elapsed (s) | Tokens |",
        "|---|---|---|---|",
    ]
    for stage, usage in sorted(review_stats.get("by_stage", {}).items()):
        lines.append(_usage_table_row(stage, usage))
    lines += ["", "Per-tier/per-rule cost breakdown is in report.json's `review_agent_stats`.", ""]
    return lines


def to_markdown(
    result: PipelineResult,
    report: AggregateReport,
    baseline: BaselineComparison | None = None,
    review_stats: dict[str, Any] | None = None,
) -> str:
    lines = ["# PlanQA Evaluation Report", ""]

    lines += ["## Summary", "", "| | TP | FN | FP | Recall | Precision |", "|---|---|---|---|---|---|"]
    lines.append(_counts_table_row("Overall", report.overall))
    lines += [
        "",
        f"- New-rule candidates (excluded from precision): {report.new_rule_candidate_count}",
        f"- Sent to human review queue: {report.human_review_count}",
        f"- Excused misses (valid reference exception): {report.excused_miss_count}",
        "",
    ]
    lines += _review_stats_section(review_stats)

    lines += [
        "## By Rule Category",
        "",
        "| Category | TP | FN | FP | Recall | Precision |",
        "|---|---|---|---|---|---|",
    ]
    for category, counts in sorted(report.by_category.items()):
        lines.append(_counts_table_row(category, counts))
    lines.append("")

    lines += ["## By Level", "", "| Level | TP | FN | FP | Recall | Precision |", "|---|---|---|---|---|---|"]
    for level, counts in sorted(report.by_level.items()):
        lines.append(_counts_table_row(level, counts))
    lines.append("")

    if baseline:
        lines += [
            "## Vs. Human Baseline (Review1-4)",
            "",
            f"- Subject recall / precision: {_pct(baseline.subject_recall)} / {_pct(baseline.subject_precision)}",
            f"- Human baseline avg recall / precision: "
            f"{_pct(baseline.baseline_recall_avg)} / {_pct(baseline.baseline_precision_avg)}",
            "",
        ]

    lines += ["## Per-Document Detail", ""]
    for doc_id, buckets in sorted(_documents(result).items()):
        lines.append(f"### {doc_id}")
        for match in buckets["matches"]:
            status = "✅" if match["rule_id_match"] and match["level_match"] else "⚠️"
            lines.append(
                f"- {status} `{match['location']}` golden={match['rule_id']}/{match['level']} "
                f"predicted={match['predicted_rule_id']}/{match['predicted_level']} "
                f"judge_avg={match['judge_average']:.1f}"
            )
        for miss in buckets["misses"]:
            tag = "excused" if miss["excused"] else "FN"
            lines.append(f"- ❌ [{tag}] `{miss['location']}` {miss['rule_id']}/{miss['level']}")
        for fp in buckets["fp_candidates"]:
            lines.append(f"- ❓ [{fp['verdict']}] `{fp['location']}` {fp['rule_id']}/{fp['level']}")
        lines.append("")

    return "\n".join(lines)


def write_report(
    output_dir: Path,
    result: PipelineResult,
    report: AggregateReport,
    baseline: BaselineComparison | None = None,
    review_stats: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(
        json.dumps(to_json_dict(result, report, baseline, review_stats), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(to_markdown(result, report, baseline, review_stats), encoding="utf-8")
    return json_path, md_path
