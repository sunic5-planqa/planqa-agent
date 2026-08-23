from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from planqa_review.document import Chunk
from planqa_review.llm.base import LLMClient

# 타문서 정합성(XDC) — "현재 문서 vs 참고문서" 비교 전용 모듈. 유진 문서(타문서와의_정합성_
# 룰북_Section1_후보매처_보충본.md) §1의 설계를 그대로 코드로 옮긴 것 — 단계 A(구조화 키 A,
# 별칭 B, Jaccard C)까지만 구현하고, 의미 유사도(신호 D, 임베딩)는 별도 PR(단계 B)에서 얹는다.
#
# 기존 bundled_screen_hybrid.py의 단일문서 파이프라인은 이 모듈을 몰라도 100% 그대로 동작한다
# — reference_documents가 없으면 이 모듈의 어떤 함수도 호출되지 않는다.


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """§1-2 스키마 그대로 — "이 문단이 틀렸다"가 아니라 "이 문단은 어떤 결정사항을 말하는가"의
    사실 추출. quote/canonical_terms는 후보 매칭(신호 A~D)에, 나머지는 Sonnet이 실제로 같은
    정책인지 판정할 때 근거로 쓴다."""

    doc_id: str
    location: str  # 이 레코드가 나온 chunk의 위치 라벨 (Chunk.location 재사용)
    quote: str
    policy_subject: str
    attribute: str
    action: str | None
    scope: str | None
    condition_exception: str | None
    value: str | None
    unit: str | None
    time_basis: str | None
    canonical_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReferenceIndex:
    """참고문서 1건을 결정 레코드로 뽑아둔 결과 — content_hash(text)로 캐시해, 같은 참고문서를
    여러 현재 문서에 대해 반복 검토해도 재추출하지 않는다(§1-2 "document_id + version 기준으로
    캐시"의 실제 구현 — version 필드가 없는 현재 백엔드 스키마 대신 텍스트 해시를 키로 쓴다)."""

    doc_id: str
    records: tuple[DecisionRecord, ...]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


_DECISION_RECORD_SYSTEM = (
    "You read numbered chunks of a Korean product-planning document and extract, for each "
    "chunk that states one, a structured record of a concrete policy DECISION — a number, "
    "range, condition, deadline, or processing outcome someone could look up and compare "
    "against another document. This is fact extraction, not judgment: do not decide whether "
    "anything is right or wrong, just describe what the chunk says. Skip chunks that state no "
    "such decision (goals, rationale, UI copy, etc. with nothing concrete to compare).\n"
    'Respond with JSON only: {"decision_records": [{"chunk_index": <int>, "quote": "<exact '
    'span the decision comes from>", "policy_subject": "<broad subject, e.g. 반품/배송/쿠폰>", '
    '"attribute": "<the attribute being decided, e.g. 신청 기한/수수료율>", "action": "<string '
    'or null>", "scope": "<who/what this applies to, or null>", "condition_exception": '
    '"<carve-out condition, or null>", "value": "<string or null>", "unit": "<string or '
    'null>", "time_basis": "<what the value is measured from, or null>", "canonical_terms": '
    '["<normalized keyword>", ...]}, ...]}'
)


def _build_record(item: dict, doc_id: str, location: str) -> DecisionRecord | None:
    quote = str(item.get("quote", "")).strip()
    policy_subject = str(item.get("policy_subject", "")).strip()
    attribute = str(item.get("attribute", "")).strip()
    if not quote or not policy_subject or not attribute:
        return None
    terms = item.get("canonical_terms")
    canonical_terms = tuple(str(t).strip() for t in terms if str(t).strip()) if isinstance(terms, list) else ()
    return DecisionRecord(
        doc_id=doc_id,
        location=location,
        quote=quote,
        policy_subject=policy_subject,
        attribute=attribute,
        action=str(item.get("action") or "").strip() or None,
        scope=str(item.get("scope") or "").strip() or None,
        condition_exception=str(item.get("condition_exception") or "").strip() or None,
        value=str(item.get("value") or "").strip() or None,
        unit=str(item.get("unit") or "").strip() or None,
        time_basis=str(item.get("time_basis") or "").strip() or None,
        canonical_terms=canonical_terms,
    )


# 공유 파싱 로직 — 참고문서 전용 추출 콜(extract_decision_records)과 현재 문서 스크리닝 콜에
#얹힌 decision_records(bundled_screen_hybrid._screen_pass) 양쪽에서 재사용한다.
def parse_decision_records(raw: object, doc_id: str, chunks: list[Chunk]) -> list[DecisionRecord]:
    if not isinstance(raw, list):
        return []
    records: list[DecisionRecord] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        chunk_index = item.get("chunk_index")
        if not (isinstance(chunk_index, int) and 0 <= chunk_index < len(chunks)):
            continue
        record = _build_record(item, doc_id, chunks[chunk_index].location)
        if record is not None:
            records.append(record)
    return records


# 참고문서 1건 전체를 한 번의 콜로 추출한다 — bundled_screen_hybrid._screen_pass가 한 위계의
# 청크 전부를 한 프롬프트에 묶어 보내는 것과 같은 이유(청크마다 콜을 나누면 참고문서 분량만큼
# 그대로 비용이 늘어난다). 현재 문서 문단의 decision_records 추출은 이 함수를 쓰지 않고
# bundled_screen_hybrid._screen_pass 안에서 기존 스크리닝 콜에 얹어 함께 반환한다(§1-1: "Gemini는
# 두 가지 결과를 동시에 반환한다") — 새 콜을 만들지 않기 위함.
def extract_decision_records(doc_id: str, chunks: list[Chunk], llm: LLMClient) -> list[DecisionRecord]:
    if not chunks:
        return []
    chunk_block = "\n\n".join(f"[{i}] ({chunk.location})\n{chunk.text}" for i, chunk in enumerate(chunks))
    prompt = f"Chunks:\n{chunk_block}\n\nReturn the decision_records JSON."
    response = llm.complete_json(system=_DECISION_RECORD_SYSTEM, prompt=prompt)
    raw = response.get("decision_records", []) if isinstance(response, dict) else []
    return parse_decision_records(raw, doc_id, chunks)


def build_reference_index(doc_id: str, chunks: list[Chunk], llm: LLMClient) -> ReferenceIndex:
    return ReferenceIndex(doc_id=doc_id, records=tuple(extract_decision_records(doc_id, chunks, llm)))


# ---- 별칭 사전 (신호 B) ----
# §1-4-B: "새 AI 호출이 아니라 코드와 프로젝트 설정값 추가" — 공통 항목만 시드하고, 검토 결과에서
# 반복되는 표현을 나중에 누적한다.
def load_aliases(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_term(term: str, aliases: dict[str, str]) -> str:
    stripped = term.strip()
    return aliases.get(stripped, stripped)


def _normalized_terms(record: DecisionRecord, aliases: dict[str, str]) -> frozenset[str]:
    return frozenset(_normalize_term(term, aliases) for term in record.canonical_terms)


# ---- 바이그램 Jaccard (신호 C) ----
# expr/review-agent(PR #33, 미머지)의 fewshot_retrieval.top_k_examples와 같은 접근 — 한국어는
# 공백 기준 토큰화가 안 되니 문자 bigram이 표준 대안(이슈 #20에서도 재사용 후보로 지목됨). PR #33
# 자체는 experiment 격리 목적이라 프로덕션이 거기 의존하면 안 되므로, 알고리즘만 그대로 복제한다.
def _char_bigrams(text: str) -> frozenset[str]:
    normalized = "".join(text.split())
    if len(normalized) < 2:
        return frozenset({normalized}) if normalized else frozenset()
    return frozenset(normalized[i : i + 2] for i in range(len(normalized) - 1))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def _record_bigrams(record: DecisionRecord) -> frozenset[str]:
    return _char_bigrams(f"{record.quote} {' '.join(record.canonical_terms)}")


# ---- 4개 신호 병합 (§1-4 마지막 규칙) ----
def match_candidates(
    current: DecisionRecord,
    indices: list[ReferenceIndex],
    aliases: dict[str, str],
    top_k: int = 3,
) -> list[DecisionRecord]:
    """현재 문단의 결정 레코드와 "같은 정책일 가능성이 있는" 참고 레코드 최대 top_k개를 반환한다
    — 여기서 "충돌한다"고 판정하지 않는다(§1-3), 그건 Sonnet의 몫이다. 신호 A(구조화 키)와 B(별칭)
    매칭은 전부 유지하고, 거기에 C(Jaccard) 상위 2개를 더한 뒤 중복 제거·우선순위 정렬해 top_k개로
    자른다 — §1-4 마지막 표의 규칙 그대로."""
    pool = [record for index in indices for record in index.records]
    if not pool or not current.quote:
        return []

    current_terms = _normalized_terms(current, aliases)
    current_bigrams = _record_bigrams(current)

    # 신호별로 어떤 참고 레코드가 어떤 신호에서 잡혔는지 추적 — §1-4 "두 가지 이상 신호에서 동시에
    # 발견된 후보"를 우선순위에 반영하기 위해 신호별 집합을 따로 모은다(레코드는 dataclass라 매칭
    # 대상 리스트의 인덱스로 식별 — DecisionRecord 자체가 hashable하지 않아도 되게).
    signal_hits: dict[int, set[str]] = {}

    def _mark(idx: int, signal: str) -> None:
        signal_hits.setdefault(idx, set()).add(signal)

    for idx, record in enumerate(pool):
        # A. 구조화 결정 키 일치 — policy_subject + attribute가 같으면 값이 다르든 같든 무조건 후보.
        if record.policy_subject == current.policy_subject and record.attribute == current.attribute:
            _mark(idx, "A")
        # B. 프로젝트 용어집/별칭 일치 — 정규화한 canonical_terms가 하나라도 겹치면 후보.
        if current_terms and current_terms & _normalized_terms(record, aliases):
            _mark(idx, "B")

    # C. 바이그램 Jaccard 상위 2개 — A/B에서 이미 후보가 나온 레코드라도 "표현이 비슷한 다른 정책을
    # 확인"할 수 있도록 별도로 추가한다(§1-4-C 3항).
    jaccard_scores = [(idx, _jaccard(current_bigrams, _record_bigrams(record))) for idx, record in enumerate(pool)]
    jaccard_scores.sort(key=lambda pair: pair[1], reverse=True)
    for idx, score in jaccard_scores[:2]:
        if score > 0:
            _mark(idx, "C")

    if not signal_hits:
        return []

    # 정렬 우선순위: A/구조화 일치 > 여러 신호에서 동시 발견 > Jaccard 점수. 안정 정렬(sort는
    # stable)이라 동점일 때 pool 순서(참고문서 등장 순서)가 유지된다.
    def _sort_key(idx: int) -> tuple[int, int, float]:
        signals = signal_hits[idx]
        has_structural = 1 if "A" in signals else 0
        return (-has_structural, -len(signals), -next((s for i, s in jaccard_scores if i == idx), 0.0))

    ranked_indices = sorted(signal_hits, key=_sort_key)
    return [pool[idx] for idx in ranked_indices[:top_k]]
