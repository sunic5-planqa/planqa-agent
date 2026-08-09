from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from planqa_review.pipeline import ReviewResult
from planqa_review.run_stats import RunStats
from planqa_schemas.rulebook import RuleBook


def _issue_id(doc_id: str, index: int) -> str:
    return f"REV-{doc_id}-{index:03d}"


def _stats_dict(stats: RunStats) -> dict[str, Any]:
    return {
        "profile": stats.profile,
        "backend": stats.backend,
        "screen_model": stats.screen_model,
        "verify_model": stats.verify_model,
        "rulebook_hash": stats.rulebook_hash,
        "total_wall_seconds": round(stats.total_wall_seconds, 2),
        "screen": {
            "call_count": stats.screen.call_count,
            "elapsed_seconds": round(stats.screen.elapsed_seconds, 2),
            "total_tokens": stats.screen.total_tokens,
        },
        "confirm": {
            "call_count": stats.confirm.call_count,
            "elapsed_seconds": round(stats.confirm.elapsed_seconds, 2),
            "total_tokens": stats.confirm.total_tokens,
        },
        "by_stage": _usage_map_dict(stats.by_stage),
        "by_tier": _usage_map_dict(stats.by_tier),
        "by_rule": _usage_map_dict(stats.by_rule),
    }


def _usage_map_dict(usage_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: {
            "call_count": usage.call_count,
            "elapsed_seconds": round(usage.elapsed_seconds, 2),
            "total_tokens": usage.total_tokens,
        }
        for key, usage in usage_map.items()
    }


def issue_dicts(result: ReviewResult) -> list[dict[str, Any]]:
    """The per-issue field mapping shared by `to_json_dict` (single document) and any
    caller that needs to merge several documents' issues into one predictions file (e.g.
    a multi-document model pilot, where eval-agent needs several docs' worth of issues at
    once for recall/precision to mean anything)."""
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
            "related_location": issue.related_location,
        }
        for i, issue in enumerate(result.issues)
    ]


def to_json_dict(result: ReviewResult, stats: RunStats | None = None) -> list[dict[str, Any]] | dict[str, Any]:
    """Matches eval-agent's common Issue schema field-for-field (plus the
    original_text/rationale/fix_direction the diff view needs, which that parser ignores
    but doesn't choke on) — this file can be handed straight to
    `planqa-eval evaluate --predictions <this file>` from within eval-agent/. That parser
    also accepts the {"issues": [...]} wrapper, so passing `stats` (profile/model/time/
    token/rulebook-version cost of this run, for comparing experiments) stays compatible
    without a separate file."""
    issues = issue_dicts(result)
    if stats is None and not result.tier_errors:
        return issues
    payload: dict[str, Any] = {"issues": issues}
    if stats is not None:
        payload["stats"] = _stats_dict(stats)
    if result.tier_errors:
        payload["tier_errors"] = list(result.tier_errors)
    return payload


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


def _stats_markdown(stats: RunStats) -> list[str]:
    def _tokens(n: int | None) -> str:
        return f"{n:,}" if n is not None else "—"

    return [
        "## 실행 통계",
        "",
        f"- 프로필: `{stats.profile}` / 백엔드: `{stats.backend}`",
        f"- 스크리닝 모델: `{stats.screen_model}` / 정밀판정 모델: `{stats.verify_model}`",
        f"- 룰북 해시: `{stats.rulebook_hash}` (`git log -p -- data/rulebook/rulebook_v1.0.md`로 대조)",
        f"- 총 소요 시간: {stats.total_wall_seconds:.1f}초",
        f"- 스크리닝: {stats.screen.call_count}회 호출, {stats.screen.elapsed_seconds:.1f}초, "
        f"{_tokens(stats.screen.total_tokens)} 토큰",
        f"- 정밀판정: {stats.confirm.call_count}회 호출 (Global Context 포함), "
        f"{stats.confirm.elapsed_seconds:.1f}초, {_tokens(stats.confirm.total_tokens)} 토큰",
        "",
    ]


def to_markdown(result: ReviewResult, rulebook: RuleBook, stats: RunStats | None = None) -> str:
    lines = [f"# 기획서 검토 결과 — {result.doc_id}", ""]
    if stats is not None:
        lines += _stats_markdown(stats)
    if result.tier_errors:
        lines += ["## ⚠️ 일부 위계 검토 실패 — 아래 결과는 부분 결과입니다", ""]
        lines += [f"- {error}" for error in result.tier_errors]
        lines.append("")
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
        if issue.related_location:
            lines.append(f"- 관련 위치: {issue.related_location}")
        lines.append("")
        diff = _diff_block(issue.original_text, issue.fix_direction)
        if diff:
            lines += [diff, ""]
        lines += ["---", ""]

    return "\n".join(lines)


def write_report(
    output_dir: Path, result: ReviewResult, rulebook: RuleBook, stats: RunStats | None = None
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "review.json"
    md_path = output_dir / "review.md"
    json_path.write_text(json.dumps(to_json_dict(result, stats), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(result, rulebook, stats), encoding="utf-8")
    return json_path, md_path
