from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from planqa_eval.ensemble import JudgeAssembly, majority_vote_categorical, run_ensemble
from planqa_eval.llm.base import LLMClient
from planqa_eval.rulebook import RuleBook
from planqa_eval.schema import Issue

Verdict = Literal["false_positive", "new_rule_candidate", "human_review"]


@dataclass(frozen=True, slots=True)
class TriageResult:
    predicted: Issue
    verdict: Verdict
    reasoning: str | None = None
    ambiguous: bool = False

_TRIAGE_CRITERIA = (
    '- "false_positive": the flagged rule genuinely does not apply here (the agent got it '
    "wrong)\n"
    '- "new_rule_candidate": the agent correctly spotted a real problem, but it does not '
    "fit any of the existing rule categories listed below (a legitimate rulebook gap, not "
    "an agent error — the rulebook has grown from real cases like this before, e.g. LG-06 "
    "and MI-08)\n"
    '- "human_review": you cannot confidently tell which of the above it is'
)

_TRIAGE_SYSTEM = (
    "A document-review agent flagged an issue that did not match any golden (human-"
    f"confirmed) issue for this document/category. Decide whether this is:\n{_TRIAGE_CRITERIA}\n"
    'Respond with JSON only: {"verdict": "false_positive"|"new_rule_candidate"|'
    '"human_review", "reasoning": "<one sentence>"}'
)

_BATCH_TRIAGE_SYSTEM = (
    "A document-review agent flagged several issues that did not match any golden (human-"
    f"confirmed) issue for their document/category. For EACH indexed item below, "
    f"independently decide whether it is:\n{_TRIAGE_CRITERIA}\n"
    'Respond with JSON only: {"triage": [{"index": <int>, "verdict": "false_positive"|'
    '"new_rule_candidate"|"human_review", "reasoning": "<one sentence>"}, ...]} — one entry '
    "per item, in any order."
)

_VALID_VERDICTS = ("false_positive", "new_rule_candidate", "human_review")


def _category_lines(rulebook: RuleBook) -> str:
    labels = sorted({rule.category_label for rule in rulebook.rules.values()})
    return "\n".join(f"- {label}" for label in labels)


def _issue_line(index: int, issue: Issue) -> str:
    return f"[{index}] rule={issue.rule_id} location={issue.location!r} description={issue.description!r}"


def _result_from(issue: Issue, values: dict) -> TriageResult:
    verdict = values.get("verdict")
    if verdict not in _VALID_VERDICTS:
        verdict = "human_review"
    return TriageResult(predicted=issue, verdict=verdict, reasoning=values.get("reasoning"))


def triage_fp_candidate(issue: Issue, rulebook: RuleBook, llm: LLMClient) -> TriageResult:
    prompt = (
        f"Existing rule categories:\n{_category_lines(rulebook)}\n\n"
        f"Flagged issue: {_issue_line(0, issue)}\n\nReturn the triage JSON."
    )
    response = llm.complete_json(system=_TRIAGE_SYSTEM, prompt=prompt)
    return _result_from(issue, response if isinstance(response, dict) else {})


def _build_batch_prompt(fp_candidates: list[Issue], rulebook: RuleBook) -> str:
    items = "\n".join(_issue_line(i, issue) for i, issue in enumerate(fp_candidates))
    return (
        f"Existing rule categories:\n{_category_lines(rulebook)}\n\n"
        f"Flagged issues:\n{items}\n\nReturn the triage JSON."
    )


def triage_fp_candidates(
    fp_candidates: list[Issue], rulebook: RuleBook, llm: LLMClient
) -> list[TriageResult]:
    """One LLM call for the whole batch instead of one per candidate. If the model drops an
    index from its response, that single candidate falls back to triage_fp_candidate()
    rather than failing the whole batch or silently guessing a verdict. If the whole batch
    response isn't even valid JSON (small local models can truncate/garble a large batch),
    every candidate falls back the same way instead of the run crashing."""
    if not fp_candidates:
        return []

    try:
        response = llm.complete_json(system=_BATCH_TRIAGE_SYSTEM, prompt=_build_batch_prompt(fp_candidates, rulebook))
    except ValueError:
        response = None
    raw = response.get("triage", []) if isinstance(response, dict) else []
    by_index = {item["index"]: item for item in raw if isinstance(item, dict) and "index" in item}

    results: list[TriageResult] = []
    for i, issue in enumerate(fp_candidates):
        values = by_index.get(i)
        if values is None:
            results.append(triage_fp_candidate(issue, rulebook, llm))
            continue
        results.append(_result_from(issue, values))
    return results


def triage_ensemble(
    issue: Issue,
    rulebook: RuleBook,
    assembly: JudgeAssembly,
    arbiter: LLMClient | None = None,
    consensus_min: float = 2 / 3,
) -> TriageResult:
    """SuperJudge-style orchestration for triage: each assembly member independently classifies
    the candidate, majority verdict wins. Below consensus_min the verdict is ambiguous — with
    an arbiter given, that candidate alone is re-triaged by the arbiter (Layer 3→4 escalation,
    same policy as judge_match_ensemble)."""
    results = run_ensemble(lambda llm: triage_fp_candidate(issue, rulebook, llm), assembly)
    if not results:
        raise RuntimeError("every judge in the ensemble failed")

    verdicts = [result.verdict for _, result in results]
    winner, consensus = majority_vote_categorical(verdicts)
    ambiguous = consensus < consensus_min

    if ambiguous and arbiter is not None:
        return replace(triage_fp_candidate(issue, rulebook, arbiter), ambiguous=True)

    reasoning = next((result.reasoning for _, result in results if result.verdict == winner), None)
    return TriageResult(predicted=issue, verdict=winner, reasoning=reasoning, ambiguous=ambiguous)


def triage_candidates_ensemble(
    fp_candidates: list[Issue],
    rulebook: RuleBook,
    assembly: JudgeAssembly,
    arbiter: LLMClient | None = None,
    consensus_min: float = 2 / 3,
) -> list[TriageResult]:
    return [
        triage_ensemble(issue, rulebook, assembly, arbiter=arbiter, consensus_min=consensus_min)
        for issue in fp_candidates
    ]
