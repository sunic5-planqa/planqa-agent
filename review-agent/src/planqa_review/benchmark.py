from __future__ import annotations

from pathlib import Path

from planqa_review.scoring import GoldenRow

DEFAULT_SOURCE_DIR = Path("data/source_documents")
DEFAULT_QA_DATASET = Path("data/qa_dataset/qa_dataset_frozen.xlsx")

# DOC-001..020 are the real NxEF documents in scope for now (021-040 are teammate-generated
# synthetic docs reserved for later rule-coverage gap-filling; DOC-000 has no real source
# text). Within that range this is the subset already manually reviewed before the ablation
# infra existed — reusing it keeps ablation runs cheap while still covering both
# true-positive-rich docs (all ten have golden rows) and a deliberate zero-violation
# false-positive check (DOC-008).
BENCHMARK_DOC_IDS: tuple[str, ...] = (
    "DOC-003",
    "DOC-004",
    "DOC-005",
    "DOC-006",
    "DOC-007",
    "DOC-008",
    "DOC-010",
    "DOC-011",
    "DOC-012",
    "DOC-015",
    "DOC-016",
)


def resolve_source_path(source_dir: Path, doc_id: str) -> Path:
    matches = sorted(source_dir.glob(f"{doc_id}_*"))
    if not matches:
        raise FileNotFoundError(f"{doc_id}에 해당하는 소스 문서를 찾을 수 없음: {source_dir}")
    if len(matches) > 1:
        raise ValueError(f"{doc_id}에 대해 소스 문서가 여러 개 존재함: {matches}")
    return matches[0]


def golden_rows_for_benchmark(
    golden_rows: list[GoldenRow], doc_ids: tuple[str, ...] = BENCHMARK_DOC_IDS
) -> tuple[GoldenRow, ...]:
    return tuple(row for row in golden_rows if row.doc_id in doc_ids)
