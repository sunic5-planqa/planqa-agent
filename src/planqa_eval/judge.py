from __future__ import annotations

from dataclasses import dataclass

from planqa_eval.llm.base import LLMClient
from planqa_eval.schema import Issue

_JUDGE_SYSTEM = (
    "You are grading how well a document-review agent explained a QA issue that has "
    "already been confirmed correct (matched against a human-labeled golden issue). Score "
    "the agent's explanation on 4 axes, 1 (worst) to 5 (best):\n"
    "- root_cause_accuracy: does it correctly identify why this is a problem, matching the "
    "golden rationale?\n"
    "- no_hallucination: does it avoid inventing details not supported by the document?\n"
    "- service_tone_fit: does it phrase the finding as guidance/suggestion rather than a "
    "flat command (기획서 검토는 단정이 아닌 안내형이어야 함)?\n"
    "- actionability: is the suggested fix concrete enough to act on?\n"
    'Respond with JSON only: {"root_cause_accuracy": <1-5>, "no_hallucination": <1-5>, '
    '"service_tone_fit": <1-5>, "actionability": <1-5>}'
)


@dataclass(frozen=True, slots=True)
class JudgeScore:
    golden: Issue
    predicted: Issue
    root_cause_accuracy: int
    no_hallucination: int
    service_tone_fit: int
    actionability: int

    @property
    def average(self) -> float:
        return (
            self.root_cause_accuracy
            + self.no_hallucination
            + self.service_tone_fit
            + self.actionability
        ) / 4


def _build_prompt(golden: Issue, predicted: Issue) -> str:
    return (
        "Golden issue (ground truth):\n"
        f"  rationale: {golden.rationale or golden.description!r}\n"
        f"  fix direction: {golden.fix_direction!r}\n\n"
        "Agent's explanation to grade:\n"
        f"  description: {predicted.description!r}\n"
        f"  fix direction: {predicted.fix_direction!r}\n\n"
        "Return the scores JSON."
    )


def judge_match(golden: Issue, predicted: Issue, llm: LLMClient) -> JudgeScore:
    response = llm.complete_json(system=_JUDGE_SYSTEM, prompt=_build_prompt(golden, predicted))
    return JudgeScore(
        golden=golden,
        predicted=predicted,
        root_cause_accuracy=int(response["root_cause_accuracy"]),
        no_hallucination=int(response["no_hallucination"]),
        service_tone_fit=int(response["service_tone_fit"]),
        actionability=int(response["actionability"]),
    )


def judge_matches(matched: list[tuple[Issue, Issue]], llm: LLMClient) -> list[JudgeScore]:
    return [judge_match(golden, predicted, llm) for golden, predicted in matched]
