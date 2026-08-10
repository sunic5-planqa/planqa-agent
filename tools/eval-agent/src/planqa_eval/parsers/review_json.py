from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from planqa_schemas.schema import Issue

# Confirmed against a real sample (2026-08-05, see docs/adr/0001-review-agent-output-contract.md):
# a JSON array (optionally wrapped in {"issues": [...]}) using the common schema's own field
# names directly, plus original_text/rationale/fix_direction — the same extra fields the golden/
# review-sheet parsers populate, which Judge relies on for fix_direction in particular.


def _optional_str(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    return str(value).strip() if value else None


def parse_review_output(json_path: Path) -> list[Issue]:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = data["issues"] if isinstance(data, dict) else data

    return [
        Issue(
            doc_id=str(item["doc_id"]).strip(),
            level=str(item["level"]).strip(),
            rule_id=str(item["rule_id"]).strip(),
            location=str(item.get("location") or "").strip(),
            description=str(item.get("description") or "").strip(),
            exception_ref=item.get("exception_ref"),
            source="review_agent",
            issue_id=_optional_str(item, "issue_id"),
            original_text=_optional_str(item, "original_text"),
            rationale=_optional_str(item, "rationale"),
            fix_direction=_optional_str(item, "fix_direction"),
        )
        for item in items
    ]


def parse_review_stats(json_path: Path) -> dict[str, Any] | None:
    """review.json's optional {"stats": {...}} — review-agent's own cost profile for the run
    (profile/backend/models/wall time/tokens, see review-agent's run_stats.py). Passed through
    verbatim by reporter.py rather than re-derived, since only review-agent has ground truth
    on its own call counts/tokens."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    return data.get("stats") if isinstance(data, dict) else None
