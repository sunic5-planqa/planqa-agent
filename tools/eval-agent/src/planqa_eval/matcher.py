from __future__ import annotations

from dataclasses import dataclass, field

from planqa_eval.llm.base import LLMClient
from planqa_eval.prefilter import candidate_pairs
from planqa_schemas.schema import Issue

_MATCHER_SYSTEM = (
    "You are matching QA issues found by a document-review agent against a human-labeled "
    "golden list of issues, for a single document and rule category. Two issues match if "
    "they point at the same underlying problem (same location/span and same kind of "
    "problem), even if the wording differs. Each golden issue matches at most one "
    "predicted issue and vice versa; issues with no counterpart are simply left unmatched. "
    'Respond with JSON only: {"matches": [{"golden_index": <int>, "predicted_index": <int>}, ...]}'
)


@dataclass(frozen=True, slots=True)
class MatchResult:
    matched: list[tuple[Issue, Issue]] = field(default_factory=list)
    fn_candidates: list[Issue] = field(default_factory=list)
    fp_candidates: list[Issue] = field(default_factory=list)


def _format_issue(index: int, issue: Issue) -> str:
    text = issue.original_text or issue.description
    return f"[{index}] rule={issue.rule_id} location={issue.location!r} text={text!r}"


def _build_prompt(golden: list[Issue], predicted: list[Issue]) -> str:
    golden_block = "\n".join(_format_issue(i, issue) for i, issue in enumerate(golden))
    predicted_block = "\n".join(_format_issue(i, issue) for i, issue in enumerate(predicted))
    return f"Golden issues:\n{golden_block}\n\nPredicted issues:\n{predicted_block}\n\nReturn the matches JSON."


def match_bucket(golden: list[Issue], predicted: list[Issue], llm: LLMClient) -> MatchResult:
    """N:M match within a single (document, rule category) bucket. Trivial cases (one side
    empty) skip the LLM call entirely."""
    if not golden and not predicted:
        return MatchResult()
    if not golden:
        return MatchResult(fp_candidates=list(predicted))
    if not predicted:
        return MatchResult(fn_candidates=list(golden))

    response = llm.complete_json(system=_MATCHER_SYSTEM, prompt=_build_prompt(golden, predicted))
    raw_matches = response.get("matches", []) if isinstance(response, dict) else []

    matched_golden_idx: set[int] = set()
    matched_predicted_idx: set[int] = set()
    matched: list[tuple[Issue, Issue]] = []
    for pair in raw_matches:
        if not isinstance(pair, dict):
            continue
        g_idx, p_idx = pair.get("golden_index"), pair.get("predicted_index")
        if not (isinstance(g_idx, int) and 0 <= g_idx < len(golden)):
            continue
        if not (isinstance(p_idx, int) and 0 <= p_idx < len(predicted)):
            continue
        if g_idx in matched_golden_idx or p_idx in matched_predicted_idx:
            continue  # guard against the model emitting a duplicate or 1:many pairing
        matched.append((golden[g_idx], predicted[p_idx]))
        matched_golden_idx.add(g_idx)
        matched_predicted_idx.add(p_idx)

    return MatchResult(
        matched=matched,
        fn_candidates=[g for i, g in enumerate(golden) if i not in matched_golden_idx],
        fp_candidates=[p for i, p in enumerate(predicted) if i not in matched_predicted_idx],
    )


def match_all(golden: list[Issue], predicted: list[Issue], llm: LLMClient) -> MatchResult:
    """Runs match_bucket over every (doc, category) bucket from the prefilter and merges
    the results into one MatchResult for the whole run."""
    result = MatchResult()
    for categories in candidate_pairs(golden, predicted).values():
        for golden_subset, predicted_subset in categories.values():
            bucket_result = match_bucket(golden_subset, predicted_subset, llm)
            result.matched.extend(bucket_result.matched)
            result.fn_candidates.extend(bucket_result.fn_candidates)
            result.fp_candidates.extend(bucket_result.fp_candidates)
    return result
