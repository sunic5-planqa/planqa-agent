from __future__ import annotations

from dataclasses import dataclass

from planqa_eval.llm.base import LLMClient
from planqa_eval.schema import Issue

_JUDGE_CRITERIA = (
    "Score the agent's explanation on 4 axes, 1 (worst) to 5 (best):\n"
    "- root_cause_accuracy: does it correctly identify why this is a problem, matching the "
    "golden rationale?\n"
    "- no_hallucination: does it avoid inventing details not supported by the document?\n"
    "- service_tone_fit: does it phrase the finding as guidance/suggestion rather than a "
    "flat command (기획서 검토는 단정이 아닌 안내형이어야 함)?\n"
    "- actionability: is the suggested fix concrete enough to act on?"
)

_JUDGE_SYSTEM = (
    "You are grading how well a document-review agent explained a QA issue that has "
    f"already been confirmed correct (matched against a human-labeled golden issue). {_JUDGE_CRITERIA}\n"
    'Respond with JSON only: {"root_cause_accuracy": <1-5>, "no_hallucination": <1-5>, '
    '"service_tone_fit": <1-5>, "actionability": <1-5>}'
)

_BATCH_JUDGE_SYSTEM = (
    "You are grading how well a document-review agent explained several QA issues that "
    f"have already been confirmed correct (each matched against a human-labeled golden "
    f"issue). For EACH indexed item below, independently: {_JUDGE_CRITERIA}\n"
    'Respond with JSON only: {"scores": [{"index": <int>, "root_cause_accuracy": <1-5>, '
    '"no_hallucination": <1-5>, "service_tone_fit": <1-5>, "actionability": <1-5>}, ...]} '
    "— one entry per item, in any order."
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


def _pair_prompt_block(golden: Issue, predicted: Issue) -> str:
    return (
        "Golden issue (ground truth):\n"
        f"  rationale: {golden.rationale or golden.description!r}\n"
        f"  fix direction: {golden.fix_direction!r}\n"
        "Agent's explanation to grade:\n"
        f"  description: {predicted.description!r}\n"
        f"  fix direction: {predicted.fix_direction!r}"
    )


def _score_from(golden: Issue, predicted: Issue, values: dict) -> JudgeScore:
    return JudgeScore(
        golden=golden,
        predicted=predicted,
        root_cause_accuracy=int(values["root_cause_accuracy"]),
        no_hallucination=int(values["no_hallucination"]),
        service_tone_fit=int(values["service_tone_fit"]),
        actionability=int(values["actionability"]),
    )


def judge_match(golden: Issue, predicted: Issue, llm: LLMClient) -> JudgeScore:
    prompt = f"{_pair_prompt_block(golden, predicted)}\n\nReturn the scores JSON."
    response = llm.complete_json(system=_JUDGE_SYSTEM, prompt=prompt)
    return _score_from(golden, predicted, response)


def _build_batch_prompt(matched: list[tuple[Issue, Issue]]) -> str:
    blocks = "\n\n".join(
        f"[{i}]\n{_pair_prompt_block(golden, predicted)}" for i, (golden, predicted) in enumerate(matched)
    )
    return f"{blocks}\n\nReturn the scores JSON."


def judge_matches(matched: list[tuple[Issue, Issue]], llm: LLMClient) -> list[JudgeScore]:
    """One LLM call for the whole batch instead of one per pair. If the model drops an
    index from its response (malformed/partial output), that single pair falls back to
    judge_match() rather than failing the whole batch or silently guessing a score."""
    if not matched:
        return []

    response = llm.complete_json(system=_BATCH_JUDGE_SYSTEM, prompt=_build_batch_prompt(matched))
    raw_scores = response.get("scores", []) if isinstance(response, dict) else []
    by_index = {item["index"]: item for item in raw_scores if isinstance(item, dict) and "index" in item}

    scores: list[JudgeScore] = []
    for i, (golden, predicted) in enumerate(matched):
        values = by_index.get(i)
        try:
            if values is None:
                raise KeyError(i)
            scores.append(_score_from(golden, predicted, values))
        except (KeyError, TypeError, ValueError):
            scores.append(judge_match(golden, predicted, llm))
    return scores
