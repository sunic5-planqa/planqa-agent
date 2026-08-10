from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from planqa_eval.ensemble import JudgeAssembly
from planqa_eval.harness.full_eval import run_full_evaluation
from planqa_eval.llm.factory import build_llm_client
from planqa_eval.parsers.review_json import parse_review_output, parse_review_stats
from planqa_eval.reporter import write_report
from planqa_schemas.rulebook import parse_rulebook

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


def cmd_evaluate(args: argparse.Namespace) -> int:
    rulebook = parse_rulebook(args.rulebook)
    predicted = parse_review_output(args.predictions)
    review_stats = parse_review_stats(args.predictions)
    llm = build_llm_client(args.backend)
    judge_assembly = _parse_judge_ensemble(args.judge_ensemble)

    result, report, comparison = run_full_evaluation(
        args.xlsx,
        predicted,
        rulebook,
        args.source_dir,
        llm,
        judge_assembly=judge_assembly,
        include_baseline=args.with_baseline,
    )

    out_dir = Path("outputs/eval") / _timestamp()
    json_path, md_path = write_report(out_dir, result, report, comparison, review_stats=review_stats)
    print(f"Wrote {json_path} and {md_path}")
    print(f"Overall recall={report.overall.recall} precision={report.overall.precision}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="planqa-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    eval_parser = subparsers.add_parser("evaluate", help="run the golden-set evaluation")
    eval_parser.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    eval_parser.add_argument("--rulebook", type=Path, default=DEFAULT_RULEBOOK)
    eval_parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    eval_parser.add_argument("--predictions", type=Path, required=True, help="review agent output JSON")
    eval_parser.add_argument("--backend", default=None, help="overrides PLANQA_LLM_BACKEND (gemini|ollama)")
    eval_parser.add_argument(
        "--judge-ensemble",
        default=None,
        help="LLM-as-judge orchestration: comma-separated name:backend[:model], e.g. "
        "qwen:ollama:qwen2.5:1.5b,exaone:ollama:exaone3.5:2.4b,gemma:ollama:gemma2:2b "
        "— --backend's LLM acts as the arbiter for pairs the ensemble can't agree on",
    )
    eval_parser.add_argument(
        "--with-baseline",
        action="store_true",
        help="also run the Review1-6 human-baseline comparison — several times the cost/"
        "time of the default golden-set-only run, off unless explicitly asked for",
    )
    eval_parser.set_defaults(func=cmd_evaluate)

    return parser


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.exit(args.func(args))
