from __future__ import annotations

from planqa_review.llm.base import CallStats
from planqa_review.rulebook import parse_rulebook
from planqa_review.structures.cell3 import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n"


class _ContentAwareLLM:
    """Unlike `ScriptedLLM`, this responds based on prompt *content* rather than strict
    call order — cell3 dispatches many more (and, under real concurrency, unordered)
    screen/confirm calls than baseline, one per (tier, category) pair, so a fixed response
    sequence can't be scripted deterministically."""

    def __init__(self, flagged_rule_id: str = "MI-01") -> None:
        self.model = "fake"
        self.usage: list[CallStats] = []
        self.calls: list[dict[str, str]] = []
        self._flagged_rule_id = flagged_rule_id

    def complete_json(self, *, system: str, prompt: str):
        self.calls.append({"system": system, "prompt": prompt})
        self.usage.append(CallStats(elapsed_seconds=0.0, prompt_tokens=None, completion_tokens=None, total_tokens=None))
        if "verdicts" not in system:  # screening call (confirm's JSON schema names "verdicts";
            # its prose also happens to say "most candidates should come back violated=false",
            # so checking for "candidates" here would misclassify confirm calls as screen calls)
            if self._flagged_rule_id in prompt:
                return {
                    "candidates": [
                        {"chunk_index": 0, "rule_id": self._flagged_rule_id, "quoted_text": "간단한 목적 설명입니다.", "reason": "목적 불명확"}
                    ]
                }
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


def test_review_document_dispatches_categories_independently(rulebook_path):
    """The core mechanic under test: each category gets its OWN screen/confirm call
    scoped to just that category's rules — unlike baseline, which bundles every category
    assigned to a tier into one call."""
    rulebook = parse_rulebook(rulebook_path)
    screen_llm = _ContentAwareLLM("MI-01")
    confirm_llm = _ContentAwareLLM("MI-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, max_workers=1)

    screen_events = [e for e in result.call_events if e.stage == "screen"]
    # 7 categories at Document + 8 at Logical Unit + 7 at Paragraph + 5 at Sentence = 27
    assert len(screen_events) == 27
    for event in screen_events:
        categories = {rule_id.split("-")[0] for rule_id in event.rule_ids}
        assert len(categories) == 1  # every screen call is scoped to exactly one category

    assert result.global_context == ""  # no summary key in this fake's responses -> ""
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
    """Same scenario as the first test but with the default thread pool (max_workers=4) —
    proves the concurrent dispatch itself doesn't corrupt shared state (events list,
    ScriptedLLM-style usage tracking) under real parallelism."""
    rulebook = parse_rulebook(rulebook_path)
    screen_llm = _ContentAwareLLM("MI-01")
    confirm_llm = _ContentAwareLLM("MI-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert any(issue.rule_id == "MI-01" for issue in result.issues)
    assert result.tier_errors == ()
