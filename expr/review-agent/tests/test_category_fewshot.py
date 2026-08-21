from __future__ import annotations

from planqa_review.llm.base import CallStats
from planqa_review.rulebook import parse_rulebook
from planqa_review.schema import Level
from planqa_review.structures.category_fewshot import review_document

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


def test_review_document_never_leaks_rule_text_into_the_prompt(rulebook_path):
    """The whole point of this structure: the confirm prompt must not contain the rule's
    own defined text/exception wording — only rule_id + curated fewshot examples."""
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _ContentAwareLLM("MI-01")

    review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm, max_workers=1)

    mi01_rule = rulebook.rules["MI-01"]
    for call in confirm_llm.calls:
        if "MI-01" in call["prompt"]:
            assert mi01_rule.text not in call["prompt"]


def test_review_document_shares_an_identical_cache_prefix_across_categories_in_one_pass(rulebook_path):
    """Every category dispatched within the same pass must send the exact same
    cache_prefix text (only the per-category `prompt` should differ) — that's what lets a
    caching-capable backend actually get a cache hit across concurrent category calls."""
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _ContentAwareLLM("MI-01")

    review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm, max_workers=1)

    # "[1]" (a second numbered chunk) only appears in the paragraph pass's cache_prefix —
    # the document pass has exactly one whole-document chunk, "[0]", with no "[1]".
    paragraph_calls = [c for c in confirm_llm.calls if "[1]" in c["cache_prefix"]]
    assert len(paragraph_calls) >= 2  # several categories dispatched for the paragraph pass
    cache_prefixes = {c["cache_prefix"] for c in paragraph_calls}
    assert len(cache_prefixes) == 1  # identical across every category in that pass

    # the chunk text lives in cache_prefix, not in the per-category prompt
    for call in paragraph_calls:
        assert "간단한 목적 설명입니다." not in call["prompt"]


def test_review_document_flags_a_violation_at_paragraph_level(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _ContentAwareLLM("MI-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm, max_workers=1)

    assert any(issue.rule_id == "MI-01" and issue.level == Level.PARAGRAPH.value for issue in result.issues)


def test_review_document_dispatches_ga_at_document_level_only(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _ContentAwareLLM("GA-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm, max_workers=1)

    ga_events = [e for e in result.call_events if "GA-01" in e.rule_ids]
    assert len(ga_events) == 1
    assert ga_events[0].tier == Level.DOCUMENT
    assert any(issue.rule_id == "GA-01" and issue.level == Level.DOCUMENT.value for issue in result.issues)


def test_review_document_reports_no_issues_when_nothing_flagged(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _ContentAwareLLM("NONEXISTENT-RULE")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm, max_workers=1)

    assert result.issues == ()


def test_review_document_runs_with_real_concurrency(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _ContentAwareLLM("MI-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm)

    assert any(issue.rule_id == "MI-01" for issue in result.issues)
    assert result.tier_errors == ()
