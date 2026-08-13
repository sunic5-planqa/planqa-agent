# 인수인계 — 데모 v1 배포 완료, 구조/모델 실험 계획으로 복귀 예정 (2026-08-10 세션 종료 시점)

> `docs/progress.md`가 너무 요약적이라 만든 상세 인수인계 문서. 이전 handoff
> (`docs/handoff_2026-08-09_model-pilot-and-demo.md`)를 이어받은 세션이 다룬 범위가 여기까지다.
> **이 문서는 일회성 스냅샷이라 다시 업데이트하지 않는다** — 이후 진행 상황은
> `docs/progress.md`에 이어서 기록할 것.

## 지금 정확히 어디에 있는가

- 브랜치: `feature/review-agent`, **워킹 트리 깨끗함, origin까지 전부 push 완료**
  (`ab71b72`). 전체 테스트 127개 통과.
- **데모 v1이 실제로 만들어져서 `planqa-agent`의 `dev` 브랜치에 merge됐다** (PR #8).
  이전 handoff의 "다음 세션이 즉시 해야 할 일"(데모 스코프 확정)은 이번 세션에서 전부
  해결됨.
- 사용자의 마지막 지시: **"compact하고 실험 계획 다시 얘기하자"** — 즉 데모는 일단락됐고,
  다음 세션은 구조/모델 ablation 실험(이전 handoff의 ①②③+④ 계획, `docs/experiments/
  structure_plan_2026-08-10.md`)으로 복귀해야 함.

## 이번 세션에서 일어난 일 — 순서대로

### 1. 데모 구조/모델 확정

사용자가 직접 순서대로 결정:
1. **판정 단계 수**: 2단계형(baseline=제안5와 동일 구조) — Gemini flash-lite 스크리닝 →
   Claude Sonnet 5 정밀판정
2. **청킹**: 위계형(기존 유지)
3+4. **세분화×퓨샷**: 처음엔 "콜통합 + 룰텍스트&정적 퓨샷"을 제안했으나, 실제 baseline
   스크리닝이 이미 룰 전문을 준다는 걸 확인한 뒤 재논의 → **최종: 스크리닝은 카테고리
   라벨만(룰 텍스트 없음), 정밀판정에 룰 전문. 퓨샷은 이번엔 안 넣음(보류).**

이 조합은 기존 baseline(`models/gemini_lite/*`)에 없는 새 동작이라 additive-only
원칙대로 **새 구조 `structures/category_screen.py`**로 구현함(스크리닝이 카테고리만
반환 → 정밀판정이 그 카테고리 안의 룰 전체를 놓고 구체적 rule_id를 직접 고름).

### 2. `llm/anthropic.py` 신규 — Claude 직접 클라이언트, 실제 버그 2개 발견/수정

게이트웨이가 아니라 팀 자체 Anthropic 크레딧으로 직접 호출. 실제 문서(DOC-006)로 스모크
테스트하다 라이브로 두 버그를 잡음:
1. `claude-sonnet-5`가 `temperature` 파라미터 자체를 400으로 거부함("deprecated for
   this model") — 모델별로 온오프하는 `_NO_TEMPERATURE_MODELS` 세트로 해결.
2. extended thinking이 이 모델은 기본 켜져 있어서, 한 번은 응답이 `ThinkingBlock`만
   오고 텍스트가 아예 없는 경우 발생 — `thinking: {"type": "disabled"}` 명시 + 응답의
   첫 텍스트 블록을 스캔하도록 수정(`content[0]`을 무조건 신뢰하면 안 됨).
   결과: DOC-006 기준 213.9초 → 71.3초.
- 사용자 지시로 새 메모리 저장: **"1분 넘는 실행/테스트는 원인 찾아서 보고할 것"**
  (`feedback_report_slow_runs.md`) — 71.3초 실행에서 92%가 Claude confirm 단계(5콜,
  콜당 ~13초, 순차 실행) 때문이었다고 stats 기반으로 실제 보고한 사례가 계기.

### 3. GitHub issue #4 대응 — `related_location` 필드

팀원(kayo2e)이 프론트(Confluence 익스텐션)에서 LG/LF/GA(관계형 룰)는 두 지점을 잇는
"범위 프레임"을 그려야 하는데 `Issue`엔 위치가 하나뿐이라 요청한 필드. `schema.py`에
`related_location: str | None = None` 추가(LG/LF/GA만 채워짐, 나머지는 항상 None),
`category_screen.py`의 정밀판정 프롬프트/파싱에 반영, `diff_report.py` JSON/마크다운
출력에도 반영. **baseline(`models/gemini_lite/confirmer.py`)엔 반영 안 함** —
additive-only 원칙 유지, 사용자도 "지금은 데모 구조에만"으로 확인.

### 4. CLI에 `--structure`, `--screen-backend`/`--confirm-backend` 추가

기존엔 screen/confirm이 같은 백엔드만 쓸 수 있었음(모델만 다르게 가능) — Gemini
스크리닝 + Claude 정밀판정처럼 **백엔드 자체가 다른 조합**을 CLI로 스모크 테스트하려면
필요해서 추가.

### 5. `sunic5-planqa/planqa-agent`가 모노레포로 재구성된 걸 처음 발견

지금까지 review-agent는 독립 레포처럼 다뤄왔는데, `dev` 브랜치를 확인해보니 이미
`services/`(배포 대상: review-agent, 신규 eval-service)/`tools/`(CI 전용:
eval-agent)/`packages/`(공유: `planqa-schemas` — `schema.py`/`rulebook.py`가 여기로
이동)로 재구성돼 있었음(`docs/adr/0001-monorepo-workspace-and-async-eval-service.md`
참고). **`services/review-agent`의 `schema.py`/`rulebook.py`는 없고 `planqa_schemas`
패키지에서 import함** — 다음 세션이 dev 쪽 파일을 볼 때 이 import 경로 차이를 헷갈리지
말 것.

또한 review-agent는 **이미 `sunic5-planqa/planqa`(실제 제품 백엔드) 안에 vendoring(복사)
되어 실제로 쓰이고 있었음** — `backend/src/sunnic_backend/qa_engine/review_agent/`,
그 레포 자체 ADR(`docs/adr/0001-vendor-review-agent-qa-engine.md`) 참고. **이번에
만든 `category_screen`/`anthropic.py`는 이 vendored 사본엔 아직 반영 안 됨** — 별도
수동 재동기화 작업이고, 사용자가 "dev merge부터 먼저, 백엔드는 나중에"로 결정함.

### 6. `tiers.py` 구버전 룰 매핑 버그 발견 → 이슈 등록

dev(`services/review-agent`)와 백엔드 vendored 사본 둘 다, 2026-08-05 룰북 개편
**이전** `TIER_CATEGORIES`를 쓰고 있었음(다수 카테고리가 위계에서 누락, Absence Check
예외도 없음). 사용자 판단으로 **직접 고치지 않고 GitHub 이슈로 등록**
(`planqa-agent#6`, 백엔드 쪽 이슈 별도) — 팀원이 PR #9로 바로 재동기화함.

이 과정에서 **로컬 `feature/review-agent`가 origin보다 10커밋 밀려있었던 것도 발견**
(`ABSENCE_CHECK_RULE_IDS` 수정 포함 — 그동안 로컬 커밋만 하고 push 안 함). 그래서
팀원이 이슈 #6에서 "그 수정이 안 보인다"고 판단했던 것 — origin만 grep했으니 당연함.
사용자 승인 받고 10커밋 전부 push, 이슈에 정정 코멘트 남김.

### 7. PR #8 제출 → merge → 팀원 리뷰 버그수정을 다시 역포팅

`sync/review-agent-demo` 브랜치(별도 git worktree)에서 서비스에 필요한 것만 추려
dev로 PR 제출(gh CLI 없어서 GitHub REST API + 캐시된 git credential로 직접 생성).
팀원이 merge 후 실제 리뷰 버그를 3개 고침:
- `dedupe.py`: 서로 다른 `related_location`을 가진 두 개의 진짜 다른 관계형 이슈를
  하나로 잘못 합치던 버그
- `llm/anthropic.py`: `APIConnectionError`(타임아웃 등) 재시도 처리가 아예 없었음
- `category_screen.py`: 내가 `models/gemini_lite/context.py`(baseline)를 import해서
  스스로 세운 additive-only 원칙을 어긴 걸 팀원이 잡아냄 — global context 로직을
  자체 복제하도록 수정, 참조-예외 체크도 `verifier.py`의 공유 함수로 정리

이 수정들을 그대로 `feature/review-agent`에도 역포팅해서 커밋/push함(테스트 127개
통과 확인). **PR #8 자체는 별도 워크트리에서 만든 거라 원래 작업 브랜치엔 자동 반영
안 됐다는 점 주의** — 이번처럼 dev 쪽에서 뭔가 바뀌면 수동으로 다시 가져와야 함.

## 다음 세션이 즉시 해야 할 일

**사용자 지시대로 구조/모델 ablation 실험 계획 논의 재개.** 참고할 것:

- `docs/experiments/structure_plan_2026-08-10.md` — ①②③+④ 매트릭스(전 handoff에서
  확정됨: 판정단계수 → 청킹 → 세분화×퓨샷 2×3, `콜분리×룰전부`=이미 만든 `cell3.py`).
  **이 계획은 이번 세션에서 안 바뀜** — 그대로 유효.
- **새로 생긴 변수**: 이번 세션에서 실험 매트릭스에 없던 조합(`콜통합 + 카테고리만
  스크리닝`)을 데모용으로 즉흥 결정해서 이미 `category_screen.py`로 구현/배포했다.
  이게 ①②③④ 매트릭스와 어떤 관계인지 사용자와 먼저 정리할 필요 있음 — 매트릭스에
  포함시킬지, 별도 "데모 트랙"으로 남겨둘지.
- 모델 파일럿(Claude/GPT/Solar 미완료 부분)은 **크레딧 문제가 이제 해결됨** — Claude는
  게이트웨이가 아니라 직접 Anthropic API로 이미 붙어서 동작 확인됨(`llm/anthropic.py`).
  게이트웨이 크레딧은 여전히 0 상태(충전 여부 미확인) — GPT/Solar/EXAONE은 게이트웨이
  없이는 여전히 막혀있음.
- eval-agent 워크트리(`C:\Users\HYESEO\Desktop\eval-agent-check\eval-agent`)는 여전히
  `.env` 미설정 상태로 추정(이전 handoff 이후 확인 안 함) — 실제로 채점 돌리려면 먼저
  설정 필요.

**체크리스트**:
- [ ] `docs/experiments/structure_plan_2026-08-10.md` 다시 읽고 매트릭스 상기
- [ ] `category_screen.py`(데모용)를 실험 매트릭스에 어떻게 편입/구분할지 사용자와 확인
- [ ] 게이트웨이 크레딧 충전 여부 확인 후 GPT/Solar 파일럿 재개 여부 결정
- [ ] eval-agent `.env` 설정 여부 확인
- [ ] AskUserQuestion 등 툴 파라미터에 한글 쓸 때 `\uXXXX` 이스케이프 절대 직접 타이핑
      하지 말 것(반복 실수, 메모리 저장돼있음)
- [ ] dev/백엔드 재동기화(오늘 만든 데모 구조를 백엔드 vendored 사본에도 반영할지)는
      아직 미결정 — 필요해지면 사용자와 별도 논의

## 이번 세션에서 새로 저장된 메모리

`C:\Users\HYESEO\.claude\projects\c--Users-HYESEO-Desktop-planqa-eval-agent\memory\`:
- `feedback_report_slow_runs.md` — 1분 넘는 실행/테스트는 stats 기반으로 원인 찾아
  보고할 것

## 참고 — 오늘 만들어진 GitHub 이슈/PR

- `planqa-agent#4` — `related_location` 요청, 이번 세션에서 해결(코멘트로 링크 남김)
- `planqa-agent#6`, 백엔드 쪽 별도 이슈 — `tiers.py` 구버전 매핑 버그, PR #9로 해결됨
- `planqa-agent#8` — 데모 v1 PR, merge 완료
