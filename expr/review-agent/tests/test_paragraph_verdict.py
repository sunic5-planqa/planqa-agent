from __future__ import annotations

from planqa_review.llm.base import CallStats
from planqa_review.rulebook import parse_rulebook
from planqa_review.schema import Level
from planqa_review.structures.paragraph_verdict import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n\n## 2. 배경\n\n두번째 문단입니다.\n"


class _ContentAwareLLM:
    """Responds based on prompt *content* (which rule_id appears in the rule block) rather
    than call order — paragraph_verdict dispatches one call per (pass, category) pair,
    concurrently, so a fixed response sequence can't be scripted deterministically."""

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


def test_review_document_dispatches_normal_categories_at_paragraph_level(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _ContentAwareLLM("MI-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm, max_workers=1)

    mi_events = [e for e in result.call_events if "MI-01" in e.rule_ids]
    assert len(mi_events) == 1
    assert mi_events[0].tier == Level.PARAGRAPH
    assert any(issue.rule_id == "MI-01" and issue.level == Level.PARAGRAPH.value for issue in result.issues)


def test_review_document_dispatches_ga_at_document_level_only(rulebook_path):
    """GA can't be judged from a single paragraph — it must be a single whole-document pass,
    never a paragraph-level one, per the ② 청킹 실험 design."""
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _ContentAwareLLM("GA-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm, max_workers=1)

    ga_events = [e for e in result.call_events if "GA-01" in e.rule_ids]
    assert len(ga_events) == 1
    assert ga_events[0].tier == Level.DOCUMENT
    assert not any(e.tier == Level.PARAGRAPH and "GA-01" in e.rule_ids for e in result.call_events)
    assert any(issue.rule_id == "GA-01" and issue.level == Level.DOCUMENT.value for issue in result.issues)


def test_review_document_dispatches_absence_check_rule_at_document_level(rulebook_path):
    """LG-01 is an absence-check rule (tiers.ABSENCE_CHECK_RULE_IDS) — it goes to the
    document-wide pass even though the rest of the LG category is paragraph-level."""
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _ContentAwareLLM("LG-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm, max_workers=1)

    lg01_events = [e for e in result.call_events if "LG-01" in e.rule_ids]
    assert len(lg01_events) == 1
    assert lg01_events[0].tier == Level.DOCUMENT


def test_review_document_splits_lg_category_across_both_passes(rulebook_path):
    """LG-01 (absence-check) goes to the document pass; the rest of LG (e.g. LG-02) still
    goes through the normal paragraph pass — same category, two different dispatch calls."""
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = _ContentAwareLLM("LG-02")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm=confirm_llm, confirm_llm=confirm_llm, max_workers=1)

    lg_paragraph_events = [e for e in result.call_events if e.tier == Level.PARAGRAPH and any(r.startswith("LG-") for r in e.rule_ids)]
    assert lg_paragraph_events
    assert "LG-01" not in lg_paragraph_events[0].rule_ids
    assert any(issue.rule_id == "LG-02" and issue.level == Level.PARAGRAPH.value for issue in result.issues)


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
