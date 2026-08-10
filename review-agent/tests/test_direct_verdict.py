from __future__ import annotations

from planqa_review.llm.base import CallStats
from planqa_review.rulebook import parse_rulebook
from planqa_review.structures.direct_verdict import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n"


class _ContentAwareLLM:
    """Responds based on prompt *content* (which rule_id appears in the rule block) rather
    than call order — direct_verdict dispatches one call per (tier, category) pair,
    concurrently, so a fixed response sequence can't be scripted deterministically."""

    def __init__(self, flagged_rule_id: str = "MI-01") -> None:
        self.model = "fake"
        self.usage: list[CallStats] = []
        self.calls: list[dict[str, str]] = []
        self._flagged_rule_id = flagged_rule_id

    def complete_json(self, *, system: str, prompt: str, cache_prefix: str | None = None):
        self.calls.append({"system": system, "prompt": prompt})
        self.usage.append(CallStats(elapsed_seconds=0.0, prompt_tokens=None, completion_tokens=None, total_tokens=None))
        if self._flagged_rule_id not in prompt:
            return {"violations": []}
        return {
            "violations": [
                {
                    "chunk_index": 0,
                    "rule_id": self._flagged_rule_id,
                    "original_text": "간단한 목적 설명입니다.",
                    "description": "목적이 구체적이지 않음",
                    "fix_direction": "목적: 사용자 재탐색 편의성을 높이기 위함.",
                    "excused": False,
                }
            ]
        }


class _LevelClaimingLLM:
    """Like _ContentAwareLLM, but every flagged violation claims a "level" field — proves
    the promotion actually reaches the final Issue through a real (non-fake) chunk/tier
    dispatch, not just the isolated document.py unit tests."""

    def __init__(self, flagged_rule_id: str, claimed_level: str) -> None:
        self.model = "fake"
        self.usage: list[CallStats] = []
        self.calls: list[dict[str, str]] = []
        self._flagged_rule_id = flagged_rule_id
        self._claimed_level = claimed_level

    def complete_json(self, *, system: str, prompt: str, cache_prefix: str | None = None):
        self.calls.append({"system": system, "prompt": prompt})
        self.usage.append(CallStats(elapsed_seconds=0.0, prompt_tokens=None, completion_tokens=None, total_tokens=None))
        if self._flagged_rule_id not in prompt:
            return {"violations": []}
        return {
            "violations": [
                {
                    "chunk_index": 0,
                    "rule_id": self._flagged_rule_id,
                    "original_text": "간단한 목적 설명입니다.",
                    "description": "목적이 구체적이지 않음",
                    "fix_direction": "목적: 사용자 재탐색 편의성을 높이기 위함.",
                    "excused": False,
                    "level": self._claimed_level,
                }
            ]
        }


class _RelationalLLM:
    """Scripts an LG-02 (relational category) violation with a related_location, and an
    MI-01 (non-relational) violation that supplies related_location anyway — the latter
    must be dropped since only LG/LF/GA categories carry a second location."""

    def __init__(self) -> None:
        self.model = "fake"
        self.usage: list[CallStats] = []
        self.calls: list[dict[str, str]] = []

    def complete_json(self, *, system: str, prompt: str, cache_prefix: str | None = None):
        self.calls.append({"system": system, "prompt": prompt})
        self.usage.append(CallStats(elapsed_seconds=0.0, prompt_tokens=None, completion_tokens=None, total_tokens=None))
        if "LG-02" in prompt:
            return {
                "violations": [
                    {
                        "chunk_index": 0,
                        "rule_id": "LG-02",
                        "original_text": "간단한 목적 설명입니다.",
                        "description": "상충 발생",
                        "fix_direction": "내용을 일치시킬 것",
                        "excused": False,
                        "related_location": "2. 배경",
                    }
                ]
            }
        if "MI-01" in prompt:
            return {
                "violations": [
                    {
                        "chunk_index": 0,
                        "rule_id": "MI-01",
                        "original_text": "간단한 목적 설명입니다.",
                        "description": "목적이 구체적이지 않음",
                        "fix_direction": "목적을 구체화할 것",
                        "excused": False,
                        "related_location": "이건 무시돼야 함",
                    }
                ]
            }
        return {"violations": []}


def test_review_document_dispatches_categories_independently(rulebook_path):
    """The core mechanic under test: each category gets its OWN single-pass call scoped to
    just that category's rules — no separate screen call at all, unlike cell3."""
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _ContentAwareLLM("MI-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm, max_workers=1)

    direct_events = [e for e in result.call_events if e.stage == "single_pass"]
    # 7 categories at Document + 8 at Logical Unit + 7 at Paragraph + 5 at Sentence = 27
    assert len(direct_events) == 27
    for event in direct_events:
        categories = {rule_id.split("-")[0] for rule_id in event.rule_ids}
        assert len(categories) == 1  # every call is scoped to exactly one category


def test_review_document_promotes_level_when_the_model_claims_a_coarser_one(rulebook_path):
    """MI is reviewed at all 4 tiers — a Sentence/Paragraph-tier call claiming "Logical
    Unit" should be promoted, but the Document-tier call (already coarsest) can't be
    promoted any further and stays put."""
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _LevelClaimingLLM("MI-01", claimed_level="Logical Unit")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm, max_workers=1)

    levels = {issue.level for issue in result.issues if issue.rule_id == "MI-01"}
    assert "Sentence" not in levels
    assert "Paragraph" not in levels
    assert "Logical Unit" in levels

    assert not any(e.stage == "screen" for e in result.call_events)
    assert not any(e.stage == "confirm" for e in result.call_events)
    assert result.global_context == ""  # no summary key in this fake's responses -> ""
    assert any(issue.rule_id == "MI-01" for issue in result.issues)
    assert result.tier_errors == ()


def test_review_document_reports_no_issues_when_nothing_flagged(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _ContentAwareLLM("NONEXISTENT-RULE")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm, max_workers=1)

    assert result.issues == ()


def test_review_document_populates_related_location_only_for_relational_categories(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _RelationalLLM()

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm, max_workers=1)

    by_rule = {issue.rule_id: issue for issue in result.issues}
    assert by_rule["LG-02"].related_location == "2. 배경"
    assert by_rule["MI-01"].related_location is None


def test_review_document_runs_with_real_concurrency(rulebook_path):
    """Same scenario as the first test but with the default thread pool (max_workers=4) —
    proves the concurrent dispatch itself doesn't corrupt shared state (events list)."""
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _ContentAwareLLM("MI-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm)

    assert any(issue.rule_id == "MI-01" for issue in result.issues)
    assert result.tier_errors == ()
