from __future__ import annotations

from planqa_review.llm.base import CallStats
from planqa_review.rulebook import parse_rulebook
from planqa_review.structures.cell3r import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n"


class _ContentAwareLLM:
    """Responds based on prompt content, not call order — cell3r dispatches one call per
    (tier, rule) pair, far more than baseline, and under real concurrency the order isn't
    deterministic."""

    def __init__(self, flagged_rule_id: str = "MI-01") -> None:
        self.model = "fake"
        self.usage: list[CallStats] = []
        self.calls: list[dict[str, str]] = []
        self._flagged_rule_id = flagged_rule_id

    def complete_json(self, *, system: str, prompt: str):
        self.calls.append({"system": system, "prompt": prompt})
        self.usage.append(CallStats(elapsed_seconds=0.0, prompt_tokens=None, completion_tokens=None, total_tokens=None))
        if "verdicts" not in system:  # screening call
            if f"Rule to check: {self._flagged_rule_id}" in prompt:
                return {"candidates": [{"chunk_index": 0, "quoted_text": "간단한 목적 설명입니다.", "reason": "목적 불명확"}]}
            return {"candidates": []}
        return {  # confirm call
            "verdicts": [
                {
                    "index": 0,
                    "violated": True,
                    "original_text": "간단한 목적 설명입니다.",
                    "description": "목적이 구체적이지 않음",
                    "fix_direction": "목적: 사용자 재탐색 편의성을 높이기 위함.",
                    "excused": False,
                }
            ]
        }


def test_review_document_dispatches_one_call_per_rule(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    screen_llm = _ContentAwareLLM("MI-01")
    confirm_llm = _ContentAwareLLM("MI-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, max_workers=1)

    screen_events = [e for e in result.call_events if e.stage == "screen"]
    # total rule count across all 4 tiers (with Absence Check exclusions applied):
    # Document=41 all rules; Logical Unit/Paragraph/Sentence exclude LG-01/TC-02 each.
    from planqa_review.tiers import rules_for_tier
    from planqa_review.schema import Level

    expected = sum(len(rules_for_tier(rulebook, level)) for level in (Level.DOCUMENT, Level.LOGICAL_UNIT, Level.PARAGRAPH, Level.SENTENCE))
    assert len(screen_events) == expected
    for event in screen_events:
        assert len(event.rule_ids) == 1  # every screen call is scoped to exactly one rule

    assert any(issue.rule_id == "MI-01" for issue in result.issues)
    assert result.tier_errors == ()


def test_review_document_skips_confirm_when_no_candidates_screened(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    screen_llm = _ContentAwareLLM("NONEXISTENT-RULE")
    confirm_llm = _ContentAwareLLM("NONEXISTENT-RULE")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, max_workers=1)

    assert result.issues == ()
    assert not any(e.stage == "confirm" for e in result.call_events)


def test_review_document_runs_with_real_concurrency(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    screen_llm = _ContentAwareLLM("MI-01")
    confirm_llm = _ContentAwareLLM("MI-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert any(issue.rule_id == "MI-01" for issue in result.issues)
    assert result.tier_errors == ()
