from __future__ import annotations

from planqa_eval.aggregator import AggregateReport, ConfusionCounts
from planqa_eval.pipeline import PipelineResult
from planqa_eval.reporter import to_json_dict, to_markdown

_EMPTY_RESULT = PipelineResult(verified_matches=[], judge_scores=[], verified_misses=[], triage_results=[])
_EMPTY_REPORT = AggregateReport(overall=ConfusionCounts())

_STATS = {
    "profile": "gemini_lite",
    "backend": "gemini",
    "screen_model": "gemini-2.5-flash-lite",
    "verify_model": "gemini-2.5-flash",
    "rulebook_hash": "abc123",
    "total_wall_seconds": 12.3,
    "by_stage": {
        "context": {"call_count": 1, "elapsed_seconds": 1.0, "total_tokens": 100},
        "screen": {"call_count": 2, "elapsed_seconds": 4.1, "total_tokens": 500},
        "confirm": {"call_count": 3, "elapsed_seconds": 8.2, "total_tokens": 900},
    },
}


def test_to_json_dict_passes_through_review_stats_verbatim():
    data = to_json_dict(_EMPTY_RESULT, _EMPTY_REPORT, review_stats=_STATS)
    assert data["review_agent_stats"] == _STATS


def test_to_json_dict_review_stats_defaults_to_none():
    data = to_json_dict(_EMPTY_RESULT, _EMPTY_REPORT)
    assert data["review_agent_stats"] is None


def test_to_markdown_includes_review_stats_section_when_present():
    md = to_markdown(_EMPTY_RESULT, _EMPTY_REPORT, review_stats=_STATS)
    assert "## Review Agent Run Cost" in md
    assert "gemini_lite" in md
    assert "context" in md


def test_to_markdown_omits_review_stats_section_when_absent():
    md = to_markdown(_EMPTY_RESULT, _EMPTY_REPORT)
    assert "Review Agent Run Cost" not in md
