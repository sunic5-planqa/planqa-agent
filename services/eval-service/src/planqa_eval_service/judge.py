from __future__ import annotations

from typing import Any


def judge_review_result(review_result: dict[str, Any]) -> dict[str, Any]:
    """Placeholder — real rubric scoring is deliberately deferred (see docs/adr/
    0002-monorepo-workspace-and-async-eval-service.md). It CANNOT be a straight copy of
    tools/eval-agent's judge_match(): that scores an issue against a golden-set rationale,
    and live production documents have no golden counterpart. This needs a reference-free
    design (e.g. does the finding's quoted span actually satisfy the rule text it cites)
    before it grades anything real — for now it just counts issues so the async pipeline
    (enqueue → worker → judge → store) can be exercised end-to-end."""
    issues = review_result.get("issues", [])
    return {"issue_count": len(issues), "scores": []}
