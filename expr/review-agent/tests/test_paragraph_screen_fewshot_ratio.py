from __future__ import annotations

import re

from planqa_review.llm.base import CallStats
from planqa_review.rulebook import parse_rulebook
from planqa_review.structures.fewshot_bank import EXCEPTION_EXAMPLES, EXCEPTION_EXAMPLES_RATIO
from planqa_review.structures.paragraph_screen_fewshot_ratio import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n\n## 2. 배경\n\n두번째 문단입니다.\n"


class _ContentAwareLLM:
    def __init__(self, flagged_rule_id: str = "MI-02") -> None:
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
                        {"chunk_index": 0, "rule_id": self._flagged_rule_id, "quoted_text": "간단한 목적 설명입니다.", "reason": "불명확"}
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


def test_review_document_gives_two_excused_examples_where_baseline_gives_one(rulebook_path):
    """MI-02 has >=2 real exception candidates — this is the whole point of the ratio
    structure: same violation examples as the baseline, but 2 exception examples instead
    of 1 (isolated A/B against paragraph_screen_fewshot)."""
    assert len(EXCEPTION_EXAMPLES["MI-02"]) == 1
    assert len(EXCEPTION_EXAMPLES_RATIO["MI-02"]) == 2

    rulebook = parse_rulebook(rulebook_path)
    screen_llm = _ContentAwareLLM("MI-02")
    confirm_llm = _ContentAwareLLM("MI-02")

    review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, max_workers=1)

    screen_calls_for_mi = [c for c in screen_llm.calls if "MI-02 (" in c["prompt"]]
    assert screen_calls_for_mi
    for call in screen_calls_for_mi:
        # Isolate MI-02's own block — the call bundles every rule in the MI category, each
        # with its own EXCUSED example count, so counting across the whole prompt would
        # double-count other MI-* rules' exceptions too. Split on the next rule-header line
        # (two-space indent + RULE-ID pattern), not just "\n  " — the block's own bullet
        # lines are four-space indented and would otherwise match a naive "\n  " split.
        after_header = call["prompt"].split("MI-02 (", 1)[1]
        mi02_block = re.split(r"\n {2}[A-Z]{2,3}-\d{2} \(", after_header, maxsplit=1)[0]
        assert mi02_block.count("EXCUSED example") == 2


def test_review_document_dispatches_normal_categories_at_paragraph_level(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    screen_llm = _ContentAwareLLM("MI-02")
    confirm_llm = _ContentAwareLLM("MI-02")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, max_workers=1)

    assert any(issue.rule_id == "MI-02" for issue in result.issues)
