# 인수인계 — bundled_screen_hybrid 20문서 재검증 + 정확도 개선 (2026-08-12, 최종)

> 이전 버전(같은 파일명, compact 직전 작성)은 미해결 질문이 있는 중간 상태였다. 그
> 이후 대화에서 실사용자 피드백 13개, 팀 GitHub 최신 PR(#30/#32/#33), 팀 프레이밍
> 규칙 Notion 문서 2건을 추가로 반영해서 계획이 크게 확장·확정됐고, 사용자가
> **ExitPlanMode로 최종 승인**했다. 이 문서는 그 최종 상태를 기록한다.

## 지금 상태

- **계획 승인 완료, 코드 실행은 아직 시작 안 함.** 지금까지 이 세션에서 실행한 실제
  코드/커밋은 없음 — 전부 조사·설계·plan 파일 갱신이었다.
- 승인된 계획 전문: `C:\Users\HYESEO\.claude\plans\replicated-jingling-pudding.md`
  (git 추적 아님) 및 그 사본 `review-agent/docs/plan_2026-08-12_bundled_screen_
  hybrid_revalidation.md`(이번에 새로 커밋, git 추적됨 — **이게 실행용 원본으로
  더 안전**, plan 파일이 나중에 다른 작업으로 재사용될 수 있음).
- 사용자가 실행 도중 자리를 비울 예정이라 **자율 실행 경계**가 계획에 명시돼 있음
  (아래 요약). 이 경계 안에서는 허락 없이 계속 진행한다.

## 자율 실행 경계 (요약, 원문은 계획 문서 최상단)

**승인 없이 진행**: 실행순서 2–11(코드 작업 전부, 로컬 커밋), 12(최소 비용 검증),
13(전체 20문서 Batch API 실행, 약 $7), 14(eval-agent 재채점), 15(보고서 작성 —
형식 관련 소소한 결정은 직접 선택 후 이유 기록).

**승인 없이는 안 함**: git push / PR 생성·머지(PR #33 포함, 마지막에 확인), `main`/
`dev` 브랜치 손대기, 이번에 다루지 않기로 한 항목(LG/GA 재현율 등) 임의 추가.

**비용 상한 — 절대 규칙**: $7, 여유 없음. 매 단계(스모크 테스트/screen 배치/confirm
배치/MI·AE재검증 배치) **제출 전에** "지금까지 실사용 비용 + 이번 단계 예상 비용"을
계산해서 합이 $7을 넘을 것 같으면 그 단계를 제출하지 않고 멈춘다. 배치는 제출 후엔
처리된 만큼 과금되므로 사후 감시가 아니라 사전 추정으로 막아야 한다 — 이 가드를
실행순서 11(실행 인프라 구현) 때 코드로 반드시 넣을 것.

**시간 상한**: Batch API 3단계(screen→confirm→MI·AE재검증) 전체를 합쳐 5시간
(실질 4.5시간 + 30분 여유). 각 단계 진입 전에 `min(90분, 남은시간 − 남은단계수×1시간)`
으로 그 단계의 배치 타임아웃을 동적으로 계산 — 도달하면 배치를 cancel API로
명시적으로 취소하고 동기+병렬(`ThreadPoolExecutor`) 폴백으로 전환한다.

**계획에 없는 진짜 블로커**: 멈추지 말고 가장 보수적인 선택 후 근거를 커밋 메시지/
`progress.md`에 남기고 계속.

## 실행 순서 다음 액션 (지금부터 시작할 지점)

1. ~~계획을 저장~~ — 완료(`review-agent/docs/plan_2026-08-12_bundled_screen_
   hybrid_revalidation.md`, 이번 커밋).
2. **다음: PR #30 포팅** — `packages/planqa-schemas`의 `Issue`에
   `related_original_text: str | None`(LG/LF/GA만) 추가, `bundled_screen_hybrid.py`
   confirm 프롬프트가 관련 위치 원문 인용도 요청하도록 수정, `diff_report.py` 출력에
   노출. PR #30 원문: https://github.com/sunic5-planqa/planqa-agent/pull/30
3. 발견8 포팅 — `verifier.py`의 `_CITATION`을 `_CITATION_DOC_CODE`+`_CITATION_NATURAL`
   로 분리(PR #32 diff 그대로 재현 가능, 정규식:
   ``「[^」]{2,40}」\s*\d+(?:-\d+)?[^.\n]{0,40}?(?:따른다|따릅니다|해당하는 경우|참조 표기|참고|참조)``).
   review-agent(`review-agent/src/planqa_review/verifier.py`)와 eval-agent
   (`feature/eval-agent` 브랜치/워크트리의 `tools/eval-agent/src/planqa_eval/
   verifier.py`) 둘 다. PR #32: https://github.com/sunic5-planqa/planqa-agent/pull/32
4. 이후 계획 문서의 "실행 순서" 4–15번 그대로.

## 이번 세션에서 새로 확정된 핵심 사실 (재조사 불필요)

- **eval-agent 워크트리 위치**: `C:/Users/HYESEO/Desktop/eval-agent-latest`
  (detached HEAD) — `feature/eval-agent` 관련 작업은 여기서.
- **저장소 자체가 `sunic5-planqa/planqa-agent`의 로컬 클론**(`origin` remote 확인됨,
  놀랍지만 사실 — `git fetch origin`으로 팀 PR을 바로 조회 가능).
- **팀 프레이밍 규칙(Notion, 8월 6일자)**: 사용자가 md 파일 2개를 직접 공유함
  (`Ver 1 - QA별 프레임 유형 구분`, `Ver 2 - Edit 행위별 프레임 유형 구분`).
  LG/LF/GA 프레임 타입은 **Ver1(항상 범위)로 확정**, MI "문장 하나 누락" 프레이밍은
  **Ver2(해당 소주제 전체)로 확정** — 사용자가 직접 선택. 원본 파일 경로:
  `C:\Users\HYESEO\Desktop\혜서\suni\frozen_files\`.
- **프론트엔드 실제 상태 확인됨**(`sunic5-planqa/planqa` repo, `extension/src/`):
  백엔드 `qa_jobs.py`의 `_frame_type()`은 이미 Notion 규칙대로 구현돼 있지만,
  `issueOverlay.ts`는 아직 object(단일 박스) 방식으로만 그림 — range/insert_range를
  실제로 다르게 그리는 로직은 없음. **발견6(MI)은 이 사실 때문에 review-agent만
  고쳐도 지금 바로 시각적 효과가 나지만, 발견5(RD)는 프론트 갱신이 따로 필요** —
  결과 보고서에 반드시 이 구분을 명시할 것.
- **하이쿠(Haiku) 관련**: 우리 review-agent/eval-agent 어디에도 실사용 없음(테스트
  코드 예시뿐). 실사용은 백엔드(`sunic5-planqa/planqa`)의 `qa_jobs.py`(QA 엔진
  스크리닝, `settings.sunnic_haiku_model`)와 `issues.py`(이슈 저장 시 유사도 체크)
  두 곳 — 이건 우리 코드가 아니라 팀 백엔드 얘기라 이번 계획 범위 밖, 사용자가
  팀원한테 별도로 문의할 사항으로 남겨둠.
- **Batch API 실제 소요시간 조사**: 공식 SLA 24시간은 상한선, 실제로는 5,000건
  이하 배치는 1–2시간 내가 흔함, 다만 진행률 표시가 없어 4시간+ 걸린 프로덕션
  사례도 보고됨([Enterprise DNA](https://enterprisedna.co/resources/guides/guide-anthropic-batch-api/)).
  우리 배치는 20문서 규모라 낙관적이지만 이 불확실성 때문에 동적 타임아웃+취소+
  폴백을 필수로 설계함.

## 남은 미해결 사항

- 이전 버전 문서에 있던 "Batch API 할지 말지" 질문은 **완전히 해결됨** — 사용자가
  "코드 변경은 네가 하는 거니 트레이드오프 논리가 안 맞음, 가능하면 하라"고 확정,
  Batch API 포함이 최종 결정.
- 남은 건 순수 실행뿐 — 위 "실행 순서 다음 액션"부터 시작하면 됨.
