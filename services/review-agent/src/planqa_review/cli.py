from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from planqa_review.llm.factory import build_llm_client
from planqa_review.diff_report import to_json_dict, write_report
from planqa_review.eval_service_notify import notify_eval_service
from planqa_review.models import DEFAULT_PROFILE, PROFILES
from planqa_review.pipeline import review_document
from planqa_review.run_stats import build_run_stats
from planqa_review.structures import STRUCTURES
from planqa_review.structures import xdc
from planqa_schemas.rulebook import parse_rulebook

DEFAULT_RULEBOOK = Path("data/rulebook/rulebook_v1.0.md")
DEFAULT_XDC_RULEBOOK = Path("data/xdc/xdc_rulebook_v1.0.md")
DEFAULT_XDC_ALIASES = Path("data/xdc/aliases.json")


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _infer_doc_id(input_path: Path) -> str:
    stem = input_path.stem
    return stem.split("_")[0] if "_" in stem else stem


def cmd_review(args: argparse.Namespace) -> int:
    document_text = args.input.read_text(encoding="utf-8")
    doc_id = args.doc_id or _infer_doc_id(args.input)
    rulebook = parse_rulebook(args.rulebook)

    # --structure picks a non-baseline review_fn (see structures/) — useful for a quick
    # single-document smoke test of a new structure before committing to a full benchmark run.
    profile_label = args.structure or args.profile

    # --reference/--xdc-rulebook: 로컬 스모크테스트용 — 실제 백엔드 연동(승현 담당)은 이 CLI를
    # 거치지 않고 review_document(..., reference_documents=[...])를 직접 호출한다. bundled_
    # screen_hybrid 구조에서만 지원 — 다른 --structure/기본 profile 경로는 XDC 파라미터를
    # 받지 않으므로 --reference를 같이 주면 사용자 실수를 조용히 무시하지 않고 바로 에러낸다.
    # LLM 클라이언트를 만들기 전에 검사해서, 인자를 잘못 준 경우 API 키 없이도 바로 실패한다.
    if args.reference and args.structure != "bundled_screen_hybrid":
        print("--reference는 --structure bundled_screen_hybrid에서만 지원됩니다", file=sys.stderr)
        return 1

    # Two separate clients so the cheap screening pass and the precise confirm pass can run
    # different models — and, via --screen-backend/--confirm-backend, different backends
    # entirely (e.g. demo: Gemini screen + Claude confirm) — see docs/review_agent_architecture.md.
    screen_backend = args.screen_backend or args.backend
    confirm_backend = args.confirm_backend or args.backend
    screen_llm = build_llm_client(screen_backend, args.screen_model, args.temperature)
    confirm_llm = build_llm_client(confirm_backend, args.verify_model, args.temperature)
    resolved_screen_backend = screen_backend or os.environ.get("PLANQA_LLM_BACKEND") or "gemini"
    resolved_confirm_backend = confirm_backend or os.environ.get("PLANQA_LLM_BACKEND") or "gemini"
    backend_name = (
        resolved_screen_backend
        if resolved_screen_backend == resolved_confirm_backend
        else f"{resolved_screen_backend}+{resolved_confirm_backend}"
    )

    xdc_kwargs: dict[str, object] = {}
    if args.reference:
        reference_documents = [
            (_infer_doc_id(path), path.read_text(encoding="utf-8")) for path in args.reference
        ]
        xdc_rulebook_path = args.xdc_rulebook or DEFAULT_XDC_RULEBOOK
        xdc_kwargs = {
            "reference_documents": reference_documents,
            "xdc_rulebook": parse_rulebook(xdc_rulebook_path),
            "xdc_aliases": xdc.load_aliases(args.xdc_aliases or DEFAULT_XDC_ALIASES),
        }

    start = time.perf_counter()
    if args.structure:
        result = STRUCTURES[args.structure](doc_id, document_text, rulebook, screen_llm, confirm_llm, **xdc_kwargs)
    else:
        result = review_document(doc_id, document_text, rulebook, screen_llm, confirm_llm, PROFILES[args.profile])
    stats = build_run_stats(
        profile=profile_label,
        backend=backend_name,
        rulebook_path=args.rulebook,
        screen_llm=screen_llm,
        confirm_llm=confirm_llm,
        total_wall_seconds=time.perf_counter() - start,
        call_events=result.call_events,
    )

    # Profile/structure name in the default path so `outputs/` makes the originating
    # structure obvious at a glance, not just a bare timestamp.
    out_dir = args.out or Path("outputs/review") / profile_label / _timestamp()
    json_path, md_path = write_report(out_dir, result, rulebook, stats)
    # Real (non-benchmark/experiment) review only, so ablation runs don't spam eval-service
    # with synthetic traffic. Print first so the summary shows up immediately, then join —
    # main() calls sys.exit() right after this returns, and an unjoined daemon thread can be
    # killed by interpreter shutdown before its POST ever lands.
    notify_thread = notify_eval_service(to_json_dict(result, stats))
    print(
        f"{doc_id}: {len(result.issues)}건 지적, {stats.total_wall_seconds:.1f}초 — {json_path}, {md_path}"
    )
    for error in result.tier_errors:
        print(f"  ⚠️ {error}", file=sys.stderr)
    if notify_thread is not None:
        notify_thread.join(timeout=5.0)
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
    review_parser.add_argument(
        "--backend",
        default=None,
        help="overrides PLANQA_LLM_BACKEND (gemini|ollama|anthropic) — both roles unless overridden below",
    )
    review_parser.add_argument("--screen-backend", default=None, help="스크리닝 전용 백엔드 — 생략 시 --backend 사용")
    review_parser.add_argument("--confirm-backend", default=None, help="정밀판정 전용 백엔드 — 생략 시 --backend 사용")
    review_parser.add_argument("--screen-model", default=None, help="1단계 스크리닝용 모델(저비용)")
    review_parser.add_argument("--verify-model", default=None, help="2단계 정밀판정/컨텍스트 추출용 모델(고비용)")
    review_parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="샘플링 온도, 기본 0.0(ablation 재현성 위해) — 다양성 원하면 명시적으로 올릴 것",
    )
    review_parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        choices=sorted(PROFILES),
        help="프롬프트/로직 전략 (src/planqa_review/models/) — --structure 미지정 시(제안5 baseline) 적용",
    )
    review_parser.add_argument(
        "--structure",
        default=None,
        choices=sorted(STRUCTURES),
        help="구조 ablation용 — 지정 시 baseline(제안5) 대신 이 구조(src/planqa_review/structures/)로 실행, --profile은 무시됨",
    )
    review_parser.add_argument(
        "--reference",
        type=Path,
        action="append",
        default=None,
        help="타문서 정합성(XDC) 참고문서 경로 — 반복 가능, --structure bundled_screen_hybrid 전용",
    )
    review_parser.add_argument("--xdc-rulebook", type=Path, default=None, help=f"생략 시 {DEFAULT_XDC_RULEBOOK}")
    review_parser.add_argument("--xdc-aliases", type=Path, default=None, help=f"생략 시 {DEFAULT_XDC_ALIASES}")
    review_parser.set_defaults(func=cmd_review)

    return parser


def main(argv: list[str] | None = None) -> None:
    # Windows consoles often default stdout/stderr to a non-UTF-8 codepage (e.g. cp949
    # under a Korean locale), which can't encode characters like an em dash or ⚠️ — this CLI
    # is Korean-heavy on both streams (stderr carries the tier-failure warnings).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.exit(args.func(args))
