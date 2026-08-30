from __future__ import annotations

from planqa_review.llm.base import CallStats
from planqa_review.rulebook import parse_rulebook
from planqa_review.schema import Level
from planqa_review.structures.paragraph_screen_hybrid import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n\n## 2. 배경\n\n두번째 문단입니다.\n"


class _ContentAwareLLM:
    def __init__(self, flagged_rule_id: str = "MI-01") -> None:
        self.model = "fake"
        self.usage: list[CallStats] = []
        self.calls: list[dict[str, str]] = []
        self._flagged_rule_id = flagged_rule_id

    def complete_json(self, *, system: str, prompt: str, cache_prefix: str | None = None):
        self.calls.append({"system": system, "prompt": prompt, "cache_prefix": cache_prefix or ""})
        self.usage.append(CallStats(elapsed_seconds=0.0, prompt_tokens=None, completion_tokens=None, total_tokens=None))
        if "verdicts" not in system:  # screening call
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


def test_review_document_gives_both_rule_text_and_fewshot_examples_in_both_stages(rulebook_path):
    """The whole point of this structure (unlike paragraph_screen_fewshot): the rule's own
    defined text must be present alongside the curated examples, in both screen and confirm."""
    rulebook = parse_rulebook(rulebook_path)
    screen_llm = _ContentAwareLLM("MI-01")
    confirm_llm = _ContentAwareLLM("MI-01")
    mi01_rule = rulebook.rules["MI-01"]

    review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, max_workers=1)

    screen_calls_with_rule = [c for c in screen_llm.calls if mi01_rule.rule_id in c["prompt"]]
    assert screen_calls_with_rule
    assert all(mi01_rule.text in c["prompt"] for c in screen_calls_with_rule)
    confirm_calls_with_rule = [c for c in confirm_llm.calls if mi01_rule.rule_id in c["prompt"]]
    assert confirm_calls_with_rule
    assert all(mi01_rule.text in c["prompt"] for c in confirm_calls_with_rule)


def test_review_document_dispatches_normal_categories_at_paragraph_level(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    screen_llm = _ContentAwareLLM("MI-01")
    confirm_llm = _ContentAwareLLM("MI-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, max_workers=1)

    mi_events = [e for e in result.call_events if "MI-01" in e.rule_ids]
    assert any(e.tier == Level.PARAGRAPH and e.stage == "screen" for e in mi_events)
    assert any(e.tier == Level.PARAGRAPH and e.stage == "confirm" for e in mi_events)
    assert any(issue.rule_id == "MI-01" and issue.level == Level.PARAGRAPH.value for issue in result.issues)


def test_review_document_dispatches_ga_at_document_level_only(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    screen_llm = _ContentAwareLLM("GA-01")
    confirm_llm = _ContentAwareLLM("GA-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, max_workers=1)

    ga_events = [e for e in result.call_events if "GA-01" in e.rule_ids]
    assert ga_events
    assert all(e.tier == Level.DOCUMENT for e in ga_events)
    assert any(issue.rule_id == "GA-01" and issue.level == Level.DOCUMENT.value for issue in result.issues)


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
