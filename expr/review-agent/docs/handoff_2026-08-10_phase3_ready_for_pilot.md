# 인수인계 — Phase 3 코드 커밋 완료, 파일럿 실행 직전 (2026-08-10 최신 스냅샷)

> 이전 `docs/handoff_2026-08-10_phase3_fewshot_and_optimization.md`는 "전부 uncommitted"
> 라고 적혀 있으나, 그 이후 커밋·푸시가 끝나 지금 상태와 안 맞는다. **이 문서가 최신
> 스냅샷**이다. 이후 진행 상황은 `docs/progress.md`에 이어서 기록할 것(이 문서도 다시
> 업데이트하지 않는 1회성 스냅샷).

## 지금 정확히 어디에 있는가

- 브랜치 `feature/review-agent`. 아래 3개 커밋으로 이번 세션 변경사항 전부 커밋·푸시
  완료(`git status` 클린, 로컬 HEAD == `origin/feature/review-agent`):
  1. `34776db` fix: harden JSON parsing and isolate concurrent LLM usage tracking
  2. `f7b343a` feat: add Phase 3 fewshot combos with prompt caching, level promotion
  3. `672560d` docs: record phase 1-3 experiment results and handoff
- 전체 테스트 173개 통과 확인됨(`cd review-agent && .venv/Scripts/python.exe -m pytest -q`,
  cwd를 `review-agent/`로 명시할 것).
- ①(판정 단계 수 → `direct_verdict`/1단계), ②(청킹 → `paragraph_verdict`/문단형)는 파일럿
  5문서(DOC-001/003/006/008/012)로 잠정 확정. 결과: `docs/experiments/
  results_2026-08-10_phase1_stage_count.md`, `results_2026-08-10_phase2_chunking.md`.
- **Phase 3(세분화×퓨샷) 정적 4콤보 코드 전부 완성, 아직 한 번도 실행 안 함**
  (`ls outputs/experiments`에 `phase1_stage_count`/`phase2_chunking`/`model_pilot`만
  있고 phase3 디렉터리가 없는 것으로 확인):
  - 콜통합×룰전부 = `structures/bundled_verdict.py`
  - 콜통합×퓨샷만 = `structures/bundled_fewshot.py`
  - 콜분리×퓨샷만 = `structures/category_fewshot.py`
  - 콜분리×룰전부 = `structures/paragraph_verdict.py`(기존 ②의 셀을 재사용, **단 지금까지의
    결과는 Gemini로 나온 것이라 재사용 불가 — Sonnet으로 새로 돌려야 함**)
- 함께 반영된 것들:
  - `structures/fewshot_bank.py` — 리키지 세이프 풀(DOC-000/021~040 + 예외조건 시트의
    합성 스니펫)에서만 큐레이션, 합성 위반 예시는 전혀 안 씀(AE-03/MI-05는 안전한 예시가
    없어서 비워둠).
  - `document.py`의 `resolve_reported_level()` — 모델이 출력에 `"level"`을 명시하면 지금
    본 청크보다 넓을 때만 승격 인정.
  - 콜분리 계열(`paragraph_verdict.py`/`category_fewshot.py`) 최적화: 동적 `max_workers`
    (그 패스의 카테고리 수만큼 한 번에 병렬) + Anthropic 프롬프트 캐싱(`cache_control:
    ephemeral`, 시스템 프롬프트 + 카테고리 공유 문서 본문).
- **모델 정책**: 진짜 스크리닝 단계가 있는 구조(`cell3`)만 screen=Gemini, 나머지(모든
  confirm/single-pass 역할, Phase 3의 4콤보 전부 포함)는 Sonnet. Phase 0/1/2는 실제로는
  Gemini+Gemini로 실행돼서 정책과 안 맞음 — **나중에 재실행 예정**(아래 체크리스트 참고).
  메모리 `project_phase12_model_policy_redo`에 기록됨.

## 지금부터 해야 할 일 (실행 직전 체크리스트)

- [ ] **4콤보 Sonnet 파일럿 실행** — 파일럿 5문서(DOC-001/003/006/008/012), `--backend
      anthropic`(또는 `--confirm-backend anthropic`). **실제 API 비용 발생** — 실행 전
      사용자의 명시적 go-ahead 필요.
- [ ] 실행 후 비교표 확인 → **동적퓨샷 2콤보**(콜분리×동적퓨샷, 콜통합×동적퓨샷) 진행
      여부/방식 결정. 검색 방식은 임베딩 API 대신 간단한 텍스트 유사도로 시작 추천.
- [ ] Phase 3 결과 문서화 — `docs/experiments/results_2026-08-10_phase3_*.md`, 기존과
      동일한 표 형식(빈 헤더 셀 없이, Notion 붙여넣기 호환).
- [ ] **최종적으로 Phase 1&2를 Gemini+Sonnet 정책으로 재실행** — `direct_verdict.py`/
      `cell3.py`/`bundled_*`에도 필요하면 프롬프트 캐싱 최적화 이식.

## 참고

- 상세 계획(데이터 소스 조사, 리키지 판단, 오류 패턴 분석 반영 내역, 실행 순서 전문):
  `C:\Users\HYESEO\.claude\plans\replicated-jingling-pudding.md`.
- 이전 스냅샷(커밋 전 상태 기준, 세션 진행 서사 위주): `docs/handoff_2026-08-10_
  phase3_fewshot_and_optimization.md`.
- 팀 공유 완료 문서: `docs/share_dev_2026-08-10.md`(개발팀용, 버그/재사용 패턴),
  `docs/share_planning_2026-08-10.md`(기획팀용, 정확도 오류 패턴).
- 버그/구현 세부사항은 `docs/progress.md`에서 계속 추적, 결과/분석/결론만
  `docs/experiments/results_*.md`에 남기는 관례 유지.
- 관련 메모리: `project_phase12_model_policy_redo`(모델 정책), `project_branch_strategy`
  (`dev`는 절대 건드리지 않음), `feedback_review_agent_scope`(정확도는 eval-agent 담당,
  review-agent는 시간/토큰 비용만 측정).
