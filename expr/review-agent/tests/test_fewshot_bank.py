from __future__ import annotations

import re

from planqa_review.rulebook import parse_rulebook
from planqa_review.structures.fewshot_bank import (
    ALL_EXCEPTION_CANDIDATES,
    ALL_VIOLATION_CANDIDATES,
    EXCEPTION_EXAMPLES,
    EXCEPTION_EXAMPLES_RATIO,
    VIOLATION_EXAMPLES,
)

# Leakage-safety scope (2026-08-12 재확장): DOC-001–020 전체가 채점 대상이라 전부
# 배제한다 — DOC-000/021–040만 안전. 채점 대상 문서 집합이 다시 바뀌면 이 패턴(과
# fewshot_bank.py의 실제 큐레이션)을 재대조해야 한다.
_PILOT_DOC_IDS = tuple(f"DOC-{i:03d}" for i in range(1, 21))
_PILOT_DOC_ID_PATTERN = re.compile(r"DOC-0(?:0[1-9]|1\d|20)\b")
# 이 두 rule_id는 실제 xlsx 대조 결과 DOC-000/021–040 안에 실 후보가 하나도 없음(2026-08-12
# 감사) — 합성 예시로 채우지 않기로 한 프로젝트 정책상 의도된 빈 리스트.
_KNOWN_REAL_DATA_GAPS = frozenset({"AE-03", "MI-05"})


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
        min_count = 0 if rule_id in _KNOWN_REAL_DATA_GAPS else 1
        assert min_count <= len(examples) <= 2, rule_id
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


def test_ae03_and_mi05_have_zero_real_violation_coverage_under_the_widened_scope():
    # Under the widened leakage scope (all of DOC-001–020 excluded, 2026-08-12 — see module
    # docstring in fewshot_bank.py), AE-03's and MI-05's only real safe candidates turned out
    # to live in DOC-016 and DOC-004/015/018 respectively — genuinely zero real candidates
    # remain in DOC-000/021–040. No synthetic content was written to pad them out (project
    # policy) — this test pins that gap down so it's a deliberate, visible fact rather than
    # something a future edit silently reintroduces or silently "fixes" with made-up text.
    for rule_id in _KNOWN_REAL_DATA_GAPS:
        assert len(ALL_VIOLATION_CANDIDATES[rule_id]) == 0, rule_id


def test_every_rule_has_at_least_one_violation_candidate_except_the_known_gaps():
    for rule_id in ALL_VIOLATION_CANDIDATES:
        if rule_id in _KNOWN_REAL_DATA_GAPS:
            continue
        assert len(ALL_VIOLATION_CANDIDATES[rule_id]) >= 1, rule_id
