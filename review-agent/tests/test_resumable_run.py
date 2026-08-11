from __future__ import annotations

import time

import pytest

from planqa_review.cost_guard import CostCapExceeded, CostGuard
from planqa_review.diff_report import write_report
from planqa_review.pipeline import ReviewResult
from planqa_review.resumable_run import already_done_doc_ids, run_resumable
from planqa_review.rulebook import parse_rulebook
from planqa_review.run_stats import ModelUsage, RunStats
from planqa_review.schema import Issue


def _issue(doc_id: str, rule_id: str = "MI-01") -> Issue:
    return Issue(doc_id=doc_id, level="Paragraph", rule_id=rule_id, location="1. 목적", description="d", original_text="x")


def _stats() -> RunStats:
    return RunStats(
        profile="bundled_screen_hybrid",
        backend="anthropic",
        screen_model="gemini-flash-lite-latest",
        verify_model="claude-sonnet-5",
        rulebook_hash="abc123",
        total_wall_seconds=1.0,
        screen=ModelUsage(call_count=1, elapsed_seconds=0.5, total_tokens=1000),
        confirm=ModelUsage(call_count=1, elapsed_seconds=0.5, total_tokens=2000),
        by_stage={},
        by_tier={},
        by_rule={},
    )


class _FakeLLM:
    def __init__(self, model: str = "fake") -> None:
        self.model = model
        self.usage = []


def _build_clients():
    return _FakeLLM("screen"), _FakeLLM("confirm")


def test_already_done_doc_ids_finds_only_docs_with_a_saved_review_json(tmp_path, rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    write_report(tmp_path / "DOC-001", ReviewResult(doc_id="DOC-001", global_context="", issues=(_issue("DOC-001"),)), rulebook, _stats())

    done = already_done_doc_ids(tmp_path, ("DOC-001", "DOC-002"))
    assert done == ("DOC-001",)


def test_run_resumable_skips_already_done_docs_without_calling_review_fn(tmp_path, rulebook_path, source_dir):
    rulebook = parse_rulebook(rulebook_path)
    write_report(tmp_path / "DOC-001", ReviewResult(doc_id="DOC-001", global_context="", issues=(_issue("DOC-001"),)), rulebook, _stats())

    calls: list[str] = []

    def review_fn(doc_id, text, rb, screen_llm, confirm_llm):
        calls.append(doc_id)
        return ReviewResult(doc_id=doc_id, global_context="", issues=(_issue(doc_id),))

    experiment, errors = run_resumable(
        doc_ids=("DOC-001", "DOC-002"),
        rulebook=rulebook,
        rulebook_path=rulebook_path,
        source_dir=source_dir,
        output_dir=tmp_path,
        golden_rows=[],
        review_fn=review_fn,
        build_clients=_build_clients,
        profile_label="bundled_screen_hybrid",
        backend_label="anthropic",
        cost_guard=CostGuard(),
        estimated_cost_per_doc_usd=0.01,
    )

    assert calls == ["DOC-002"]  # DOC-001 skipped entirely — zero cost, zero risk
    assert errors == []
    assert [doc.doc_id for doc in experiment.documents] == ["DOC-001", "DOC-002"]
    assert [issue.rule_id for issue in experiment.documents[0].result.issues] == ["MI-01"]


def test_run_resumable_writes_a_review_json_for_newly_computed_docs(tmp_path, rulebook_path, source_dir):
    rulebook = parse_rulebook(rulebook_path)

    def review_fn(doc_id, text, rb, screen_llm, confirm_llm):
        return ReviewResult(doc_id=doc_id, global_context="", issues=(_issue(doc_id),))

    run_resumable(
        doc_ids=("DOC-001",),
        rulebook=rulebook,
        rulebook_path=rulebook_path,
        source_dir=source_dir,
        output_dir=tmp_path,
        golden_rows=[],
        review_fn=review_fn,
        build_clients=_build_clients,
        profile_label="bundled_screen_hybrid",
        backend_label="anthropic",
        cost_guard=CostGuard(),
        estimated_cost_per_doc_usd=0.01,
    )

    assert (tmp_path / "DOC-001" / "review.json").exists()
    # a second run against the same output_dir must now skip it entirely
    calls: list[str] = []

    def review_fn_2(doc_id, text, rb, screen_llm, confirm_llm):
        calls.append(doc_id)
        return ReviewResult(doc_id=doc_id, global_context="", issues=())

    run_resumable(
        doc_ids=("DOC-001",),
        rulebook=rulebook,
        rulebook_path=rulebook_path,
        source_dir=source_dir,
        output_dir=tmp_path,
        golden_rows=[],
        review_fn=review_fn_2,
        build_clients=_build_clients,
        profile_label="bundled_screen_hybrid",
        backend_label="anthropic",
        cost_guard=CostGuard(),
        estimated_cost_per_doc_usd=0.01,
    )
    assert calls == []


def test_run_resumable_raises_before_launching_when_estimated_cost_exceeds_the_cap(tmp_path, rulebook_path, source_dir):
    rulebook = parse_rulebook(rulebook_path)
    calls: list[str] = []

    def review_fn(doc_id, text, rb, screen_llm, confirm_llm):
        calls.append(doc_id)
        return ReviewResult(doc_id=doc_id, global_context="", issues=())

    with pytest.raises(CostCapExceeded):
        run_resumable(
            doc_ids=("DOC-001", "DOC-002"),
            rulebook=rulebook,
            rulebook_path=rulebook_path,
            source_dir=source_dir,
            output_dir=tmp_path,
            golden_rows=[],
            review_fn=review_fn,
            build_clients=_build_clients,
            profile_label="bundled_screen_hybrid",
            backend_label="anthropic",
            cost_guard=CostGuard(cap_usd=1.0),
            estimated_cost_per_doc_usd=10.0,  # 2 docs * $10 >> $1 cap
        )

    assert calls == []  # nothing launched — the guard fires before any real call


def test_run_resumable_collects_per_document_errors_without_losing_other_documents(tmp_path, rulebook_path, source_dir):
    rulebook = parse_rulebook(rulebook_path)

    def review_fn(doc_id, text, rb, screen_llm, confirm_llm):
        if doc_id == "DOC-002":
            raise RuntimeError("boom")
        return ReviewResult(doc_id=doc_id, global_context="", issues=(_issue(doc_id),))

    experiment, errors = run_resumable(
        doc_ids=("DOC-001", "DOC-002"),
        rulebook=rulebook,
        rulebook_path=rulebook_path,
        source_dir=source_dir,
        output_dir=tmp_path,
        golden_rows=[],
        review_fn=review_fn,
        build_clients=_build_clients,
        profile_label="bundled_screen_hybrid",
        backend_label="anthropic",
        cost_guard=CostGuard(),
        estimated_cost_per_doc_usd=0.01,
    )

    assert len(errors) == 1 and "DOC-002" in errors[0]
    assert [doc.doc_id for doc in experiment.documents] == ["DOC-001"]


def test_run_resumable_updates_the_cost_guard_with_actual_token_usage(tmp_path, rulebook_path, source_dir):
    rulebook = parse_rulebook(rulebook_path)

    def review_fn(doc_id, text, rb, screen_llm, confirm_llm):
        screen_llm.usage.append(_TokenStats(1000))
        confirm_llm.usage.append(_TokenStats(2000))
        return ReviewResult(doc_id=doc_id, global_context="", issues=())

    guard = CostGuard()
    run_resumable(
        doc_ids=("DOC-001",),
        rulebook=rulebook,
        rulebook_path=rulebook_path,
        source_dir=source_dir,
        output_dir=tmp_path,
        golden_rows=[],
        review_fn=review_fn,
        build_clients=_build_clients,
        profile_label="bundled_screen_hybrid",
        backend_label="anthropic",
        cost_guard=guard,
        estimated_cost_per_doc_usd=0.01,
    )

    assert guard.spent_usd > 0  # real token usage from the (fake) LLM clients got recorded


def test_run_resumable_stops_submitting_new_docs_once_the_deadline_has_passed(tmp_path, rulebook_path, source_dir):
    rulebook = parse_rulebook(rulebook_path)
    calls: list[str] = []

    def review_fn(doc_id, text, rb, screen_llm, confirm_llm):
        calls.append(doc_id)
        return ReviewResult(doc_id=doc_id, global_context="", issues=())

    experiment, errors = run_resumable(
        doc_ids=("DOC-001", "DOC-002", "DOC-003"),
        rulebook=rulebook,
        rulebook_path=rulebook_path,
        source_dir=source_dir,
        output_dir=tmp_path,
        golden_rows=[],
        review_fn=review_fn,
        build_clients=_build_clients,
        profile_label="bundled_screen_hybrid",
        backend_label="anthropic",
        cost_guard=CostGuard(),
        estimated_cost_per_doc_usd=0.01,
        deadline=time.perf_counter() - 1,  # already in the past — nothing new should launch
    )

    assert calls == []
    assert errors == []
    assert experiment.documents == ()
    # none of them have a review.json yet, so a later resumable call would retry all three
    assert already_done_doc_ids(tmp_path, ("DOC-001", "DOC-002", "DOC-003")) == ()


class _TokenStats:
    def __init__(self, total_tokens: int) -> None:
        self.total_tokens = total_tokens
        self.elapsed_seconds = 0.1
        self.prompt_tokens = total_tokens
        self.completion_tokens = 0
