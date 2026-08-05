from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from planqa_eval.judge import JudgeScore, judge_matches
from planqa_eval.llm.base import LLMClient
from planqa_eval.matcher import match_all
from planqa_eval.new_rule_triage import TriageResult, triage_fp_candidates
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
) -> PipelineResult:
    """The one function every prediction source runs through — the review agent's output,
    each human Review1-4 baseline, and the 2-1 confidence-gate sample all call this the
    same way, so Aggregator's comparisons are apples-to-apples."""
    match_result = match_all(golden, predicted, llm)
    return PipelineResult(
        verified_matches=verify_matches(match_result.matched),
        judge_scores=judge_matches(match_result.matched, llm),
        verified_misses=verify_misses(match_result.fn_candidates, rulebook, source_dir),
        triage_results=triage_fp_candidates(match_result.fp_candidates, rulebook, llm),
    )
