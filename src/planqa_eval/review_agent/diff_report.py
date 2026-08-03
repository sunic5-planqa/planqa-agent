from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from planqa_eval.review_agent.pipeline import ReviewResult
from planqa_eval.rulebook import RuleBook


def _issue_id(doc_id: str, index: int) -> str:
    return f"REV-{doc_id}-{index:03d}"


def to_json_dict(result: ReviewResult) -> list[dict[str, Any]]:
    """Matches docs/adr/0001-review-agent-output-contract.md field-for-field (plus the
    original_text/rationale/fix_direction the diff view needs, which that parser ignores
    but doesn't choke on) — this file can be handed straight to
    `planqa-eval evaluate --predictions <this file>`."""
    return [
        {
            "issue_id": issue.issue_id or _issue_id(result.doc_id, i),
            "doc_id": issue.doc_id,
            "level": issue.level,
            "rule_id": issue.rule_id,
            "location": issue.location,
            "description": issue.description,
            "exception_ref": issue.exception_ref,
            "original_text": issue.original_text,
            "rationale": issue.rationale,
            "fix_direction": issue.fix_direction,
        }
        for i, issue in enumerate(result.issues)
    ]


def _diff_block(original: str | None, suggestion: str | None) -> str:
    """Line-level diff between the flagged original text and the suggested revision,
    rendered as a ```diff fence so GitHub/VSCode preview it with red/green highlighting."""
    if not original and not suggestion:
        return ""
    old_lines = (original or "").splitlines() or [""]
    new_lines = (suggestion or original or "").splitlines() or [""]

    rendered: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old_lines, b=new_lines).get_opcodes():
        if tag == "equal":
            rendered.extend(f"  {line}" for line in old_lines[i1:i2])
        else:
            rendered.extend(f"- {line}" for line in old_lines[i1:i2])
            rendered.extend(f"+ {line}" for line in new_lines[j1:j2])

    body = "\n".join(rendered)
    return f"```diff\n{body}\n```"


def to_markdown(result: ReviewResult, rulebook: RuleBook) -> str:
    lines = [f"# 기획서 검토 결과 — {result.doc_id}", ""]
    if result.global_context:
        lines += ["## 문서 요약 (Global Context)", "", result.global_context, ""]
    lines += [f"## 지적 사항 ({len(result.issues)}건)", ""]

    if not result.issues:
        lines.append("발견된 이슈가 없습니다.")
        return "\n".join(lines)

    for i, issue in enumerate(result.issues, start=1):
        rule = rulebook.rule(issue.rule_id)
        category_label = rule.category_label if rule else issue.rule_id
        lines += [
            f"### {i}. [{issue.rule_id}] {category_label} — {issue.location}",
            "",
            f"- 위계: {issue.level}",
            f"- 문제: {issue.description}",
        ]
        if issue.rationale:
            lines.append(f"- 근거: {issue.rationale}")
        lines.append("")
        diff = _diff_block(issue.original_text, issue.fix_direction)
        if diff:
            lines += [diff, ""]
        lines += ["---", ""]

    return "\n".join(lines)


def write_report(output_dir: Path, result: ReviewResult, rulebook: RuleBook) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "review.json"
    md_path = output_dir / "review.md"
    json_path.write_text(json.dumps(to_json_dict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(result, rulebook), encoding="utf-8")
    return json_path, md_path
