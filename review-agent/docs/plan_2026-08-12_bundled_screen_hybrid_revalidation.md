# bundled_screen_hybrid 20문서 재검증 + 정확도 개선 (실제 Sonnet5, 속도/비용 최적화)

> 실행계획 문서. 승인된 원본은 `C:\Users\HYESEO\.claude\plans\replicated-jingling-pudding.md`
> (Claude Code plan 파일, git 추적 대상 아님) — 이 파일은 그 내용을 저장소에도 남겨서
> git으로 버전 관리되게 한 사본이다. 2026-08-12 사용자 승인 완료(ExitPlanMode).

## 자율 실행 범위 (사용자가 자리를 비운 동안의 경계)

사용자가 실행 도중 잠들 예정이라 그 사이엔 허락을 받을 수 없다. 이 계획이 승인되면
아래 경계로 자율 실행한다.

**승인 없이 진행**:
- 실행순서의 코드 작업 전부(PR #30/#32 포팅, 발견1–8 구현, `fewshot_bank.py` 재구축,
  캐싱·resumable 실행·Batch API 인프라) — 전부 로컬 git 커밋 단위, 비용 없음, 되돌리기
  쉬움.
- 최소 비용 검증 단계(mocked 테스트+더미 배치+1문서 실 호출)와 전체 20문서 Batch API
  실행(약 $7 예산) — 이미 대화에서 여러 차례 상세히 논의·합의된 지출이라 진행.
- eval-agent 재채점(API 비용 없음), 결과 보고서 작성 — "새 절 추가 vs 별도 문서"처럼
  "사용자와 상의"로 남겨둔 소소한 형식 결정은 가장 합리적인 쪽으로 직접 선택하고, 그
  이유를 보고서 서두에 남겨서 나중에 검토·수정하기 쉽게 한다.

**승인 없이는 하지 않음**:
- git push, 새 PR 생성, 기존 PR 머지 — `feature/review-agent`/`feature/eval-agent`는
  계속 로컬 전용(기존 원칙 그대로).
- **PR #33(expr/ 폴더 이전) 머지** — 마지막에 확인받는다.
- `main`/`dev` 브랜치를 어떤 형태로든 건드리는 것.
- **비용 상한은 $7, 절대치, 여유 없음** — 매 단계(1문서 스모크 테스트, screen 배치,
  confirm 배치, MI·AE재검증 배치 등) 제출/호출 **전에** 지금까지 실제로 쓴 비용 +
  이번 단계 예상 비용을 계산해서, 그 합이 $7을 넘을 것 같으면 그 단계를 제출/호출하지
  않고 그 자리에서 멈춘다(배치는 한번 제출하면 이미 처리된 만큼은 취소해도 과금되므로,
  사후 감시가 아니라 제출 전 사전 추정으로 막아야 함). 이미 완료된 부분까지의 결과는
  그대로 보존하고 어디서/왜 멈췄는지 기록.
- 이번에 다루지 않기로 한 항목(예: LG/GA 재현율)을 임의로 스코프에 추가하는 것.

**계획에 없는 진짜 블로커를 만나면**: 멈춰서 기다리지 않고 가장 보수적인 선택을 한 뒤
그 판단과 근거를 진행 기록(커밋 메시지/`progress.md`)에 남기고 계속한다.

## Context

### 왜 재검증하는가

기존 ①②③ 구조 실험은 전부 파일럿 5문서(DOC-001/003/006/008/012)만 대상으로 했다.
`benchmark.py`에 이미 문서화돼 있던 원래 설계는 DOC-001–020 전체가 실제 대상 문서
(`BENCHMARK_DOC_IDS` 기본값)이고, DOC-021–040은 팀이 만든 룰 커버리지 보충용 문서,
DOC-000은 소스 문서 없이 golden 예시만 모아둔 풀이다. golden 131건 중 DOC-001–020에
19건(현재 6건의 3배, 룰 종류도 4→11개)이 있어서, 20문서로 넓히면 표본이 훨씬 커진다.

### 왜 "다른 모델로 대신 측정"을 기각했는가

로컬 오픈소스 모델로 confirm을 대신 돌려서 비용을 아끼는 방향을 검토했으나 기각했다 —
이미 "모델을 바꾸면 어느 구조가 이기는지 결론 자체가 뒤집힌다"는 걸 직접 증명한 바
있다(①번 실험: confirm이 Gemini일 때는 1단계 승, Sonnet일 때는 2단계 승으로 결론이
뒤집혔음). 로컬 모델로 다시 겨루면 "그 모델 기준 어느 구조가 이기는가"에 대한 답만
나올 뿐, 실제 서비스(Sonnet5) 성능 평가를 대신하지 못한다.

### 비용 재산정 — 실제 서비스 관측치로 재보정

`bundled_screen_hybrid`의 confirm+context 토큰이 문서당 8,792(5문서 실측 평균), 실제
서비스 관측 비용($0.3–0.4/문서)으로 역산한 단가는 $34–46/M 토큰(중간값 $40/M).

| 구조 | 20문서 재추정 (Sonnet5) |
| --- | --- |
| **bundled_screen_hybrid (데모2, 이번 재검증 대상)** | **약 $7.00** |
| Phase1 cell3 | 약 $33.54 |
| Phase1 direct_verdict | 약 $26.62 |
| (나머지 9개 구조 합) | 약 $117 |
| **12개 구조 전부** | **약 $184** |

### 결정: 범위를 데모2 구조 하나로 좁힌다

①②는 이미 효과 크기가 커서 6건 표본으로도 결론이 견고하다 — $184를 들여 12개 구조
전부 재확인할 필요 없음. 최종 채택된 실제 서비스 구조(`bundled_screen_hybrid`) 하나만
leak-safe 20문서로 재실행해서 결론이 유지되는지 확인하는 것으로 범위를 좁힌다.

## 정확도 개선 — 데모2 사용자 피드백 조사 결과 + 실사용자 피드백 13개

데모2 배포 후 GitHub 이슈/PR(`sunic5-planqa/planqa-agent`, `sunic5-planqa/planqa`)과
사용자가 직접 전달한 실사용자 피드백 13개 원문을 함께 조사했다.

### 발견 1 — 카테고리 오분류(GA↔TC, TC↔MI)

이슈 [#26](https://github.com/sunic5-planqa/planqa-agent/issues/26): GA가 TC로,
TC가 MI로 오분류되는 문제. PR [#27](https://github.com/sunic5-planqa/planqa-agent/pull/27)
에서 `_CATEGORY_BOUNDARY_NOTES` 프롬프트 보강 상수로 해결됨(순수 프롬프트, 시그니처
변경 없음) — 우리 `feature/review-agent`에는 없음, 그대로 포팅. 실사용자 피드백
8·11번이 이 문제의 실증 사례.

### 발견 2 — MI/AE 카테고리 과탐지

MI는 문단 단위로만 검토돼서, confirm이 "이 문단엔 없다"를 "문서 전체에 없다"로 착각.
백엔드는 벤더링 정책상 소스를 못 고쳐서 `qa_jobs.py`에 별도 재검증 단계를 우회로
추가함(`_verify_mi_finding`, PR [#28](https://github.com/sunic5-planqa/planqa/pull/28),
AE로 확장 PR [#55](https://github.com/sunic5-planqa/planqa/pull/55)). 우리는
review-agent 소스를 직접 소유하니 `bundled_screen_hybrid.py`의 `review_document()`
마지막 단계에 정식으로 구현한다. 실사용자 피드백 7번이 이 패턴의 실증 사례.

### 발견 3 — 위치/하이라이트가 소제목에 잡히는 근본 원인 (코드 레벨 버그)

`bundled_screen_hybrid.py`의 `_screen_pass`/`_confirm_pass`가 모델이 반환하는
`quoted_text`/`original_text`가 실제로 그 청크의 본문 부분 문자열인지 전혀 검증하지
않아서, 모델이 헤더 라벨을 그대로 인용해도 통과된다. 수정: 정확 일치 → 정규화
재시도 → 바이그램 Jaccard 근접탐색으로 검증하고, 실패 시 원문에서 가장 가까운
매칭 서브스트링으로 인용문만 교체(판정은 유지).

### 발견 4 — LF가 "사실 모순"까지 흡수하는 카테고리 경계 문제

LF는 흐름/가독성 문제 정의인데, 서로 다른/충돌하는 사실을 말하는 문장까지 LF로
오분류(피드백 7번). `_CATEGORY_BOUNDARY_NOTES`에 세 번째 구분 추가: 사실이 다르면
GA/LG, LF는 절대 아님.

### 팀 GitHub 최신 변경사항

- PR [#30](https://github.com/sunic5-planqa/planqa-agent/pull/30)(머지됨): `Issue`에
  `related_original_text` 필드 추가(LG/LF/GA만) — 발견5 작업 전 먼저 포팅.
- PR [#32](https://github.com/sunic5-planqa/planqa-agent/pull/32)(열려있음): 아래
  발견8.
- PR [#33](https://github.com/sunic5-planqa/planqa-agent/pull/33)(열려있음):
  `feature/review-agent`를 모노레포의 `expr/review-agent/`로 옮기자는 조직적 제안 —
  코드 변경 없음, 머지는 최종 사용자 승인 후.

### 발견 5·6 — 중복 위치 2곳 노출 + 삽입형 제안 프레이밍 확장

사용자가 공유한 팀 프레이밍 규칙 문서(Notion "Ver 1/Ver 2") + 실제 백엔드/프론트
코드 확인 결과: 백엔드(`qa_jobs.py`의 `_frame_type`)는 이미 Notion 규칙대로
구현돼 있지만, 프론트(`issueOverlay.ts`)는 아직 object 방식(박스 하나)으로만
그려서 range/insert_range를 시각적으로 반영 못함.

- **발견 5(RD 중복 위치 2곳)**: RD도 `related_location`+`related_original_text`를
  채우도록 확장(PR #30 패턴 재사용). 프론트 갱신 전까진 화면에 두 번째 박스가 안
  보인다는 걸 결과 보고서에 명시.
- **발견 6(MI 삽입 프레이밍)**: MI가 이미 보고하는 위계(Document/LogicalUnit/
  Paragraph/Sentence)를 재사용해서 `original_text`를 넓힌다:

  | reported level | 처리 |
  | --- | --- |
  | Sentence | 그 문장이 속한 Paragraph 청크 전체로 넓힘 |
  | Paragraph | 앞뒤 인접 Paragraph 청크까지 합쳐서 넓힘 |
  | LogicalUnit/Document | 앞뒤 인접 LogicalUnit까지 합쳐서 넓힘 |
  | (문장보다 짧은 구/단어) | 그 문장 하나로 좁힘 |

  object 렌더러가 "텍스트 찾아서 박스 하나"만 그리므로, 발견6은 review-agent만
  고치면 지금 당장도 시각적으로 바로 효과가 남(발견5와 다른 점).

### 발견 7 — TC 탐지실패: MI/AE와 동일한 "짧은 요약, 전체 용어집 아님" 문제

TC는 Paragraph 단위로만 검토되고 서술형 요약(`global_context`)만 받아서 앞서 쓴
용어를 재표현으로 못 알아보거나(재현율 실패) 새 개념으로 오해해 MI로 오탐지.
수정: `_extract_global_context`가 명시적 용어 목록도 함께 추출.

LG/GA 탐지실패는 이번 스코프에서 고치지 않음 — 이미 document-tier인데도 못 잡는 건
모델의 단일 패스 추론 깊이 한계로 보이며 저비용 수정 방법을 못 찾음(알려진 한계).

### 발견 8 — 참조-예외 정규식이 프로즈 인용을 못 잡는 버그

PR [#32](https://github.com/sunic5-planqa/planqa-agent/pull/32): `verifier.py`의
`_CITATION`이 "문서명(DOC-XXX) 참고" 형태만 인식, golden 예외조건 4건(AE-01/GA-03/
LG-03/TC-02)의 프로즈 인용을 못 잡음. `is_reference_excused_by_rule`이
`bundled_screen_hybrid.py`의 `_confirm_pass`에서 실제로 호출되므로, 우리가 재검증할
구조의 실제 false positive 원인. `_CITATION_DOC_CODE`+`_CITATION_NATURAL`로 분리,
review-agent와 eval-agent 양쪽에 동일 적용.

### 범위 밖 (review-agent 소스로 고칠 수 없음)

- 팝업 위치, 방향성 제안 유사도 측정, 넘버링 표기 — 프론트/백엔드 UI 문제.
- overview 개수 불일치 — 원인 미특정, "추가 조사 필요".
- LG/GA 재현율, 전반적 비결정성 — 알려진 한계로 명시.

## 속도/비용 최적화 (Batch API 포함)

1. prompt caching(`cache_prefix`) — 룰+퓨샷 블록.
2. confirm 프롬프트 룰 블록 중복 제거.
3. 캐싱은 20문서 전체에 걸쳐 효과 누적.
4. global_context도 캐싱 대상.
5. 발견2 재검증 콜 시스템 프롬프트도 자동 캐싱.
6. 문서 단위 병렬화(소규모 검증에서만, `ThreadPoolExecutor`).
7. **Batch API(50% 할인) — 포함**. screen→confirm→MI/AE재검증 3단계 배치로 나눔,
   각 요청에 `(doc_id, chunk_index, ...)` `custom_id` 부여.

   **시간 제약(2026-08-12 재조정, 5시간→3시간 축소)**: 3단계 전체를 합쳐 최대
   3시간. 실제 후기 기준 대부분(5,000건 이하)은 1–2시간 내 끝나지만, 진행률
   표시가 없어 4시간+ 걸린 사례도 있음
   ([Enterprise DNA](https://enterprisedna.co/resources/guides/guide-anthropic-batch-api/)) —
   하드 타임아웃+폴백 필수, 예산이 줄어든 만큼 폴백 전환이 더 빨리 일어남.

   **설계**: 전체 데드라인 = 시작+3시간(여유 20분, 실질 160분). 각 단계 타임아웃 =
   `min(45분, 남은시간 − 남은단계수×1시간)`으로 동적 계산(동기폴백 예상 1시간/단계는
   실측 기반이라 예산 축소와 무관하게 유지). 예: 1단계 진입 시 160−2×60=40분 →
   `min(45,40)`=40분; 2단계는 120−60=60분 → 45분; 3단계는 75−0=75분 → 45분.
   타임아웃 도달 시 배치 취소(cancel 엔드포인트) 후 동기+병렬 폴백. 3단계 각각
   독립 적용.

   **(2026-08-12 실행 중 갱신) 이번 실행에서는 3단계 통합을 안 함**: 실제 구현해보니
   global_context의 결과가 screen 프롬프트에 그대로 들어가는데, 배치 안 요청들은
   서로 독립적이어야 해서 "context+screen 한 배치"가 성립하지 않음(품질을 낮추거나
   4단계로 늘려야 함 — 계획에 없던 설계 공백). 리스크 대비 이득(최대 ~$3.5 절감)이
   작다고 판단해 이번 실행순서 13은 `resumable_run.py`의 동기+병렬 경로로 진행,
   Batch API 프리미티브(`llm/anthropic.py`)는 테스트까지 구현해두고 이번엔 안 씀 —
   자세한 내용은 `docs/progress.md` 2026-08-12(실행순서 11) 참고.

## 실행 순서

1. 이 계획을 `review-agent/docs/`에 저장(완료, 이 파일).
2. PR #30 포팅: `related_original_text` 필드 + confirm 프롬프트 확장.
3. 발견8 포팅: `_CITATION_DOC_CODE`+`_CITATION_NATURAL` (review-agent + eval-agent).
4. 발견1+4 포팅: `_CATEGORY_BOUNDARY_NOTES` 3구분.
5. 발견2 구현: `_verify_mi_finding`/`_verify_ae_finding` + `_FALSE_POSITIVE_VERIFIERS`.
6. 발견3 구현: 서브스트링 검증+보정.
7. 발견5+6 구현: RD 확장 + MI 프레이밍 확장.
8. 발견7 구현: `_extract_global_context` 용어 목록 확장.
9. `fewshot_bank.py` 재구축: DOC-000+021–040만 소스.
10. 캐싱 최적화 1·2·4번 적용.
11. 실행 인프라(resumable) + Batch API 프리미티브 구현 + $7 상한 가드. (Batch API
    3단계 통합은 설계 공백으로 이번엔 안 함 — 위 "속도/비용 최적화" 절 갱신 참고)
12. 최소 비용 검증(mocked 테스트 + 배치 프리미티브 단위 테스트 + 1문서 실 호출, 결과
    재사용).
13. 전체 실행(`resumable_run.py`의 동기+병렬 경로, 나머지 19문서).
14. eval-agent 재채점(발견8 영향 재확인 포함).
15. 결과 보고서 작성 + PR #33 머지 여부 최종 확인.

## 검증

- 캐싱/중복제거 최적화 전후 issue 목록 동일성 확인.
- MI/AE 재검증 로직 — 백엔드 테스트 패턴 포팅(통과/탈락/에러/malformed).
- 발견3 — 헤더 라벨 인용 mock fixture로 보정 확인.
- 발견4 — 쿠폰 개수 불일치 예시로 GA/LG 분류 확인.
- 발견7 — 용어 목록 추출/전달 확인.
- 발견8 — PR #32 회귀 테스트 2개 + 기존 반례 테스트 통과.
- 발견5 — related_location+related_original_text 채워지는지.
- 발견6 — 4가지 케이스(단어/문장/소주제/대주제) fixture 검증.
- Batch API — custom_id 매칭, 동적 타임아웃, 취소+폴백, 3시간 데드라인 준수.
- resumable 실행 — 완료된 doc_id 스킵 확인.
- 최종 비용을 실제 API usage로 재확인.
