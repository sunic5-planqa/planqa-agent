from __future__ import annotations

import re

from planqa_review.benchmark import BENCHMARK_DOC_IDS
from planqa_review.rulebook import parse_rulebook
from planqa_review.structures.fewshot_bank import EXCEPTION_EXAMPLES, VIOLATION_EXAMPLES

# The benchmark doc_ids never appear literally in example text, but a doc_id substring
# match is still worth guarding against copy-paste mistakes pulling in a labeled excerpt.
_DOC_ID_PATTERN = re.compile(r"DOC-0(?:0[1-9]|1\d|20)\b")


def _all_example_texts():
    for examples in VIOLATION_EXAMPLES.values():
        for example in examples:
            yield example.original_text
            yield example.rationale
    for exception in EXCEPTION_EXAMPLES.values():
        yield exception.original_text
        yield exception.exception_condition
        yield exception.rationale


def test_no_benchmark_document_id_appears_in_any_example_text():
    for text in _all_example_texts():
        assert not _DOC_ID_PATTERN.search(text), text


def test_no_rule_has_more_than_two_violation_examples():
    for rule_id, examples in VIOLATION_EXAMPLES.items():
        assert 1 <= len(examples) <= 2, rule_id


def test_every_violation_rule_id_is_a_real_rule(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    for rule_id in VIOLATION_EXAMPLES:
        assert rule_id in rulebook.rules, rule_id


def test_every_exception_rule_id_is_a_real_rule(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    for rule_id in EXCEPTION_EXAMPLES:
        assert rule_id in rulebook.rules, rule_id


def test_ae03_and_mi05_have_no_violation_examples():
    # Confirmed during curation: every real golden-dataset violation example for these two
    # rules happens to live inside the scored benchmark (DOC-001..020) — no leakage-safe
    # example exists, and per project policy we never write a synthetic one to fill the gap.
    assert "AE-03" not in VIOLATION_EXAMPLES
    assert "MI-05" not in VIOLATION_EXAMPLES


def test_benchmark_doc_ids_module_matches_the_pattern_used_here():
    # Sanity check that the hand-written regex above actually matches the real benchmark
    # range, so the leakage test isn't silently checking against the wrong set.
    for doc_id in BENCHMARK_DOC_IDS:
        assert _DOC_ID_PATTERN.fullmatch(doc_id), doc_id
