# 인수인계 — eval-agent 결정론적 채점 + review-agent Sentence 위계 계획 (compact 직전)

> 계획 자체는 `C:\Users\HYESEO\.claude\plans\replicated-jingling-pudding.md`에 있고
> 사용자가 승인했다("현재 plan파일로 진행할게"). 이 문서는 그 계획을 compact 이후에도
> 막힘없이 실행할 수 있도록, plan 파일에는 요약만 들어간 세부 사실들(정확한 코드
> 시그니처, 실제 location 문자열 예시, 테스트 관례, 의존성 현황 등)을 통째로 옮겨
> 적어두는 것이다. **plan 파일 + 이 문서 두 개를 같이 읽어야 실행 가능.**

## 지금 정확히 어디에 있는가

- 브랜치 `feature/review-agent`(review-agent 쪽 작업 위치, 레포 루트는
  `c:\Users\HYESEO\Desktop\planqa-eval-agent`, review-agent는 그 하위 `review-agent/`).
- review-agent 실험은 **완전히 종료됨** — 최종 결론은
  `docs/experiments/results_2026-08-10_final_summary.md`(가장 먼저 읽을 문서),
  가장 마지막으로 실제로 돌린 실험은 hybrid 세부 축 3종(위반예시↑/예외예시↑/동적검색)이고
  결과는 `docs/experiments/results_2026-08-10_phase3_hybrid_subaxis.md`에 있음 — **세
  축 다 기준선(`bundled_screen_hybrid`)과 eval-agent 기준 정확도 완전 동률, 비용만
  26~28% 증가라 채택 안 함.** 최종 채택 구조는 `bundled_screen_hybrid`(2단계 screen=
  Gemini/confirm=Sonnet, 콜통합, 룰텍스트+퓨샷) 그대로.
- 이 구조는 `sync/review-agent-demo-2` 브랜치로 PR #21 → `dev` 병합 완료(팀원 kayo2e가
  리뷰 중 실제 버그 4~6건 찾아서 고침 — Level.WORD KeyError, JSON 복구 문자열 컨텍스트
  버그, Gemini 라운드로빈 공유 안 되는 버그, isolate_client try 블록 밖 문제 등). 이
  버그들의 동일 원인 코드가 `feature/review-agent`에도 있어서 **이미 전부 포팅해서
  커밋해뒀음**(`fa5f668`, `d016672`, `02f9ecc`, `47d8fa5` — 4개 커밋, 238개 테스트 통과).
  push는 아직 안 함(요청 없었음).
- **`dev`는 이제 더 안 건드리는 걸로 확정** — 데모2가 실서비스용 최종 후보일 가능성이
  높다고 판단, 이후 모든 실험/수정은 `feature/review-agent`(review-agent)와 새로 만들
  `feature/eval-agent`(eval-agent)에서만.
- **지금 시작하려는 작업**: GitHub 이슈 #20(eval-agent 매칭/FP판정이 단일 LLM 의존이라
  결정론적이지 않음)을 팀원 기다리지 않고 우리가 직접 고침 — 목적은 review-agent 구조
  실험을 **더 신뢰할 수 있는 정확도로 재채점**해서 전체적인 실험결과 보고서를 쓰는 것.
  추가로 review-agent의 Sentence 위계 판정 제약도 같이 고치기로 함(아래 설명).
  **이 작업은 아직 코드 한 줄도 안 건드렸음 — 계획만 승인된 상태.**

## eval-agent → dev PR 안 함 (중요한 정책 결정)

처음엔 "다 고치고 테스트 통과하면 dev로 PR까지" 하려 했는데, 사용자가 반대함 — 이유:
이번 수정은 애초에 "우리 재채점 목적"으로 시작한 거라, 팀 전체가 쓰는 도구에 구조적
변경(LLM triage 완전 제거, scipy 의존성 추가 등)을 합의 없이 PR로 얹는 건 부적절.
**`feature/eval-agent`에서 구현·검증하고 우리 재채점 용도로만 쓴다. push/PR 둘 다 안 함.**

## review-agent 데모2 PR 관련 메타 발견 (실행에 직접 필요하진 않지만 맥락상 중요)

`git show origin/dev:README.md`+ADR(`docs/adr/0001-monorepo-workspace-and-async-eval-service.md`)
확인 결과:
- **review-agent의 실제 배포본은 이 모노레포가 아니라 `planqa-backend`에 벤더링(복사)된
  별도 코드**(`backend/src/sunnic_backend/qa_engine/review_agent/`). `services/review-agent`
  (이 모노레포)는 "앞으로의 canonical 위치"일 뿐, 벤더링된 카피는 자동 업데이트 안 됨 —
  재동기화는 그 저장소 쪽 별도 수동 작업. 즉 데모2가 `dev`에 병합됐다고 곧바로 실서비스가
  되는 게 아님(누군가 벤더링을 다시 해줘야 함) — 그래도 "다음 동기화 때 그대로 반영될
  유력 후보"라는 판단은 유효해서, review-agent를 더 안 건드리는 결정 자체는 바뀌지 않음.
- **`tools/eval-agent`는 정의상 절대 배포 안 됨**("eval-agent also has zero reason to
  ever be deployed — it's a CI-time, golden-comparison-only tool", ADR 원문). `services/`
  (배포됨) vs `tools/`(CI 전용, 영원히 안 배포) 구분이지 "안정 vs 실험"의 구분이 아님.
  다만 `dev`에 실제 CI 파이프라인은 아직 없음("no actual CI YAML was added") — 순수
  컨벤션/문서상의 구분.
- `feature/eval-agent` 브랜치는 `origin/dev` 대비 **51 commits behind, 0 ahead** — 이미
  전부 dev에 병합된 죽은 브랜치. eval-agent의 그 이후 작업은 dev에 직접 커밋되거나
  `fix/*` 짧은 브랜치(예: `fix/eval-agent-golden-scoping-and-triage-taxonomy`)로 진행됨.
  **계획: 이 브랜치를 `origin/dev` 현재 tip으로 재설정해서 재사용**(기존 커밋은 이미 다
  dev에 있으니 잃는 것 없음).

## eval-agent 현재 코드 — 정확한 시그니처/로직 (Explore 결과 그대로, `origin/main` 기준)

경로: `tools/eval-agent/src/planqa_eval/`. 공유 스키마: `packages/planqa-schemas/src/planqa_schemas/`.

### `prefilter.py` (전체, ~35줄)
```python
def category_of(rule_id: str) -> str:
    return rule_id.split("-", 1)[0]

def group_by_doc_and_category(issues: list[Issue]) -> dict[str, dict[str, list[Issue]]]: ...

def candidate_pairs(golden: list[Issue], predicted: list[Issue]) -> dict[str, dict[str, tuple[list[Issue], list[Issue]]]]:
```
`(doc_id, rule_id 접두사)`로만 버킷팅. location 기반 필터링 전혀 없음.

### `matcher.py`
- `MatchResult`(frozen dataclass): `matched: list[tuple[Issue,Issue]]`, `fn_candidates`,
  `fp_candidates` (전부 기본값 `[]`).
- `match_bucket(golden, predicted, llm) -> MatchResult`: 양쪽 다 비면 콜 없이 빈 결과,
  한쪽만 비면 콜 없이 나머지 전부 fn/fp, 둘 다 있으면 **단일 LLM 콜** 하나로
  `{"matches":[{"golden_index":int,"predicted_index":int}]}` 받음. 관대한 프롬프트
  ("Err on the side of matching when in doubt... same location/span is a strong signal
  but not a hard requirement"). 방어적 파싱(범위 밖 인덱스/중복 인덱스 재사용 무시).
- `match_all(golden, predicted, llm)`: `prefilter.candidate_pairs`로 나눈 버킷마다
  `match_bucket` 호출해서 합침.
- **텍스트 유사도/위치 겹침 로직은 전혀 없음** — 매칭은 100% LLM에 위임.

### `new_rule_triage.py`
- `Verdict = Literal["false_positive","new_rule_candidate","valid_but_unlabeled","human_review"]`
- `TriageResult`(frozen): `predicted: Issue`, `verdict`, `reasoning: str|None=None`, `ambiguous: bool=False`
- `triage_fp_candidates(fp_candidates, rulebook, llm) -> list[TriageResult]`: 전부 **하나의
  배치 LLM 콜**로 처리(`{"triage":[{"index","reasoning","verdict"}]}`). 배치 전체가 파싱
  안 되면 개별 fallback, 특정 인덱스만 빠지면 그 항목만 개별 fallback. 빈 리스트면 콜 없음.
- `triage_ensemble`/`triage_candidates_ensemble`: 앙상블 다수결 버전(이번 범위 밖, `judge`
  쪽 로직이라 그대로 유지).

### `aggregator.py`
- `ConfusionCounts`(frozen): `true_positive=0, false_negative=0, false_positive=0` +
  `.recall`/`.precision` property(분모 0이면 `None`).
- `AggregateReport`(frozen): `overall`, `overall_relaxed=ConfusionCounts()`,
  `tier_accuracy: float|None=None`, `by_category={}`, `by_level={}`,
  `new_rule_candidate_count=0`, `valid_unlabeled_count=0`, `human_review_count=0`,
  `excused_miss_count=0`.
- `aggregate(result: PipelineResult) -> AggregateReport` 카운팅 규칙(정확히):
  - **엄격(`overall`)**: `VerifiedMatch.fully_correct`(rule_id **and** level 둘 다 일치)
    만 TP. 아니면 golden 쪽 category/level에 FN **+** predicted 쪽 category/level에 FP
    (하나의 오매칭이 miss와 phantom catch 둘 다 만듦).
  - **`overall_relaxed`**: rule_id만 일치하면 TP(레벨 무관), 레벨도 맞으면
    `tier_correct += 1`. rule_id 자체가 안 맞으면 relaxed FN **+** relaxed FP 둘 다.
  - **`tier_accuracy`** = `tier_correct / rule_id_match_count`(rule_id 매칭된 것 중 레벨도
    맞은 비율), 매칭 0건이면 `None`.
  - **미스(`VerifiedMiss`)**: `excused=True`면 `excused_miss_count`만, recall에서 완전
    제외. `excused=False`면 FN.
  - **미매칭 predicted의 triage verdict**: `"false_positive"`→FP, `"new_rule_candidate"`
    /`"valid_but_unlabeled"`/`"human_review"`→각자 카운트만 증가(precision 분모 제외).
  - `overall` = `by_category` 합. `by_category`/`by_level` 키는 `category_of(rule_id)`/
    `issue.level`로 동적 생성(하드코딩 없음).
- `BaselineComparison`/`compare_to_human_baseline`: 이번 범위 밖, 안 건드림.

### `pipeline.py`
```python
@dataclass(frozen=True, slots=True)
class PipelineResult:
    verified_matches: list[VerifiedMatch]
    judge_scores: list[JudgeScore]
    verified_misses: list[VerifiedMiss]
    triage_results: list[TriageResult]

def run_pipeline(golden, predicted, rulebook, source_dir, llm, *, judge_assembly=None) -> PipelineResult:
```
`match_result = match_all(...)` → (앙상블 있으면 `judge_matches_ensemble`+
`triage_candidates_ensemble`, 없으면 `judge_matches`+`triage_fp_candidates`) →
`PipelineResult(verify_matches(match_result.matched), judge_scores,
verify_misses(match_result.fn_candidates, ...), triage_results)`. **`fn_candidates`(놓친
golden)는 절대 triage 안 됨 — triage는 미매칭 predicted에만 적용.** `judge_matches`(매칭된
쌍의 rubric 채점)는 이번 범위 밖, 그대로 둠.

### `Issue` 스키마 (`packages/planqa-schemas/src/planqa_schemas/schema.py`)
```python
class Level(StrEnum):
    DOCUMENT = "Document"; LOGICAL_UNIT = "Logical Unit"; PARAGRAPH = "Paragraph"
    SENTENCE = "Sentence"; WORD = "Word"

@dataclass(frozen=True, slots=True)
class Issue:
    doc_id: str; level: str; rule_id: str; location: str; description: str
    exception_ref: str|None=None; source: str=""; issue_id: str|None=None
    original_text: str|None=None; rationale: str|None=None; fix_direction: str|None=None
    related_location: str|None=None; related_original_text: str|None=None  # LG/LF/GA만
```
`location`은 **golden/predicted 공통으로 완전 자유 텍스트**, 파싱/구조화 전혀 없음.
`level`은 `str`(런타임에 `Level`로 검증 안 됨).

### `verifier.py`
```python
class VerifiedMatch:
    golden: Issue; predicted: Issue; rule_id_match: bool; level_match: bool
    @property
    def fully_correct(self): return self.rule_id_match and self.level_match
```
`verify_matches`는 순수 문자열 완전일치(`==`), 유사 매칭 로직 전혀 없음 — **Level 부분
점수를 넣을 자리가 바로 여기**. `verify_misses`/`has_valid_reference_exception`은 별개의
결정론적 인용구-예외 체크(문단 블록 안에 인용 패턴 + 인용된 키워드가 같이 있으면 excuse)
— 이미 있는 결정론적 로직 예시로 참고할 만함(LLM 없이 동작).

### 실제 golden location 문자열 예시 (`tools/eval-agent/data/qa_dataset/qa_dataset_2026-08-05.xlsx`, "golden dataset" 시트)
결정론적 매처가 실제로 다뤄야 할 표기 다양성:
- 범위: `2-1~2-4 전반`(DOC-006, 이슈에서 언급한 그 예시), `4-1, 4-2`(콤마 목록), `3장, 4장 전체`
- 관계형(LG/LF/GA, 두 위치 비교): `3장 KPI vs 4장 기술 제약`, `1-a/3-1 기본 방식 ↔ 5장 운영 가이드(내부)`
  — `vs`와 `↔` 혼용됨, `>`로 중첩도 있음: `02. 인증 오류 개선 > 2-1. 문제 정의 ↔ 2-2. 개선 방안`
- 단순 단일 위치: `4-2 주문 취소 정책`, `1장 프로덕트 목적`
- **predicted 쪽(review-agent 출력)은 같은 위치를 다른 문자열로 표현**: golden
  `"1-a 문제 정의"` vs predicted `"1. 프로덕트 목적 > a. 문제 정의"` — 완전 문자열 일치는
  구조적으로 불가능, 유사도/구조 파싱이 실제로 필요한 이유.

### 테스트 관례
- `tests/conftest.py`: `ScriptedLLM`(스크립트된 응답 큐, `.calls` 기록), `BrokenBatchLLM`
  (첫 콜이 `JSONDecodeError`, 그다음부터 정상 — 배치→개별 fallback 테스트용). 픽스처
  `xlsx_path`/`rulebook_path`/`source_dir`(실제 `tools/eval-agent/data/` 파일).
- `tests/test_matcher.py`: `_issue(doc_id, rule_id, location="x")` 팩토리, empty-side는
  `llm.calls == []`로 콜 스킵 검증.
- `tests/test_aggregator.py`: `_issue`/`_judge`/`_result` 팩토리로 `VerifiedMatch`/
  `VerifiedMiss`/`TriageResult`를 **직접 생성**해서 aggregator만 단위 테스트(matcher/
  verifier/triage 안 거침) — 새 aggregator 필드 테스트도 이 패턴 유지.
- `tests/test_verifier.py`: 실제 `rulebook_path`/`source_dir` 픽스처(LLM 모킹 없음) —
  결정론적 로직 테스트의 정확한 선례. `location="2-1~2-4 전반"`이 이미 이 파일의
  `test_doc006_ae01_citation_does_not_excuse_the_miss`에 실 fixture로 존재.

### 의존성
`scipy`는 이 모노레포 어디에도 없음(5개 `pyproject.toml` + `uv.lock` 확인). 이분 매칭에
필요하면 `tools/eval-agent/pyproject.toml`에 신규 추가(CI 전용 도구라 배포 리스크 없음).

## review-agent — Sentence 위계 판정 통찰 (compact로 잃으면 안 되는 추론 과정)

계기: `AE-03`/`DOC-003` golden이 `level=Sentence`인데 우리 예측은 항상 `level=Paragraph`
(rule_id는 맞음, level만 불일치 — eval-agent 재채점 리포트에서 `rule_id_match=true,
level_match=false` 확인됨). 원인 추적 결과:

- `document.py`의 `resolve_reported_level`은 "청크보다 넓은 위계 주장(승격)만 신뢰,
  좁은 위계 주장(강등)은 무조건 거부"하는 정책.
- **이 비대칭이 논리적으로 뒤바뀌어 있다는 게 이번 분석의 핵심 통찰**:
  - **승격**(예: 문단 청크에서 "이건 사실 문서 전체 문제") = 청크에 안 보여준 것에 대한
    주장 → 신뢰하려면 실제로 그 범위를 보여줘야 함(그래서 GA/LG/LF를 문서 전체 pass로
    옮긴 게 맞는 방향). **여기는 그대로 유지.**
  - **강등**(예: 문단 청크에서 "이건 그중 이 문장 하나만의 문제") = 이미 보여준 것
    **안에서** 범위를 좁히는 주장이고, `original_text`가 그 청크 안의 실제 인용문인 이상
    근거가 확실함. **이걸 무조건 거부하는 지금 코드가 버그.**
  - 문단 pass가 문단 전체(여러 문장)를 이미 다 보고 있으므로, "이 문제는 그중 이 문장
    하나"라고 말하는 걸 못 믿을 이유가 없음 — 오히려 원래보다 더 안전한 축소 주장.
- golden 자체도 Sentence 라벨에 문단급 위치 문자열을 그대로 씀(AE-03/DOC-003:
  `location="4. 상품 컨디션 등급 기준 > 표 하단 서술"`, `level=Sentence`) — 강등 허용
  시 위치 문자열을 더 정밀하게 만들 인프라가 필요 없다는 뜻(golden도 안 그렇게 함).
- **수정 방향**: `_LEVEL_COARSENESS[claimed_level] >= _LEVEL_COARSENESS[chunk_level]`일
  때만 거부하던 조건을, `claimed_level == chunk_level`(동일)일 때만 그대로 두고
  나머지(더 넓든 좁든 `_LEVEL_COARSENESS`에 있는 값이면)는 인정 — 단, 위치 문자열은 강등
  시 그대로 유지(트림 로직 적용 안 함). `bundled_screen_hybrid.py`의
  `_CONFIRM_HYBRID_SYSTEM`도 "더 넓은 경우"만 말하던 level 지시문에 "청크 안에서 특정
  문장 하나에만 해당하면 Sentence로 표시하라"는 강등 사례 추가 필요(안 그러면 코드는
  허용해도 모델이 안 시도함).

## 관련 메모리

- `feedback_no_synthetic_fewshot_examples` — eval-agent location_match도 실 데이터
  범위 안에서 테스트할 것(합성 location 문자열 만들지 말고 실제 xlsx 값 사용).
- `feedback_no_push_without_request` — `feature/review-agent`의 4개 커밋도 push 안 함,
  `feature/eval-agent` 작업도 push/PR 안 함(이번 정책 결정).
- `feedback_no_unicode_escapes_in_tool_text` — 이번 세션에 4번째로 재발함, 메모리
  강화해둠(기계적 사전 스캔 절차 추가) — AskUserQuestion 등에 한글 쓸 때 반드시 재확인.

## 다음 세션(또는 compact 이후) 체크리스트

- [ ] plan 파일(`C:\Users\HYESEO\.claude\plans\replicated-jingling-pudding.md`)의
  "실행 순서" 1~10번을 그대로 따라가면 됨 — 1번(`feature/eval-agent` 재설정)부터 시작.
- [ ] `location_match.py`는 위 "실제 golden location 문자열 예시"를 테스트 fixture로
  직접 사용할 것(합성 만들지 말 것).
- [ ] eval-agent 작업은 `dev`로 push/PR 안 함 — 로컬 브랜치 전용, 우리 재채점 용도.
- [ ] review-agent Sentence 위계 수정은 `feature/review-agent`에 그대로 커밋(이미 이
  브랜치가 실험 전용으로 확정됐으니 자유롭게).
- [ ] 재채점은 이미 저장된 `predictions.json`들을 재사용 — API 비용 없음, 승인 불필요.
