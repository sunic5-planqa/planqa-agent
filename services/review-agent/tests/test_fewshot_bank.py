from __future__ import annotations

import re

from planqa_schemas.rulebook import parse_rulebook
from planqa_review.structures.fewshot_bank import (
    ALL_EXCEPTION_CANDIDATES,
    ALL_VIOLATION_CANDIDATES,
    EXCEPTION_EXAMPLES,
    EXCEPTION_EXAMPLES_RATIO,
    VIOLATION_EXAMPLES,
)

# Leakage-safety scope (2026-08-10 재설계): only the 5 documents actually used by the current
# pilot are excluded — the other 15 benchmark docs are fair game since they aren't being
# scored right now. If the pilot doc set grows, this pattern (and the underlying curation in
# fewshot_bank.py) must be re-audited against the new set.
_PILOT_DOC_IDS = ("DOC-001", "DOC-003", "DOC-006", "DOC-008", "DOC-012")
_PILOT_DOC_ID_PATTERN = re.compile(r"DOC-0(?:01|03|06|08|12)\b")


def _all_example_texts():
    for examples in ALL_VIOLATION_CANDIDATES.values():
        for example in examples:
            yield example.original_text
            yield example.rationale
    for exceptions in ALL_EXCEPTION_CANDIDATES.values():
        for exception in exceptions:
            yield exception.original_text
            yield exception.exception_condition
            yield exception.rationale


def test_no_pilot_document_id_appears_in_any_example_text():
    for text in _all_example_texts():
        assert not _PILOT_DOC_ID_PATTERN.search(text), text


def test_pilot_doc_id_pattern_matches_the_real_pilot_set():
    # Sanity check that the hand-written regex above actually matches the real pilot doc
    # ids, so the leakage test isn't silently checking against the wrong set.
    for doc_id in _PILOT_DOC_IDS:
        assert _PILOT_DOC_ID_PATTERN.fullmatch(doc_id), doc_id


def test_static_violation_examples_never_exceed_the_cap():
    for rule_id, examples in VIOLATION_EXAMPLES.items():
        assert 1 <= len(examples) <= 2, rule_id
        assert len(examples) <= len(ALL_VIOLATION_CANDIDATES[rule_id])


def test_static_exception_examples_never_exceed_the_cap():
    for rule_id, examples in EXCEPTION_EXAMPLES.items():
        assert len(examples) <= 1, rule_id


def test_ratio_variant_has_more_or_equal_exceptions_than_baseline():
    # The whole point of EXCEPTION_EXAMPLES_RATIO: same violations, more exceptions — this
    # is what isolates the ratio axis from the reselection/dynamic axes.
    for rule_id, ratio_examples in EXCEPTION_EXAMPLES_RATIO.items():
        assert len(ratio_examples) <= 2, rule_id
        assert len(ratio_examples) >= len(EXCEPTION_EXAMPLES.get(rule_id, []))


def test_every_violation_rule_id_is_a_real_rule(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    for rule_id in ALL_VIOLATION_CANDIDATES:
        assert rule_id in rulebook.rules, rule_id


def test_every_exception_rule_id_is_a_real_rule(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    for rule_id in ALL_EXCEPTION_CANDIDATES:
        assert rule_id in rulebook.rules, rule_id


def test_ae03_has_thin_but_nonzero_violation_coverage():
    # Under the narrowed leakage scope (only the 5 pilot docs excluded, see module docstring
    # in fewshot_bank.py) AE-03 has exactly 1 real safe candidate — thin, but real; no
    # synthetic content was written to pad it out (project policy).
    assert len(ALL_VIOLATION_CANDIDATES["AE-03"]) == 1


def test_mi05_has_real_violation_coverage_under_the_narrowed_scope():
    # MI-05 had 0 safe candidates under the old (full 20-doc benchmark) exclusion scope —
    # confirms the narrowed scope actually recovered real data rather than needing synthesis.
    assert len(ALL_VIOLATION_CANDIDATES["MI-05"]) >= 1


def test_every_rule_has_at_least_one_violation_candidate():
    for rule_id in ALL_VIOLATION_CANDIDATES:
        assert len(ALL_VIOLATION_CANDIDATES[rule_id]) >= 1, rule_id
