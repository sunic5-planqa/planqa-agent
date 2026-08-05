from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from planqa_eval.llm.factory import build_llm_client
from planqa_eval.review_agent.diff_report import write_report
from planqa_eval.review_agent.models import DEFAULT_PROFILE, PROFILES
from planqa_eval.review_agent.pipeline import review_document
from planqa_eval.rulebook import parse_rulebook

DEFAULT_RULEBOOK = Path("data/rulebook/rulebook_v1.0.md")


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _infer_doc_id(input_path: Path) -> str:
    stem = input_path.stem
    return stem.split("_")[0] if "_" in stem else stem


def cmd_review(args: argparse.Namespace) -> int:
    document_text = args.input.read_text(encoding="utf-8")
    doc_id = args.doc_id or _infer_doc_id(args.input)
    rulebook = parse_rulebook(args.rulebook)
    profile = PROFILES[args.profile]

    # Two separate clients so the cheap screening pass and the precise confirm pass can run
    # different models (even different backends) — see docs/review_agent_architecture.md.
    screen_llm = build_llm_client(args.backend, args.screen_model)
    confirm_llm = build_llm_client(args.backend, args.verify_model)

    result = review_document(doc_id, document_text, rulebook, screen_llm, confirm_llm, profile)

    out_dir = args.out or Path("outputs/review") / _timestamp()
    json_path, md_path = write_report(out_dir, result, rulebook)
    print(f"{doc_id}: {len(result.issues)}건 지적 — {json_path}, {md_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="planqa-review")
    subparsers = parser.add_subparsers(dest="command", required=True)

    review_parser = subparsers.add_parser("review", help="업로드된 기획서를 룰북 기준으로 검토")
    review_parser.add_argument("--input", type=Path, required=True, help="검토할 기획서 markdown 파일 경로")
    review_parser.add_argument(
        "--doc-id", default=None, help="생략 시 파일명에서 추론 (예: DOC-001_....md -> DOC-001)"
    )
    review_parser.add_argument("--rulebook", type=Path, default=DEFAULT_RULEBOOK)
    review_parser.add_argument("--out", type=Path, default=None, help="생략 시 outputs/review/<timestamp>/")
    review_parser.add_argument("--backend", default=None, help="overrides PLANQA_LLM_BACKEND (gemini|ollama)")
    review_parser.add_argument("--screen-model", default=None, help="1단계 스크리닝용 모델(저비용)")
    review_parser.add_argument("--verify-model", default=None, help="2단계 정밀판정/컨텍스트 추출용 모델(고비용)")
    review_parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        choices=sorted(PROFILES),
        help="프롬프트/로직 전략 (review_agent/models/) — 모델 실험용",
    )
    review_parser.set_defaults(func=cmd_review)

    return parser


def main(argv: list[str] | None = None) -> None:
    # Windows consoles often default stdout to a non-UTF-8 codepage (e.g. cp949 under a
    # Korean locale), which can't encode characters like an em dash — reconfigure so the
    # Korean-heavy CLI output here doesn't crash after a review has already completed.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.exit(args.func(args))
