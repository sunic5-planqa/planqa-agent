from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from planqa_review.llm.factory import build_llm_client
from planqa_review.benchmark import BENCHMARK_DOC_IDS, DEFAULT_QA_DATASET, DEFAULT_SOURCE_DIR
from planqa_review.diff_report import write_report
from planqa_review.experiment import ExperimentConfig, run_experiment, write_experiment_report
from planqa_review.models import DEFAULT_PROFILE, PROFILES
from planqa_review.pipeline import review_document
from planqa_review.run_stats import build_run_stats
from planqa_review.rulebook import parse_rulebook
from planqa_review.scoring import load_golden_rows
from planqa_review.structures import STRUCTURES

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

    # --structure picks a non-baseline review_fn (see structures/), same convention as
    # `experiment` — useful for a quick single-document smoke test of a new structure
    # before committing to a full benchmark run.
    profile_label = args.structure or args.profile

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

    start = time.perf_counter()
    if args.structure:
        result = STRUCTURES[args.structure](doc_id, document_text, rulebook, screen_llm, confirm_llm)
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
    print(
        f"{doc_id}: {len(result.issues)}건 지적, {stats.total_wall_seconds:.1f}초 — {json_path}, {md_path}"
    )
    for error in result.tier_errors:
        print(f"  ⚠️ {error}", file=sys.stderr)
    return 0


def cmd_experiment(args: argparse.Namespace) -> int:
    rulebook = parse_rulebook(args.rulebook)
    golden_rows = list(load_golden_rows(args.qa_dataset))
    doc_ids = tuple(args.doc_ids) if args.doc_ids else BENCHMARK_DOC_IDS

    # --structure picks a non-baseline review_fn (see structures/); config.profile then
    # becomes just a label (not a models.PROFILES lookup) — default it to the structure
    # name so the output path/summary stay descriptive without a separate flag.
    review_fn = STRUCTURES[args.structure] if args.structure else None
    profile_label = args.structure or args.profile

    config = ExperimentConfig(
        profile=profile_label,
        backend=args.backend,
        screen_model=args.screen_model,
        verify_model=args.verify_model,
        temperature=args.temperature,
        doc_ids=doc_ids,
    )
    experiment = run_experiment(config, rulebook, args.rulebook, args.source_dir, golden_rows, review_fn=review_fn)

    out_dir = args.out or Path("outputs/experiments") / profile_label / _timestamp()
    write_experiment_report(out_dir, experiment, rulebook)

    score = experiment.summary.score.overall
    print(
        f"{len(experiment.documents)}개 문서, recall={score.recall}, precision={score.precision}, "
        f"{experiment.summary.total_wall_seconds:.1f}초 — {out_dir}"
    )
    for doc in experiment.documents:
        for error in doc.result.tier_errors:
            print(f"  ⚠️ [{doc.doc_id}] {error}", file=sys.stderr)
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
        "--backend", default=None, help="overrides PLANQA_LLM_BACKEND (gemini|ollama|gateway|anthropic) — both roles unless overridden below"
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
    review_parser.set_defaults(func=cmd_review)

    experiment_parser = subparsers.add_parser(
        "experiment", help="벤치마크 문서 세트를 골든 데이터셋과 대조해 recall/precision·시간·토큰 비용을 측정"
    )
    experiment_parser.add_argument("--rulebook", type=Path, default=DEFAULT_RULEBOOK)
    experiment_parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    experiment_parser.add_argument("--qa-dataset", type=Path, default=DEFAULT_QA_DATASET)
    experiment_parser.add_argument(
        "--doc-ids", nargs="+", default=None, help="생략 시 benchmark.BENCHMARK_DOC_IDS 사용"
    )
    experiment_parser.add_argument("--out", type=Path, default=None, help="생략 시 outputs/experiments/<profile>/<timestamp>/")
    experiment_parser.add_argument("--backend", default=None, help="overrides PLANQA_LLM_BACKEND (gemini|ollama)")
    experiment_parser.add_argument("--screen-model", default=None, help="1단계 스크리닝용 모델(저비용)")
    experiment_parser.add_argument("--verify-model", default=None, help="2단계 정밀판정/컨텍스트 추출용 모델(고비용)")
    experiment_parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="샘플링 온도, 기본 0.0(ablation 재현성 위해) — 다양성 원하면 명시적으로 올릴 것",
    )
    experiment_parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        choices=sorted(PROFILES),
        help="프롬프트/로직 전략 (src/planqa_review/models/) — --structure 미지정 시(제안5 baseline) 적용",
    )
    experiment_parser.add_argument(
        "--structure",
        default=None,
        choices=sorted(STRUCTURES),
        help="구조 ablation용 — 지정 시 baseline(제안5) 대신 이 구조(src/planqa_review/structures/)로 실행, --profile은 무시됨",
    )
    experiment_parser.set_defaults(func=cmd_experiment)

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
