from __future__ import annotations

from conftest import ScriptedLLM

from planqa_review.document import Chunk
from planqa_review.models.gemini_lite.screener import rules_for_tier, screen_tier
from planqa_review.rulebook import parse_rulebook
from planqa_review.schema import Level


def _chunk(location: str = "1. 목적", text: str = "본문") -> Chunk:
    return Chunk(level=Level.LOGICAL_UNIT, location=location, text=text)


def test_rules_for_tier_matches_document_declared_categories(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    rules = rules_for_tier(rulebook, Level.LOGICAL_UNIT)
    categories = {rule.category for rule in rules}
    assert categories == {"LG", "LF", "TM", "AE", "MI"}


def test_rules_for_tier_empty_for_word_level(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    assert rules_for_tier(rulebook, Level.WORD) == []


def test_screen_tier_parses_valid_candidates(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    llm = ScriptedLLM(
        [{"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "본문", "reason": "목적 없음"}]}]
    )
    [candidate] = screen_tier([_chunk()], rulebook, Level.LOGICAL_UNIT, "", llm)
    assert candidate.chunk_index == 0
    assert candidate.rule_id == "MI-01"
    assert len(llm.calls) == 1


def test_screen_tier_drops_out_of_range_index_and_unknown_rule_id(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    llm = ScriptedLLM(
        [
            {
                "candidates": [
                    {"chunk_index": 5, "rule_id": "MI-01", "quoted_text": "x", "reason": "y"},
                    {"chunk_index": 0, "rule_id": "AE-99", "quoted_text": "x", "reason": "y"},
                ]
            }
        ]
    )
    assert screen_tier([_chunk()], rulebook, Level.LOGICAL_UNIT, "", llm) == []


def test_screen_tier_skips_llm_when_no_chunks(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    llm = ScriptedLLM([{"candidates": []}])
    assert screen_tier([], rulebook, Level.LOGICAL_UNIT, "", llm) == []
    assert llm.calls == []


def test_screen_tier_skips_llm_when_tier_has_no_rules(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    llm = ScriptedLLM([{"candidates": []}])
    assert screen_tier([_chunk()], rulebook, Level.WORD, "", llm) == []
    assert llm.calls == []
