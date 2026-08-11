from __future__ import annotations

import json

from planqa_review.diff_report import to_json_dict, to_markdown, write_report
from planqa_review.pipeline import ReviewResult
from planqa_review.run_stats import ModelUsage, RunStats
from planqa_review.rulebook import RuleBook, parse_rulebook
from planqa_review.schema import Issue


def _stats() -> RunStats:
    return RunStats(
        profile="gemini_lite",
        backend="gemini",
        screen_model="gemini-flash-lite-latest",
        verify_model="gemini-3.5-flash-lite",
        rulebook_hash="abc123def456",
        total_wall_seconds=12.34,
        screen=ModelUsage(call_count=4, elapsed_seconds=5.0, total_tokens=1000),
        confirm=ModelUsage(call_count=2, elapsed_seconds=7.34, total_tokens=None),
        by_stage={"screen": ModelUsage(call_count=4, elapsed_seconds=5.0, total_tokens=1000)},
        by_tier={"Document": ModelUsage(call_count=1, elapsed_seconds=1.0, total_tokens=200)},
        by_rule={"MI-01": ModelUsage(call_count=1, elapsed_seconds=1.0, total_tokens=200)},
    )


def _issue(**overrides) -> Issue:
    defaults = dict(
        doc_id="DOC-TEST",
        level="Paragraph",
        rule_id="MI-01",
        location="1. 목적",
        description="목적이 명시되지 않음",
        original_text="배경 설명입니다.",
        fix_direction="배경 설명입니다. 목적: 사용자 재탐색 편의성을 위해.",
    )
    defaults.update(overrides)
    return Issue(**defaults)


def test_to_json_dict_matches_adr_0001_contract_fields():
    result = ReviewResult(doc_id="DOC-TEST", global_context="요약", issues=(_issue(),))
    [item] = to_json_dict(result)
    for field in ("issue_id", "doc_id", "level", "rule_id", "location", "description", "exception_ref"):
        assert field in item
    assert item["issue_id"] == "REV-DOC-TEST-000"


def test_to_json_dict_includes_related_original_text():
    result = ReviewResult(
        doc_id="DOC-TEST",
        global_context="",
        issues=(_issue(related_location="2. 배경", related_original_text="배경 설명입니다."),),
    )
    [item] = to_json_dict(result)
    assert item["related_location"] == "2. 배경"
    assert item["related_original_text"] == "배경 설명입니다."


def test_to_markdown_renders_related_original_text(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    result = ReviewResult(
        doc_id="DOC-TEST",
        global_context="",
        issues=(_issue(related_location="2. 배경", related_original_text="배경 설명입니다."),),
    )
    markdown = to_markdown(result, rulebook)
    assert "관련 위치: 2. 배경" in markdown
    assert "관련 위치 원문: 배경 설명입니다." in markdown


def test_to_json_dict_keeps_explicit_issue_id():
    result = ReviewResult(doc_id="DOC-TEST", global_context="", issues=(_issue(issue_id="REV-007"),))
    [item] = to_json_dict(result)
    assert item["issue_id"] == "REV-007"


def test_to_markdown_reports_no_issues():
    result = ReviewResult(doc_id="DOC-TEST", global_context="", issues=())
    empty_rulebook = RuleBook(rules={}, categories=(), reference_exception_rule_ids=frozenset())
    markdown = to_markdown(result, empty_rulebook)
    assert "발견된 이슈가 없습니다" in markdown


def test_to_markdown_renders_diff_fence_and_category_label(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    result = ReviewResult(doc_id="DOC-TEST", global_context="문서 요약", issues=(_issue(),))
    markdown = to_markdown(result, rulebook)
    assert "```diff" in markdown
    assert "- 배경 설명입니다." in markdown
    assert "정보 누락" in markdown  # MI category label
    assert "문서 요약" in markdown


def test_write_report_writes_both_files(tmp_path, rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    result = ReviewResult(doc_id="DOC-TEST", global_context="요약", issues=(_issue(),))
    json_path, md_path = write_report(tmp_path / "out", result, rulebook)
    assert json_path.exists() and md_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data[0]["rule_id"] == "MI-01"


def test_to_json_dict_without_stats_stays_a_bare_list():
    result = ReviewResult(doc_id="DOC-TEST", global_context="", issues=(_issue(),))
    assert isinstance(to_json_dict(result), list)


def test_to_json_dict_with_stats_wraps_issues_and_adds_stats():
    result = ReviewResult(doc_id="DOC-TEST", global_context="", issues=(_issue(),))
    data = to_json_dict(result, _stats())
    assert isinstance(data, dict)
    assert data["issues"][0]["rule_id"] == "MI-01"
    assert data["stats"]["profile"] == "gemini_lite"
    assert data["stats"]["screen"]["call_count"] == 4
    assert data["stats"]["confirm"]["total_tokens"] is None


def test_to_markdown_with_stats_includes_stats_section(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    result = ReviewResult(doc_id="DOC-TEST", global_context="", issues=())
    markdown = to_markdown(result, rulebook, _stats())
    assert "## 실행 통계" in markdown
    assert "gemini_lite" in markdown
    assert "12.3초" in markdown


def test_write_report_with_stats_round_trips_through_json(tmp_path, rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    result = ReviewResult(doc_id="DOC-TEST", global_context="", issues=(_issue(),))
    json_path, md_path = write_report(tmp_path / "out", result, rulebook, _stats())
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["stats"]["backend"] == "gemini"
    assert "## 실행 통계" in md_path.read_text(encoding="utf-8")
