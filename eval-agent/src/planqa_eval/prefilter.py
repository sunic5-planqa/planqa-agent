from __future__ import annotations

from collections import defaultdict

from planqa_eval.schema import Issue


def category_of(rule_id: str) -> str:
    return rule_id.split("-", 1)[0]


def group_by_doc_and_category(issues: list[Issue]) -> dict[str, dict[str, list[Issue]]]:
    grouped: dict[str, dict[str, list[Issue]]] = defaultdict(lambda: defaultdict(list))
    for issue in issues:
        grouped[issue.doc_id][category_of(issue.rule_id)].append(issue)
    return {doc_id: dict(categories) for doc_id, categories in grouped.items()}


def candidate_pairs(
    golden: list[Issue], predicted: list[Issue]
) -> dict[str, dict[str, tuple[list[Issue], list[Issue]]]]:
    """Buckets golden and predicted issues by (doc_id, rule category prefix) so the Matcher
    only ever compares issues that could plausibly refer to the same rule violation —
    narrowing the N:M search space before the expensive LLM call."""
    golden_grouped = group_by_doc_and_category(golden)
    predicted_grouped = group_by_doc_and_category(predicted)

    result: dict[str, dict[str, tuple[list[Issue], list[Issue]]]] = {}
    for doc_id in set(golden_grouped) | set(predicted_grouped):
        golden_categories = golden_grouped.get(doc_id, {})
        predicted_categories = predicted_grouped.get(doc_id, {})
        result[doc_id] = {
            category: (golden_categories.get(category, []), predicted_categories.get(category, []))
            for category in set(golden_categories) | set(predicted_categories)
        }
    return result
