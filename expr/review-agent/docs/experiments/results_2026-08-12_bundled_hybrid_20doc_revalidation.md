# bundled_screen_hybrid 20문서 재검증 + 정확도 개선(발견1–8) — 결과 (2026-08-12)

> 계획 문서: `docs/plan_2026-08-12_bundled_screen_hybrid_revalidation.md`. 이 실험의
> 목적은 두 가지였다 — (a) 실사용자 피드백 13개에서 뽑은 8개 정확도 개선(발견1–8)을
> `bundled_screen_hybrid`(실제 데모2/프로덕션 구조)에 직접 구현, (b) 기존 5문서/골든
> 6건 파일럿의 결론(특히 recall 50%)이 20문서/골든 19건으로 넓혀도 유지되는지 확인.
> **결론을 먼저 말하면: (a)는 성공(구현·테스트·실행 전부 완료), (b)는 실패 —
> recall은 표본을 넓히자 50%에서 5%로 떨어졌다.** 아래에 근거를 정리한다.

## 요약

| 항목 | 값 |
| --- | --- |
| 구현한 발견 | 1–8 전부 (커밋 8건, `git log`에서 "발견"/finding 관련 커밋 참고) |
| 테스트 | review-agent 300+개 전부 통과 (mocked, API 비용 없음) |
| 실 API 실행 | DOC-001–020 전체 20문서, Sonnet5(confirm)+Gemini flash-lite(screen) |
| 실제 비용 | **$6.33** (상한 $7 안, 여유 $0.67) |
| 실행 중 에러 | 0건 |
| eval-agent 재채점(relaxed, rule_id만) | **recall 5%(1/19), precision 50%(1/2)** |
| eval-agent 재채점(strict, rule_id+Level) | recall 0%, precision 0% |
| valid_but_unlabeled(골든에 없지만 그럴듯한 지적) | 9건 |
| **기존 5문서 파일럿(2026-08-11) 대비** | **recall 50%(3/6) → 5%(1/19), 대폭 하락** |

## 실행 방식

- `resumable_run.py`(이번에 신규 구현)로 doc_id별 resumable + $7 사전추정 가드 +
  웨이브 단위 실사용 재확인. Batch API는 구현은 했으나(테스트 포함) 실행 중 발견한
  설계 공백(global_context 결과가 screen 프롬프트에 들어가서 "같은 배치 안 독립 요청"
  조건이 안 맞음) 때문에 이번 실행엔 안 씀 — 대신 `ThreadPoolExecutor` 동기+병렬 경로.
  자세한 내용은 `docs/progress.md` 2026-08-12(실행순서 11) 참고.
- 결과: `outputs/experiments/bundled_hybrid_20doc_revalidation/`(문서별 review.json/md +
  summary.json/md + predictions.json). `outputs/`는 gitignore돼 있어 로컬에만 있음.

## 발견1–8 구현 현황 (전부 완료)

| 발견 | 내용 | 실 실행에서 관찰됐나 |
| --- | --- | --- |
| 1+4 | `_CATEGORY_BOUNDARY_NOTES`(GA↔TC, TC↔MI, LF↔GA/LG) | 프롬프트에 포함 확인(테스트) — 실 실행에서 GA/LG/LF 위반이 하나도 confirm 안 돼서 실전 효과는 이번엔 관찰 못 함(아래 "핵심 발견" 참고) |
| 2 | MI/AE 오탐 재검증(`_verify_mi_finding`/`_verify_ae_finding`) | 로직 정상 작동(테스트) — 이번 실행에서 최종 11건 중 재검증에 걸려 제외된 사례는 로그상 확인 안 함(전부 살아남음, 즉 이번 20문서에선 그런 오탐 자체가 없었거나 재검증을 통과함) |
| 3 | 인용 서브스트링 보정(`_resolve_quoted_span`) | 코드 정상 작동(테스트) — 실 실행에서 헤더 라벨 인용 사례가 있었는지는 개별 확인 안 함 |
| 5 | RD 두 번째 위치(`related_location`/`related_original_text`) | **이번 실행에서 GA/LG/LF/RD 확정 위반이 0건이라 실전 검증 못 함** — predictions.json의 11건 전부 `related_location`이 비어 있음 |
| 6 | MI 프레이밍 확장(문장→소주제, 소주제→인접 등) | **부분적으로 확인됨**: MI 이슈 8건 중 7건은 확실히 넓혀진 걸로 보이는 길이(346~629자, 문장 하나로는 너무 길다)이지만, DOC-011의 MI-07 1건은 19자로 넓혀지지 않았다 — `issue.location`이 실제 `document.py` 청크 위치와 정확히 안 맞아서 `_widen_mi_finding`이 조용히 원본을 그대로 반환한 것으로 추정(예외 없이 no-op하는 설계라 에러로도 안 잡힘). 실제 서비스에 반영하기 전에 위치 매칭 실패율을 더 큰 표본으로 확인 필요. |
| 7 | TC 용어 목록 (`_extract_global_context`의 `terms`) | 이번 실행에서 TC 위반이 1건(DOC-006 AE-03 근처가 아니라 실제로는 0건 confirm, golden만 1건) — TC confirm 자체가 거의 안 열려서 실전 효과 확인 못 함 |
| 8 | 참조-예외 프로즈 인용 정규식 | review-agent+eval-agent 둘 다 적용, 테스트 통과. 이번 predictions.json에 예외조건(exception) 적용 사례가 있었는지는 review.json에 excused 이슈가 안 남으므로 직접 확인 불가(설계상 제외된 건 로그에 안 남음) |

**발견 5·6은 "지금 당장 즉시 반영"이라고 이전에 판단했지만, MI 자체가 confirm될 때만
효과가 나는 구조**라 이번 20문서 실행에선 MI가 8건 confirm됐으니 발견6은 대체로
작동을 확인했다(7/8). 발견5(RD)는 RD/GA/LG/LF 위반이 이번 실행에서 전혀 confirm되지
않아 실전 검증 기회 자체가 없었다 — mocked 테스트로만 확인된 상태.

## 핵심 발견: recall이 표본을 넓히자 크게 떨어졌다

2026-08-11 문서(`results_2026-08-11_deterministic_rescore.md`)는 5문서·골든 6건
기준으로 `bundled_screen_hybrid`가 **relaxed recall 50%(3/6), precision 100%,
unmatched 0건**으로 "이 매트릭스의 최종 승자"라고 결론 냈다. 이번에 golden 19건(20문서)
으로 넓혀서 같은 방식(eval-agent 결정론적 매칭)으로 다시 재본 결과:

- **relaxed recall: 5%(1/19)**, precision 50%(1/2)
- strict(rule_id+Level 둘 다 일치): recall/precision 둘 다 0%
- **관계형 카테고리(GA/LG/TM/TC, Document 또는 Logical Unit 위계)가 전부 미탐지** —
  golden 19건 중 9건(GA×5, LG×1, TM×2, TC×1)이 이 관계형 카테고리인데, **단 하나도
  못 잡았다.** 이전엔 골든이 6건뿐이라 이 정도로 폭넓게 드러나지 않았을 뿐, 실제로는
  이 구조의 document-tier 관계형 판정이 훨씬 더 약하다는 뜻으로 보인다.
- MI(정보 누락) 쪽도 golden 4건 중 0건 매칭(단, 이건 "완전히 못 찾음"이 아니라
  "다른 위치를 찾음"에 가깝다 — 아래 개별 사례 참고).

**왜 떨어졌는가**: 이번 세션에서 구현한 발견1–8은 전부 좁게 스코프된, 주로 오탐
억제(발견2/3/8)나 표현 개선(발견5/6/7)이라 recall을 낮출 이유가 없다 — 실제로 표를
보면 recall 저하가 이번 변경과 무관하게 **관계형 카테고리 전반에 걸쳐 있다**(발견1/4가
직접 다루는 GA↔TC/TC↔MI/LF↔GA,LG 경계 문제가 아니라, 애초에 관계형 위반 자체를
못 찾는 문제). 가장 그럴듯한 설명은 **골든 6건짜리 표본이 너무 작아서 50%라는 수치가
통계적으로 불안정했다** — 표본을 넓히니 그 운이 다한 것으로 보인다. 이번 세션 스코프
안에서 "LG/GA 재현율 문제는 알려진 한계로 남긴다"고 미리 정해뒀는데(발견7 문서 참고),
그 한계의 **실제 크기가 이전에 생각했던 것보다 훨씬 크다**는 게 이번 재검증의 진짜
결론이다.

## 개별 사례로 본 세부 관찰

- **DOC-003, DOC-006 — 카테고리 경계 혼동 (새로 발견, 이번 스코프 밖)**: golden은
  AE-03을 기대했는데 AE-01로 잘못 분류(judge_avg=5.0, rubric 품질 자체는 낮지 않음 —
  순수 카테고리 오분류). 발견1/4가 다룬 GA↔TC/TC↔MI/LF↔GA,LG 세 조합엔 AE-01↔AE-03이
  없어서 이번엔 안 고쳤다. 재발하면 발견1/4의 `_CATEGORY_BOUNDARY_NOTES`에 네 번째
  구분으로 추가할 후보.
- **DOC-006 — golden이 기대한 위계보다 더 좁게 보고**: golden은 AE-01을 Logical Unit
  (2-1~2-4 전반)으로 기대했는데 실제로는 Paragraph(2-1만)로 더 좁게 잡았다(rule_id는
  맞음 — relaxed recall의 유일한 TP 1건이 이거다). AE-03도 마찬가지로 더 좁게(Paragraph,
  2-3만) 잡았는데 이건 golden의 "전반" 범위와 안 겹쳐서 FN으로 잡혔다 — 그런데 바로
  이 위치가 `valid_but_unlabeled`로도 한 번 더 나온다(같은 문서, 다른 매칭 로직에서
  "골든엔 없지만 유효해 보임"으로 재분류). 즉 review-agent는 AE-03을 정확한 세부
  위치에서 찾긴 했는데, golden이 그보다 넓은 범위로 라벨링돼 있어서 점수화 방식에 따라
  결과가 왔다 갔다 한다 — 이건 review-agent 문제가 아니라 golden의 위계 라벨링과
  scoring 로직 사이의 근본적인 어긋남이다.
- **valid_but_unlabeled 9건**: DOC-006/008/011/013/016에서 나온 MI-02/03/05/07 계열
  지적들이 golden에는 없지만 "유효해 보인다"고 eval-agent가 별도 분류했다 — golden
  19건이 실제 위반 전체를 다 담고 있지 않다는 뜻(애초에 golden은 "결정론적으로 채점
  가능한 대표 사례"만 추린 것이라 예상된 결과). precision 계산에서 이 9건은 분모에서
  빠지므로, "review-agent가 지어낸 오답"으로 세지는 건 아니다.
- **eval-agent의 문서 스코핑 버그(재확인, 이전에도 알려짐)**: `_scope_to_predicted_docs`
  가 predictions.json에 등장하는 doc_id만 골든 스코프에 포함시키는데, **0건 지적한
  문서는 predictions.json에 그 doc_id가 전혀 안 남아서 "미검토"로 오인**된다 — 이번에
  20문서 중 14문서가 0건 지적이라 자동 스코핑으로 돌리면 그 14문서의 골든(DOC-001의
  LG-05 포함)이 통째로 빠져서 recall이 인위적으로 17%(6문서 스코프)로 부풀려진다.
  **이 보고서의 5% 수치는 이 버그를 우회(스코핑 함수를 몽키패치해서 20문서 전체로
  강제)해서 낸 정확한 값**이다 — `results_2026-08-11_deterministic_rescore.md`도 이미
  이 문제를 "이번 세션 범위 밖"으로 남겨뒀던 것(review-agent 소스가 아니라 eval-agent
  소스 문제라 이번에도 안 고침, 팀에 공유할 가치 있는 별도 이슈).

## 비용

- 실측: 20문서 confirm(+global_context) 토큰 합계 기준 **$6.33**(상한 $7 안).
- 문서당 평균 $0.317 — 계획 초기 추정($0.3–0.4/문서)과 일치.
- Batch API(50% 할인) 미사용 — 썼다면 이론상 confirm 쪽 비용이 절반 가까이 줄었겠지만,
  이번 세션에서 발견한 설계 공백(위 "실행 방식" 참고) 때문에 안전하게 구현하기엔
  시간이 부족하다고 판단해 보류.

## 알려진 한계 (이번 스코프에서 손 안 댐, 재확인됨)

- **관계형 카테고리(GA/LG/LF/TM/TC) document-tier 재현율 — 예상보다 훨씬 심각**.
  단일 패스 추론 깊이 한계로 추정했으나 정량적으로 "9건 중 0건"이라는 건 이전에 몰랐던
  정도의 심각성. 다음 세션에서 우선순위로 다룰 가치 있음(예: 후보 재검토 2차 패스,
  또는 판정 전 강제로 "충돌 후보 쌍"을 나열하게 하는 프롬프트 재설계).
- **AE-01↔AE-03 카테고리 경계 혼동** — 새로 관찰됨, `_CATEGORY_BOUNDARY_NOTES`에 추가
  후보.
- **golden 위계(Level) 라벨링과 review-agent 보고 위계 간 근본적 불일치** — DOC-006
  사례처럼 review-agent가 더 좁게(정확하게?) 잡아도 golden의 넓은 라벨과 안 맞아서
  strict/relaxed 점수가 왔다 갔다 함. review-agent 버그가 아니라 golden 라벨링 방식과
  scoring 로직의 구조적 문제.
- **eval-agent의 "0건 지적 = 미검토" 오인 버그** — review-agent 소스가 아니라 eval-agent
  소스 문제, 팀 공유 필요(이슈로 등록 권장).
- **발견5(RD)는 이번 실행에서 검증 기회가 없었음** — RD/GA/LG/LF가 전혀 confirm되지
  않아서(위 recall 문제와 동일 원인) 실전에서 related_location이 채워지는 걸 못 봄.
- **발견6(MI 프레이밍)의 위치 매칭 실패 사례 1건** — `_widen_mi_finding`이 위치 문자열
  불일치 시 조용히 원본을 그대로 반환 — 실패를 로그로 남기지 않아서 이번에 우연히
  발견함. 더 큰 표본으로 실패율 확인 필요.

## 다음 단계 제안

1. 관계형 카테고리 recall 문제를 이번 세션 스코프 밖으로 남기지 말고 다음 우선순위로
   격상 — 9건 중 0건은 "알려진 한계"라고만 적어두기엔 너무 크다.
2. eval-agent의 문서 스코핑 버그를 팀(kayo2e 등)에 이슈로 공유.
3. `_widen_mi_finding`이 위치 매칭에 실패하면 조용히 넘어가지 말고 `tier_errors`에
   기록하도록 보강(관찰 가능성 개선).
4. AE-01↔AE-03 경계 혼동을 재현 가능한 사례가 더 쌓이면 `_CATEGORY_BOUNDARY_NOTES`에
   추가.

## PR #33 (`expr/review-agent/`로 이전) 처리

계획대로 **사용자 최종 승인 필요** — 이 보고서 작성 시점까지 머지하지 않았다.
