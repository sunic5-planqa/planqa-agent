from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from planqa_eval.ensemble import JudgeAssembly
from planqa_eval.judge import JudgeScore, judge_matches, judge_matches_ensemble
from planqa_eval.llm.base import LLMClient
from planqa_eval.matcher import match_all
from planqa_eval.new_rule_triage import TriageResult, triage_candidates_ensemble, triage_fp_candidates
from planqa_eval.rulebook import RuleBook
from planqa_eval.schema import Issue
from planqa_eval.verifier import VerifiedMatch, VerifiedMiss, verify_matches, verify_misses


@dataclass(frozen=True, slots=True)
class PipelineResult:
    verified_matches: list[VerifiedMatch]
    judge_scores: list[JudgeScore]
    verified_misses: list[VerifiedMiss]
    triage_results: list[TriageResult]


def run_pipeline(
    golden: list[Issue],
    predicted: list[Issue],
    rulebook: RuleBook,
    source_dir: Path,
    llm: LLMClient,
    *,
    judge_assembly: JudgeAssembly | None = None,
) -> PipelineResult:
    """The one function every prediction source runs through — the review agent's output and
    each human Review1-4 baseline all call this the same way, so Aggregator's comparisons are
    apples-to-apples.

    judge_assembly swaps the single-LLM judge/triage calls for the LLM-as-judge ensemble
    (judge_matches_ensemble/triage_candidates_ensemble) — llm doubles as the arbiter for
    whatever the ensemble can't agree on. Matcher/Verifier are untouched: only the two
    genuinely "grading" stages (rubric scoring, FP-candidate triage) go through the ensemble.
    """
    match_result = match_all(golden, predicted, llm)
    if judge_assembly is not None:
        judge_scores = judge_matches_ensemble(match_result.matched, judge_assembly, arbiter=llm)
        triage_results = triage_candidates_ensemble(match_result.fp_candidates, rulebook, judge_assembly, arbiter=llm)
    else:
        judge_scores = judge_matches(match_result.matched, llm)
        triage_results = triage_fp_candidates(match_result.fp_candidates, rulebook, llm)

    return PipelineResult(
        verified_matches=verify_matches(match_result.matched),
        judge_scores=judge_scores,
        verified_misses=verify_misses(match_result.fn_candidates, rulebook, source_dir),
        triage_results=triage_results,
    )
