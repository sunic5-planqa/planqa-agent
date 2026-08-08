from __future__ import annotations

from typing import Any

from planqa_eval_service.ensemble import JudgeAssembly, majority_vote_categorical, run_ensemble
from planqa_eval_service.llm.base import LLMClient
from planqa_schemas.rulebook import RuleBook, RuleDef

# Reference-free by design — unlike tools/eval-agent's judge_match(), there is no golden
# Issue to compare against here (this grades review-agent's *live* production output, which
# has no golden counterpart). The only ground truth available is the rule's own text and the
# agent's own quoted evidence.
_TIER1_CRITERIA = (
    "Does the quoted evidence (original_text) genuinely violate the cited rule, given the "
    "rule's own exception condition? You have no reference answer — judge only from the "
    "rule text and the agent's own quoted evidence/reasoning. Mark confidence 'uncertain' "
    "rather than guessing whenever the rule text alone doesn't clearly settle it — that is "
    "the signal that escalates this finding to a second, independent check, so it's cheaper "
    "to say 'uncertain' here than to be confidently wrong."
)

_TIER1_SYSTEM = (
    "You are auditing a document-review agent's findings independently, after the fact — "
    f"this is not the agent's own confirmation step. For EACH indexed finding below: {_TIER1_CRITERIA}\n"
    'Respond with JSON only: {"verdicts": [{"index": <int>, "valid": <bool>, '
    '"confidence": "confident"|"uncertain", "reason": "<one sentence>"}, ...]} — one entry '
    "per finding, in any order."
)

_TIER2_SYSTEM = (
    "You are independently verifying whether a document-review agent's finding is a "
    f"genuine rule violation. {_TIER1_CRITERIA}\n"
    'Respond with JSON only: {"valid": <bool>, "reason": "<one sentence>"}'
)


def _rule_block(rule: RuleDef | None, rule_id: str) -> str:
    if rule is None:
        return f"rule {rule_id}: (definition not found in bundled rulebook)"
    return f"rule {rule.rule_id} ({rule.category_label}): {rule.text}\n  exception condition: {rule.exception_text or '없음'}"


def _issue_block(index: int, issue: dict[str, Any], rulebook: RuleBook) -> str:
    rule = rulebook.rule(issue.get("rule_id", ""))
    return (
        f"[{index}] {_rule_block(rule, issue.get('rule_id', ''))}\n"
        f"  quoted evidence (original_text): {issue.get('original_text')!r}\n"
        f"  agent's description: {issue.get('description')!r}\n"
        f"  agent's rationale: {issue.get('rationale')!r}"
    )


def _build_tier1_prompt(issues: list[dict[str, Any]], rulebook: RuleBook) -> str:
    blocks = "\n\n".join(_issue_block(i, issue, rulebook) for i, issue in enumerate(issues))
    return f"{blocks}\n\nReturn the verdicts JSON."


def _tier1_batch_check(issues: list[dict[str, Any]], rulebook: RuleBook, llm: LLMClient) -> list[dict[str, Any]]:
    try:
        response = llm.complete_json(system=_TIER1_SYSTEM, prompt=_build_tier1_prompt(issues, rulebook))
    except ValueError:
        response = None  # unparseable batch response — every item below falls back, not crashes

    raw = response.get("verdicts", []) if isinstance(response, dict) else []
    by_index = {item["index"]: item for item in raw if isinstance(item, dict) and "index" in item}

    results: list[dict[str, Any]] = []
    for i in range(len(issues)):
        values = by_index.get(i)
        if values is None:
            # Missing/malformed tier-1 verdict — default to trusting confirm's original
            # judgment (valid=True) rather than flagging it ourselves on no evidence, but
            # mark 'uncertain' so it still gets a real second look when an ensemble exists.
            results.append({"valid": True, "confidence": "uncertain", "reason": "tier-1 response missing/malformed"})
            continue
        confidence = values.get("confidence")
        results.append(
            {
                "valid": bool(values.get("valid")),
                "confidence": confidence if confidence in ("confident", "uncertain") else "uncertain",
                "reason": values.get("reason"),
            }
        )
    return results


def _tier2_single_check(issue: dict[str, Any], rule: RuleDef | None, llm: LLMClient) -> dict[str, Any]:
    prompt = (
        f"{_rule_block(rule, issue.get('rule_id', ''))}\n"
        f"quoted evidence (original_text): {issue.get('original_text')!r}\n"
        f"agent's description: {issue.get('description')!r}\n"
        f"agent's rationale: {issue.get('rationale')!r}\n\n"
        "Return the verdict JSON."
    )
    try:
        response = llm.complete_json(system=_TIER2_SYSTEM, prompt=prompt)
    except ValueError:
        response = None
    if not isinstance(response, dict):
        return {"valid": True, "reason": "tier-2 response missing/malformed"}
    return {"valid": bool(response.get("valid")), "reason": response.get("reason")}


def _verdict_entry(
    issue: dict[str, Any], valid: bool, tier: str, reason: str | None, *, ambiguous: bool = False, consensus: float | None = None
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "issue_id": issue.get("issue_id"),
        "rule_id": issue.get("rule_id"),
        "location": issue.get("location"),
        "valid": valid,
        "tier": tier,
        "reason": reason,
        "ambiguous": ambiguous,
    }
    if consensus is not None:
        entry["consensus"] = consensus
    return entry


def judge_review_result(
    review_result: dict[str, Any],
    llm: LLMClient,
    rulebook: RuleBook,
    *,
    assembly: JudgeAssembly | None = None,
    arbiter: LLMClient | None = None,
    consensus_min: float = 2 / 3,
) -> dict[str, Any]:
    """LLM-cascade audit of review-agent's confirmed findings, reference-free (see
    docs/adr/0001-... for why this can't reuse tools/eval-agent's golden-referenced Judge).

    Tier 1 (cheap, one batched call over every finding): each finding gets checked once. Most
    should come back 'confident' — those verdicts are final, no further cost spent.

    Tier 2 (only for 'confident'-less findings, and only if `assembly` is given): every
    member of the ensemble independently re-checks that one finding in parallel
    (run_ensemble). If they agree past `consensus_min`, the majority verdict wins. If they
    don't, and `arbiter` is given, the arbiter's single verdict wins instead and the entry is
    flagged `ambiguous=True` — this is the RouteLLM/FrugalGPT-style cascade: cheap for the
    easy majority, escalate only the genuinely uncertain minority, mirroring review-agent's
    own screen→confirm cost structure one layer up."""
    issues = review_result.get("issues", []) if isinstance(review_result, dict) else []
    if not issues:
        return {"issue_count": 0, "flagged_count": 0, "verdicts": []}

    tier1_results = _tier1_batch_check(issues, rulebook, llm)

    verdicts: list[dict[str, Any]] = []
    for issue, tier1 in zip(issues, tier1_results):
        if tier1["confidence"] == "confident" or not assembly:
            verdicts.append(_verdict_entry(issue, tier1["valid"], "cheap", tier1.get("reason")))
            continue

        rule = rulebook.rule(issue.get("rule_id", ""))
        ensemble_results = run_ensemble(lambda member_llm: _tier2_single_check(issue, rule, member_llm), assembly)
        if not ensemble_results:
            verdicts.append(_verdict_entry(issue, tier1["valid"], "cheap_fallback", "ensemble unavailable"))
            continue

        labels = ["valid" if result["valid"] else "invalid" for _, result in ensemble_results]
        winner, consensus = majority_vote_categorical(labels)
        ambiguous = consensus < consensus_min

        if ambiguous and arbiter is not None:
            final = _tier2_single_check(issue, rule, arbiter)
            verdicts.append(_verdict_entry(issue, final["valid"], "arbiter", final.get("reason"), ambiguous=True))
        else:
            verdicts.append(_verdict_entry(issue, winner == "valid", "ensemble", None, ambiguous=ambiguous, consensus=consensus))

    flagged = [v for v in verdicts if not v["valid"]]
    return {"issue_count": len(issues), "flagged_count": len(flagged), "verdicts": verdicts}
