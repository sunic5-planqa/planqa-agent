from __future__ import annotations

from typing import Protocol

from planqa_review.structures.fewshot_bank import ALL_VIOLATION_CANDIDATES

# Simple text-similarity retrieval for the "동적퓨샷" combos — picks the few-shot examples
# most similar to the text actually being reviewed, instead of always giving the same
# static top-N. Deliberately not embedding-based: this experiment is about justifying a
# presentation claim (see docs/progress.md 2026-08-10 재설계), not standing up new
# embedding infra, so character-bigram Jaccard overlap is used instead — Korean text
# doesn't tokenize well on whitespace (no spaces between morphemes within a word), so
# character n-grams are the standard cheap substitute for word n-grams here.
#
# Used for both violation pools (FewShotExample) and exception pools (FewShotException) —
# a Protocol keeps the signature honest for either without coupling this module to both
# concrete classes.


class _CuratedExample(Protocol):
    original_text: str


def _char_bigrams(text: str) -> frozenset[str]:
    normalized = "".join(text.split())
    if len(normalized) < 2:
        return frozenset({normalized}) if normalized else frozenset()
    return frozenset(normalized[i : i + 2] for i in range(len(normalized) - 1))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def top_k_examples(
    reference_text: str,
    rule_id: str,
    k: int = 2,
    candidates: dict[str, list[_CuratedExample]] | None = None,
) -> list[_CuratedExample]:
    """Returns up to `k` examples for `rule_id` most similar to `reference_text`, ranked by
    character-bigram Jaccard overlap (highest first). Falls back to the pool's own curated
    order when there's no similarity signal (identical/zero scores) — `sorted` is stable, so
    ties keep their original best-first position. `candidates` defaults to
    `ALL_VIOLATION_CANDIDATES`; overridable for testing."""
    pool = candidates if candidates is not None else ALL_VIOLATION_CANDIDATES
    rule_candidates = pool.get(rule_id, [])
    if not rule_candidates:
        return []
    reference_bigrams = _char_bigrams(reference_text)
    ranked = sorted(
        rule_candidates,
        key=lambda example: _jaccard(reference_bigrams, _char_bigrams(example.original_text)),
        reverse=True,
    )
    return ranked[:k]
