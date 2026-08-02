from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from planqa_eval.llm.base import LLMClient
from planqa_eval.rulebook import RuleBook
from planqa_eval.schema import Issue

Verdict = Literal["false_positive", "new_rule_candidate", "human_review"]

_TRIAGE_SYSTEM = (
    "A document-review agent flagged an issue that did not match any golden (human-"
    "confirmed) issue for this document/category. Decide whether this is:\n"
    '- "false_positive": the flagged rule genuinely does not apply here (the agent got it '
    "wrong)\n"
    '- "new_rule_candidate": the agent correctly spotted a real problem, but it does not '
    "fit any of the existing rule categories listed below (a legitimate rulebook gap, not "
    "an agent error — the rulebook has grown from real cases like this before, e.g. LG-06 "
    "and MI-08)\n"
    '- "human_review": you cannot confidently tell which of the above it is\n'
    'Respond with JSON only: {"verdict": "false_positive"|"new_rule_candidate"|'
    '"human_review", "reasoning": "<one sentence>"}'
)


@dataclass(frozen=True, slots=True)
class TriageResult:
    predicted: Issue
    verdict: Verdict
    reasoning: str | None = None


def _build_prompt(issue: Issue, rulebook: RuleBook) -> str:
    labels = sorted({rule.category_label for rule in rulebook.rules.values()})
    category_lines = "\n".join(f"- {label}" for label in labels)
    return (
        f"Existing rule categories:\n{category_lines}\n\n"
        f"Flagged issue: rule={issue.rule_id} location={issue.location!r}\n"
        f"description: {issue.description!r}\n\n"
        "Return the triage JSON."
    )


def triage_fp_candidate(issue: Issue, rulebook: RuleBook, llm: LLMClient) -> TriageResult:
    response = llm.complete_json(system=_TRIAGE_SYSTEM, prompt=_build_prompt(issue, rulebook))
    verdict = response.get("verdict") if isinstance(response, dict) else None
    reasoning = response.get("reasoning") if isinstance(response, dict) else None
    if verdict not in ("false_positive", "new_rule_candidate", "human_review"):
        verdict = "human_review"
    return TriageResult(predicted=issue, verdict=verdict, reasoning=reasoning)


def triage_fp_candidates(
    fp_candidates: list[Issue], rulebook: RuleBook, llm: LLMClient
) -> list[TriageResult]:
    return [triage_fp_candidate(issue, rulebook, llm) for issue in fp_candidates]
