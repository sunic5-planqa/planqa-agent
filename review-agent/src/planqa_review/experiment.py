from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from planqa_review.benchmark import BENCHMARK_DOC_IDS, resolve_source_path
from planqa_review.diff_report import write_report
from planqa_review.llm.base import LLMClient
from planqa_review.llm.factory import build_llm_client
from planqa_review.models import PROFILES
from planqa_review.pipeline import ReviewResult, review_document
from planqa_review.rulebook import RuleBook
from planqa_review.run_stats import ModelUsage, RunStats, build_run_stats
from planqa_review.scoring import GoldenRow, ScoreCounts, ScoreResult, merge_score_results, score_issues


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    profile: str
    backend: str | None = None
    screen_model: str | None = None
    verify_model: str | None = None
    temperature: float = 0.0
    doc_ids: tuple[str, ...] = BENCHMARK_DOC_IDS


@dataclass(frozen=True, slots=True)
class DocumentRun:
    doc_id: str
    result: ReviewResult
    stats: RunStats
    score: ScoreResult


@dataclass(frozen=True, slots=True)
class ExperimentSummary:
    """The RunStats shape (see run_stats.py) summed across every document in the sweep,
    plus the benchmark-wide ScoreResult — this is the one object worth comparing between
    experiment runs (different profile/model/temperature)."""

    profile: str
    backend: str
    screen_model: str
    verify_model: str
    temperature: float
    rulebook_hash: str
    total_wall_seconds: float
    screen: ModelUsage
    confirm: ModelUsage
    by_stage: dict[str, ModelUsage]
    by_tier: dict[str, ModelUsage]
    by_rule: dict[str, ModelUsage]
    score: ScoreResult


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    config: ExperimentConfig
    documents: tuple[DocumentRun, ...]
    summary: ExperimentSummary


def _add_usage(a: ModelUsage, b: ModelUsage) -> ModelUsage:
    tokens = None
    if a.total_tokens is not None or b.total_tokens is not None:
        tokens = (a.total_tokens or 0) + (b.total_tokens or 0)
    return ModelUsage(call_count=a.call_count + b.call_count, elapsed_seconds=a.elapsed_seconds + b.elapsed_seconds, total_tokens=tokens)


def _merge_usage_maps(usage_maps: list[dict[str, ModelUsage]]) -> dict[str, ModelUsage]:
    merged: dict[str, ModelUsage] = {}
    for usage_map in usage_maps:
        for key, usage in usage_map.items():
            merged[key] = _add_usage(merged[key], usage) if key in merged else usage
    return merged


def _summarize(documents: tuple[DocumentRun, ...], temperature: float, total_wall_seconds: float) -> ExperimentSummary:
    first_stats = documents[0].stats
    screen_total = ModelUsage(call_count=0, elapsed_seconds=0.0, total_tokens=None)
    confirm_total = ModelUsage(call_count=0, elapsed_seconds=0.0, total_tokens=None)
    for doc in documents:
        screen_total = _add_usage(screen_total, doc.stats.screen)
        confirm_total = _add_usage(confirm_total, doc.stats.confirm)

    return ExperimentSummary(
        profile=first_stats.profile,
        backend=first_stats.backend,
        screen_model=first_stats.screen_model,
        verify_model=first_stats.verify_model,
        temperature=temperature,
        rulebook_hash=first_stats.rulebook_hash,
        total_wall_seconds=total_wall_seconds,
        screen=screen_total,
        confirm=confirm_total,
        by_stage=_merge_usage_maps([doc.stats.by_stage for doc in documents]),
        by_tier=_merge_usage_maps([doc.stats.by_tier for doc in documents]),
        by_rule=_merge_usage_maps([doc.stats.by_rule for doc in documents]),
        score=merge_score_results(doc.score for doc in documents),
    )


def run_experiment(
    config: ExperimentConfig,
    rulebook: RuleBook,
    rulebook_path: Path,
    source_dir: Path,
    golden_rows: list[GoldenRow],
    build_clients: Callable[[], tuple[LLMClient, LLMClient]] | None = None,
) -> ExperimentResult:
    """Sweeps `config.doc_ids` through `config.profile`, scoring each document against
    `golden_rows` — one fresh pair of LLM clients per document (`build_clients`, defaulting
    to the real factory) so per-document token/time stats never mix across documents. Tests
    override `build_clients` to hand back scripted clients instead of hitting a real backend."""
    profile = PROFILES[config.profile]
    backend_name = config.backend or os.environ.get("PLANQA_LLM_BACKEND") or "gemini"
    build_clients = build_clients or (
        lambda: (
            build_llm_client(config.backend, config.screen_model, config.temperature),
            build_llm_client(config.backend, config.verify_model, config.temperature),
        )
    )

    documents: list[DocumentRun] = []
    experiment_start = time.perf_counter()

    for doc_id in config.doc_ids:
        document_text = resolve_source_path(source_dir, doc_id).read_text(encoding="utf-8")
        screen_llm, confirm_llm = build_clients()

        doc_start = time.perf_counter()
        result = review_document(doc_id, document_text, rulebook, screen_llm, confirm_llm, profile)
        stats = build_run_stats(
            profile=config.profile,
            backend=backend_name,
            rulebook_path=rulebook_path,
            screen_llm=screen_llm,
            confirm_llm=confirm_llm,
            total_wall_seconds=time.perf_counter() - doc_start,
            call_events=result.call_events,
        )
        score = score_issues(doc_id, result.issues, golden_rows)
        documents.append(DocumentRun(doc_id=doc_id, result=result, stats=stats, score=score))

    summary = _summarize(tuple(documents), config.temperature, time.perf_counter() - experiment_start)
    return ExperimentResult(config=config, documents=tuple(documents), summary=summary)


def _usage_dict(usage: ModelUsage) -> dict:
    return {"call_count": usage.call_count, "elapsed_seconds": round(usage.elapsed_seconds, 2), "total_tokens": usage.total_tokens}


def _usage_map_dict(usage_map: dict[str, ModelUsage]) -> dict[str, dict]:
    return {key: _usage_dict(usage) for key, usage in usage_map.items()}


def _counts_dict(counts: ScoreCounts) -> dict:
    return {
        "true_positives": counts.true_positives,
        "false_positives": counts.false_positives,
        "false_negatives": counts.false_negatives,
        "recall": counts.recall,
        "precision": counts.precision,
    }


def _score_dict(score: ScoreResult) -> dict:
    return {
        "overall": _counts_dict(score.overall),
        "by_rule": {rule_id: _counts_dict(counts) for rule_id, counts in sorted(score.by_rule.items())},
        "by_category": {category: _counts_dict(counts) for category, counts in sorted(score.by_category.items())},
    }


def _summary_dict(summary: ExperimentSummary) -> dict:
    return {
        "profile": summary.profile,
        "backend": summary.backend,
        "screen_model": summary.screen_model,
        "verify_model": summary.verify_model,
        "temperature": summary.temperature,
        "rulebook_hash": summary.rulebook_hash,
        "total_wall_seconds": round(summary.total_wall_seconds, 2),
        "screen": _usage_dict(summary.screen),
        "confirm": _usage_dict(summary.confirm),
        "by_stage": _usage_map_dict(summary.by_stage),
        "by_tier": _usage_map_dict(summary.by_tier),
        "by_rule": _usage_map_dict(summary.by_rule),
        "score": _score_dict(summary.score),
    }


def _percent(value: float | None) -> str:
    return f"{value:.0%}" if value is not None else "—"


def summary_markdown(experiment: ExperimentResult) -> str:
    summary = experiment.summary
    score = summary.score.overall
    lines = [
        f"# 실험 결과 — profile `{summary.profile}` / backend `{summary.backend}`",
        "",
        f"- 스크리닝 모델: `{summary.screen_model}` / 정밀판정 모델: `{summary.verify_model}` / temperature: `{summary.temperature}`",
        f"- 룰북 해시: `{summary.rulebook_hash}`",
        f"- 문서 {len(experiment.documents)}건, 총 소요 시간 {summary.total_wall_seconds:.1f}초",
        f"- 전체 recall: {_percent(score.recall)} ({score.true_positives}/{score.true_positives + score.false_negatives}), "
        f"precision: {_percent(score.precision)} ({score.true_positives}/{score.true_positives + score.false_positives})",
        "",
        "## 카테고리별 recall/precision",
        "",
        "| 카테고리 | TP | FP | FN | Recall | Precision |",
        "|---|---|---|---|---|---|",
    ]
    for category, counts in sorted(summary.score.by_category.items()):
        lines.append(
            f"| {category} | {counts.true_positives} | {counts.false_positives} | {counts.false_negatives} "
            f"| {_percent(counts.recall)} | {_percent(counts.precision)} |"
        )
    lines += ["", "## 문서별 결과", "", "| 문서 | 지적 건수 | TP | FP | FN |", "|---|---|---|---|---|"]
    for doc in experiment.documents:
        counts = doc.score.overall
        lines.append(
            f"| {doc.doc_id} | {len(doc.result.issues)} | {counts.true_positives} | {counts.false_positives} "
            f"| {counts.false_negatives} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_experiment_report(output_dir: Path, experiment: ExperimentResult, rulebook: RuleBook) -> Path:
    """Writes one `review.json`/`review.md` per document (via diff_report.write_report,
    same shape a single `planqa-review review` run produces) plus a benchmark-wide
    `summary.json`/`summary.md` at the experiment root."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for doc in experiment.documents:
        write_report(output_dir / doc.doc_id, doc.result, rulebook, doc.stats)

    summary_json_path = output_dir / "summary.json"
    summary_md_path = output_dir / "summary.md"
    summary_json_path.write_text(json.dumps(_summary_dict(experiment.summary), ensure_ascii=False, indent=2), encoding="utf-8")
    summary_md_path.write_text(summary_markdown(experiment), encoding="utf-8")
    return output_dir
