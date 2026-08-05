from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from planqa_eval.schema import Issue

# No real review-agent output sample exists yet (see docs/adr/0001-review-agent-output-contract.md).
# We assume the agent emits a JSON array (optionally wrapped in {"issues": [...]}) of objects
# using the common schema's own field names directly. If the real format differs, only the
# field lookups below need to change — every other module consumes Issue objects, not raw JSON.


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
            issue_id=str(item["issue_id"]).strip() if item.get("issue_id") else None,
        )
        for item in items
    ]
