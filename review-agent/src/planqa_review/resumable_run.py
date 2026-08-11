from __future__ import annotations

import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from planqa_review.benchmark import resolve_source_path
from planqa_review.cost_guard import CostGuard
from planqa_review.diff_report import write_report
from planqa_review.experiment import DocumentRun, ExperimentConfig, ExperimentResult, ExperimentSummary, _summarize
from planqa_review.llm.base import LLMClient
from planqa_review.pipeline import ReviewResult
from planqa_review.rulebook import RuleBook
from planqa_review.run_stats import ModelUsage, RunStats, build_run_stats
from planqa_review.schema import Issue
from planqa_review.scoring import GoldenRow, ScoreCounts, ScoreResult, score_issues

ReviewFn = Callable[[str, str, RuleBook, LLMClient, LLMClient], ReviewResult]


def already_done_doc_ids(output_dir: Path, doc_ids: tuple[str, ...]) -> tuple[str, ...]:
    """A doc_id counts as already done once its review.json exists — this is the entire
    resumability mechanism: re-running with the same output_dir skips every doc_id that
    already has one, at zero API cost, no separate "resume" flag needed."""
    return tuple(doc_id for doc_id in doc_ids if (output_dir / doc_id / "review.json").exists())


def _issue_from_dict(data: dict) -> Issue:
    return Issue(
        doc_id=data["doc_id"],
        level=data["level"],
        rule_id=data["rule_id"],
        location=data["location"],
        description=data.get("description", ""),
        exception_ref=data.get("exception_ref"),
        source=data.get("source", ""),
        issue_id=data.get("issue_id"),
        original_text=data.get("original_text"),
        rationale=data.get("rationale"),
        fix_direction=data.get("fix_direction"),
        related_location=data.get("related_location"),
        related_original_text=data.get("related_original_text"),
    )


def _usage_from_dict(data: dict | None) -> ModelUsage:
    if not data:
        return ModelUsage(call_count=0, elapsed_seconds=0.0, total_tokens=None)
    return ModelUsage(
        call_count=data.get("call_count", 0), elapsed_seconds=data.get("elapsed_seconds", 0.0), total_tokens=data.get("total_tokens")
    )


# 이전 실행에서 이미 계산된 문서를 API 호출 없이 복원 — review.json에 저장된 issues+stats
# 만으로 DocumentRun을 재구성한다(재계산 비용 없음). call_events는 저장되지 않으므로 빈
# 튜플로 남지만, 이미 완료된 문서는 이번 실행의 신규 비용 집계에 반영할 게 없으니 무해함.
def _load_saved_document_run(doc_id: str, output_dir: Path, golden_rows: list[GoldenRow]) -> DocumentRun:
    payload = json.loads((output_dir / doc_id / "review.json").read_text(encoding="utf-8"))
    raw_issues = payload["issues"] if isinstance(payload, dict) else payload
    issues = tuple(_issue_from_dict(item) for item in raw_issues)
    stats_dict = payload.get("stats") if isinstance(payload, dict) else None
    stats = RunStats(
        profile=(stats_dict or {}).get("profile", ""),
        backend=(stats_dict or {}).get("backend", ""),
        screen_model=(stats_dict or {}).get("screen_model", ""),
        verify_model=(stats_dict or {}).get("verify_model", ""),
        rulebook_hash=(stats_dict or {}).get("rulebook_hash", ""),
        total_wall_seconds=0.0,
        screen=_usage_from_dict((stats_dict or {}).get("screen")),
        confirm=_usage_from_dict((stats_dict or {}).get("confirm")),
        by_stage={k: _usage_from_dict(v) for k, v in (stats_dict or {}).get("by_stage", {}).items()},
        by_tier={k: _usage_from_dict(v) for k, v in (stats_dict or {}).get("by_tier", {}).items()},
        by_rule={k: _usage_from_dict(v) for k, v in (stats_dict or {}).get("by_rule", {}).items()},
    )
    result = ReviewResult(doc_id=doc_id, global_context="", issues=issues)
    score = score_issues(doc_id, issues, golden_rows)
    return DocumentRun(doc_id=doc_id, result=result, stats=stats, score=score)


def run_resumable(
    doc_ids: tuple[str, ...],
    rulebook: RuleBook,
    rulebook_path: Path,
    source_dir: Path,
    output_dir: Path,
    golden_rows: list[GoldenRow],
    review_fn: ReviewFn,
    build_clients: Callable[[], tuple[LLMClient, LLMClient]],
    profile_label: str,
    backend_label: str,
    cost_guard: CostGuard,
    estimated_cost_per_doc_usd: float,
    max_workers: int = 5,
    deadline: float | None = None,
) -> tuple[ExperimentResult, list[str]]:
    """Resumable, bounded-concurrency runner for the full doc_ids sweep: doc_ids whose
    review.json already exists in output_dir are loaded back (zero cost, zero risk) instead
    of recomputed; the rest are launched through a ThreadPoolExecutor, but only after
    check_or_raise confirms the WHOLE remaining batch fits under the $7 cap using
    estimated_cost_per_doc_usd (a real per-doc average — see the 1-doc smoke test in the
    execution plan). This is the pre-flight check the cap depends on: once a call is made
    it's billed regardless of what happens after, so this can only stop a batch from
    *starting*, not partway through — each completed document's actual token usage is still
    recorded into cost_guard afterward so the next stage's pre-flight check sees real spend,
    not just the estimate.

    `deadline` (a time.perf_counter() value, matching what callers compare it against) stops
    *submitting new* documents once passed — already-submitted ones still finish normally
    (there's no clean way to abort a call already sent to the API, and each one is bounded by
    its own client-level retry/timeout anyway, so this only needs to stop new work from
    starting). Documents never submitted this call simply have no review.json yet, so the
    next run_resumable call picks them up automatically — this is what lets the 3-hour
    overall deadline degrade into "whatever got done, resumably" instead of a hard failure."""
    already_done = already_done_doc_ids(output_dir, doc_ids)
    remaining = tuple(doc_id for doc_id in doc_ids if doc_id not in already_done)

    documents: list[DocumentRun] = [_load_saved_document_run(doc_id, output_dir, golden_rows) for doc_id in already_done]
    errors: list[str] = []

    if remaining:
        cost_guard.check_or_raise(estimated_cost_per_doc_usd * len(remaining), stage=f"전체 실행({len(remaining)}문서 신규)")

        def run_one(doc_id: str) -> DocumentRun:
            document_text = resolve_source_path(source_dir, doc_id).read_text(encoding="utf-8")
            screen_llm, confirm_llm = build_clients()
            start = time.perf_counter()
            result = review_fn(doc_id, document_text, rulebook, screen_llm, confirm_llm)
            stats = build_run_stats(
                profile=profile_label,
                backend=backend_label,
                rulebook_path=rulebook_path,
                screen_llm=screen_llm,
                confirm_llm=confirm_llm,
                total_wall_seconds=time.perf_counter() - start,
                call_events=result.call_events,
            )
            score = score_issues(doc_id, result.issues, golden_rows)
            write_report(output_dir / doc_id, result, rulebook, stats)
            return DocumentRun(doc_id=doc_id, result=result, stats=stats, score=score)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for doc_id in remaining:
                if deadline is not None and time.perf_counter() >= deadline:
                    break
                futures[pool.submit(run_one, doc_id)] = doc_id
            for future in as_completed(futures):
                doc_id = futures[future]
                try:
                    doc_run = future.result()
                except Exception as error:  # noqa: BLE001 - one document's failure shouldn't sink the whole run
                    errors.append(f"{doc_id}: {error}")
                    continue
                documents.append(doc_run)
                cost_guard.record_actual_tokens((doc_run.stats.screen.total_tokens or 0) + (doc_run.stats.confirm.total_tokens or 0))

    order = {doc_id: i for i, doc_id in enumerate(doc_ids)}
    documents_sorted = tuple(sorted(documents, key=lambda doc: order[doc.doc_id]))
    total_wall_seconds = sum(doc.stats.total_wall_seconds for doc in documents_sorted)
    # A deadline hit before anything could even start (or a doc_ids list that resolves to
    # nothing new and nothing already done) leaves documents_sorted empty — _summarize
    # indexes documents[0], so this case needs its own placeholder summary rather than
    # crashing the whole run over having made zero progress.
    if documents_sorted:
        summary = _summarize(documents_sorted, 0.0, total_wall_seconds)
    else:
        empty_usage = ModelUsage(call_count=0, elapsed_seconds=0.0, total_tokens=None)
        summary = ExperimentSummary(
            profile=profile_label,
            backend=backend_label,
            screen_model="",
            verify_model="",
            temperature=0.0,
            rulebook_hash="",
            total_wall_seconds=0.0,
            screen=empty_usage,
            confirm=empty_usage,
            by_stage={},
            by_tier={},
            by_rule={},
            score=ScoreResult(overall=ScoreCounts(), by_rule={}, by_category={}),
        )
    experiment = ExperimentResult(
        config=ExperimentConfig(profile=profile_label, backend=backend_label, doc_ids=doc_ids),
        documents=documents_sorted,
        summary=summary,
    )
    return experiment, errors
