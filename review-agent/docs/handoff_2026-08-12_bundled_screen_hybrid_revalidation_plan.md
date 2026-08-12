# 인수인계 — bundled_screen_hybrid 20문서 재검증 + 정확도 개선 (2026-08-13, 완료 후 최종)

> 이 문서의 이전 버전들은 "계획 승인 완료, 실행 전" 상태를 기록한 것이었다. 이번
> 버전은 **실행순서 1–15가 전부 끝난 뒤의 최종 상태**를 기록한다 — 남은 건 PR #33
> 머지 여부 사용자 승인 하나뿐이다.

## 지금 상태 — 계획 실행 완료

- **실행순서 1–15 전부 완료.** 발견1–8 코드 구현+테스트(300+ 통과)+실제 20문서
  Sonnet5 실행($6.33/$7)+eval-agent 재채점+결과 보고서 작성까지 끝났다.
- 결과 보고서: `review-agent/docs/experiments/results_2026-08-12_bundled_hybrid_
  20doc_revalidation.md` — **핵심 결론: recall이 5문서·골든6건 기준 50%에서
  20문서·골든19건 기준 5%로 대폭 하락.** 관계형 카테고리(GA/LG/TM/TC, "두 지점을
  비교해야 하는 판정") golden 9~10건이 전부 미탐지 — 이번 세션에서 가장 중요한 발견.
- 실행 로그 전체: `review-agent/docs/progress.md`의 2026-08-12 날짜 섹션들(실행순서
  2번부터 15번까지 순서대로 기록됨). 각 발견의 구현 커밋 해시도 거기 다 있음.
- 실 실행 결과물(코드 추적 안 됨, 로컬 파일만): `review-agent/outputs/experiments/
  bundled_hybrid_20doc_revalidation/` — 문서별 review.json/md, predictions.json,
  summary.json/md.

## 실행 중 발견한 예상 밖 이슈 (전부 문서화됨)

1. **Batch API 3단계 통합을 포기함** — global_context 결과가 screen 프롬프트에
   들어가는데, 배치 안 요청은 서로 독립적이어야 해서 설계가 안 맞았음. 프리미티브
   (`llm/anthropic.py`의 submit/poll/cancel/fetch_batch_results)는 테스트까지 구현
   했지만 이번 실행에는 안 씀 — `resumable_run.py`의 동기+병렬 경로로 대체.
2. **cost guard 버그** — screen(Gemini 무료)과 confirm(Sonnet 유료) 토큰을 합쳐서
   단가를 매기던 버그를 실행 중 발견/수정(`b892ba3`). 이후 웨이브 단위 실사용 재확인
   으로 한 번 더 강화(`82a8fdb`).
3. **eval-agent의 기존 스코핑 버그 재확인** — `_scope_to_predicted_docs`가 "0건
   지적"과 "미검토"를 구분 못 함. 20문서 중 14문서가 0건이라 자동 스코핑하면 recall이
   인위적으로 부풀려짐(17% vs 정확히 계산한 5%). eval-agent 소스 문제라 이번에도
   수정 안 하고 몽키패치로 우회해서 정확한 수치만 냄.

## 계획 실행 완료 이후 — 사용자의 후속 요청(결과 해석/발표 자료 준비)

계획 자체는 끝났지만, 이후 대화에서 사용자가 이 결과를 **팀 발표/베타테스트 슬라이드
자료로 정리**하는 걸 도와달라고 해서 아래를 진행함(전부 review-agent 코드 변경 없음,
분석·설명·아티팩트 제작만):

- **아티팩트 3개 게시**(전부 이 대화 세션에서 게시, URL은 `Artifact` 도구의
  `action: "list"`로 재조회 가능):
  1. "20문서 재검증 결과" — 요약 보고서(recall 50%→5% 강조)
  2. "문서별 검토 대조표" — DOC-001~020 전체를 찾은 것/golden/소요시간/토큰/비용별로
     대조 (문서당 평균 비용 $0.317, 전체 $6.33)
  3. "피드백별 해석과 통찰" — 해결(3)/부분적해결(1)/미해결(2)로 재분류, "두 지점을
     비교해야 하는 판정"이 전멸했다는 걸 하나의 큰 줄기로 통합해서 정리
- **실 Sonnet5 API 호출 여부를 사용자가 재확인 요청** → `client.messages.with_raw_
  response`로 실시간 호출 1회 실행, `message.id`/`request-id`/`anthropic-
  organization-id`(`4a24715b-dd96-4cac-8682-50e008cafe07`) 등을 근거로 실제 호출임을
  증명. 사용자가 콘솔에 사용량이 안 보인다던 문제는 **콘솔에서 다른 조직(workspace)을
  보고 있을 가능성**으로 결론(이 API 키가 속한 조직 ID를 대사하도록 안내함).
- **eval-agent 채점 방식 설명 + 사람 vs AI 비교 방법론 컨설팅** — 사용자가 별도로
  진행 중인 "정답지(전량형, 이 문서의 모든 문제를 담음) 대비 인간 리뷰어 vs AI 에이전트"
  비교 작업(베타테스트 슬라이드용)을 위해 recall/precision 공식, 오탐(FP 개수)/
  과탐률(1−precision) 계산법을 설명함. **이건 review-agent 저장소 밖의 별도 문서
  (`카카오톡 받은 파일/사진후기페이지_PRD_Test Doc...md`)에 대한 새 비교 작업으로,
  이번 20문서 재검증과는 별개 — 후속 세션에서 이 주제가 이어지면 이 컨텍스트를
  참고할 것.**

## 남은 것 — 딱 하나

**PR #33(`feature/review-agent`를 `expr/review-agent/`로 이전, 팀원 kayo2e 제안)
머지 여부 — 사용자 최종 승인 대기 중.** 계획대로 이번 세션에서 사용자 승인 없이는
머지하지 않았음. 다음에 이 대화가 이어지면 이것부터 물어볼 것.

## 그 외 참고

- `feature/review-agent`는 여전히 로컬 전용 — 이번 세션의 모든 커밋(발견1–8, 캐싱,
  실행 인프라, 문서화)이 push 안 된 상태로 남아 있음. push/PR은 여전히 명시적 요청
  시에만.
- `eval-agent-latest` 워크트리(`C:/Users/HYESEO/Desktop/eval-agent-latest`)의 발견8
  포팅(정규식 수정)은 detached HEAD라 **여전히 커밋 안 하고 워킹트리에만 남겨둠**
  (의도된 선택, 이유는 progress.md 2026-08-12 실행순서 3 항목 참고).
