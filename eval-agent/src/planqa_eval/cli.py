from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from planqa_eval.ensemble import JudgeAssembly
from planqa_eval.harness.confidence_gate import (
    load_human_labels,
    run_confidence_gate,
    save_human_label_template,
    stratified_sample,
)
from planqa_eval.harness.full_eval import GateNotPassedError, run_full_evaluation
from planqa_eval.llm.factory import build_llm_client
from planqa_eval.parsers.golden import parse_golden_dataset
from planqa_eval.parsers.review_json import parse_review_output
from planqa_eval.reporter import write_report
from planqa_eval.rulebook import parse_rulebook

DEFAULT_XLSX = Path("data/qa_dataset/qa_dataset_2026-08-05.xlsx")
DEFAULT_RULEBOOK = Path("data/rulebook/rulebook_v1.0.md")
DEFAULT_SOURCE_DIR = Path("data/source_documents")


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _parse_judge_ensemble(spec: str | None) -> JudgeAssembly | None:
    """--judge-ensemble takes `name:backend[:model]` entries, comma-separated — e.g.
    "qwen:ollama:qwen2.5:1.5b,exaone:ollama:exaone3.5:2.4b,gemma:ollama:gemma2:2b"."""
    if not spec:
        return None
    assembly: JudgeAssembly = []
    for member in spec.split(","):
        name, backend, *rest = member.split(":", 2)
        model = rest[0] if rest else None
        assembly.append((name, build_llm_client(backend, model)))
    return assembly


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    parser.add_argument("--rulebook", type=Path, default=DEFAULT_RULEBOOK)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--predictions", type=Path, required=True, help="review agent output JSON")
    parser.add_argument("--backend", default=None, help="overrides PLANQA_LLM_BACKEND (gemini|ollama)")
    parser.add_argument(
        "--judge-ensemble",
        default=None,
        help="LLM-as-judge orchestration: comma-separated name:backend[:model], e.g. "
        "qwen:ollama:qwen2.5:1.5b,exaone:ollama:exaone3.5:2.4b,gemma:ollama:gemma2:2b "
        "— --backend's LLM acts as the arbiter for pairs the ensemble can't agree on",
    )


def cmd_gate(args: argparse.Namespace) -> int:
    rulebook = parse_rulebook(args.rulebook)
    golden = parse_golden_dataset(args.xlsx)
    predicted = parse_review_output(args.predictions)
    sample = stratified_sample(golden, rulebook, sample_size=args.sample_size)

    out_dir = Path("outputs/gate") / _timestamp()

    if args.human_labels is None:
        template_path = out_dir / "human_label_template.json"
        save_human_label_template(sample, predicted, template_path)
        print(f"Wrote a {len(sample)}-issue stratified sample template to {template_path}")
        print("Fill in matched_predicted_issue_id + the 4 rubric scores per item, then rerun")
        print(f"with --human-labels {template_path}")
        return 0

    human_labels = load_human_labels(args.human_labels)
    llm = build_llm_client(args.backend)
    assembly = _parse_judge_ensemble(args.judge_ensemble)
    report = run_confidence_gate(sample, predicted, human_labels, llm, assembly=assembly)

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "gate_report.json"
    report_path.write_text(
        json.dumps(
            {
                "passed": report.passed,
                "sample_size": report.sample_size,
                "matcher_agreement": report.matcher_agreement,
                "judge_agreement": report.judge_agreement,
                "rule_level_accuracy": report.rule_level_accuracy,
                "judge_prompt_hash": report.judge_prompt_hash,
                "log": report.log,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Gate {'PASSED' if report.passed else 'FAILED'} — report at {report_path}")
    print(
        f"  matcher_agreement={report.matcher_agreement:.0%} "
        f"judge_agreement={report.judge_agreement:.0%} "
        f"rule_level_accuracy={report.rule_level_accuracy:.0%}"
    )
    return 0 if report.passed else 1


def _latest_gate_report() -> Path:
    gate_dir = Path("outputs/gate")
    candidates = sorted(gate_dir.glob("*/gate_report.json")) if gate_dir.exists() else []
    return candidates[-1] if candidates else Path("outputs/gate/__none__/gate_report.json")


def cmd_evaluate(args: argparse.Namespace) -> int:
    rulebook = parse_rulebook(args.rulebook)
    predicted = parse_review_output(args.predictions)
    llm = build_llm_client(args.backend)
    gate_report_path = args.gate_report or _latest_gate_report()
    judge_assembly = _parse_judge_ensemble(args.judge_ensemble)

    try:
        result, report, comparison = run_full_evaluation(
            args.xlsx,
            predicted,
            rulebook,
            args.source_dir,
            llm,
            gate_report_path,
            force=args.force,
            judge_assembly=judge_assembly,
        )
    except GateNotPassedError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    out_dir = Path("outputs/eval") / _timestamp()
    json_path, md_path = write_report(out_dir, result, report, comparison)
    print(f"Wrote {json_path} and {md_path}")
    print(f"Overall recall={report.overall.recall} precision={report.overall.precision}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="planqa-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    gate_parser = subparsers.add_parser("gate", help="run the 2-1 Matcher/Judge confidence gate")
    _add_common_args(gate_parser)
    gate_parser.add_argument("--sample-size", type=int, default=10)
    gate_parser.add_argument(
        "--human-labels", type=Path, default=None, help="filled-in blind-label file; omit to generate one"
    )
    gate_parser.set_defaults(func=cmd_gate)

    eval_parser = subparsers.add_parser("evaluate", help="run the 2-2 full golden-set evaluation")
    _add_common_args(eval_parser)
    eval_parser.add_argument("--gate-report", type=Path, default=None, help="defaults to the latest gate run")
    eval_parser.add_argument("--force", action="store_true", help="skip the 2-1 gate check")
    eval_parser.set_defaults(func=cmd_evaluate)

    return parser


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.exit(args.func(args))
