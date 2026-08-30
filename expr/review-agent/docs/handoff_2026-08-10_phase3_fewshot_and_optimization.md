# 인수인계 — Phase 3 퓨샷 코드 완성, 모델 정책 정정, 콜분리 최적화 (2026-08-10 세션 종료 시점)

> `docs/progress.md`가 너무 요약적이라 만든 상세 인수인계 문서. 이전 handoff
> (`docs/handoff_2026-08-10_demo-v1-shipped.md`)를 이어받은 세션이 다룬 범위가 여기까지다.
> **이 문서는 일회성 스냅샷이라 다시 업데이트하지 않는다** — 이후 진행 상황은
> `docs/progress.md`에 이어서 기록할 것.

## 지금 정확히 어디에 있는가

- 브랜치: `feature/review-agent`. **⚠️ 이번 세션에서 만든 변경사항이 전부 커밋 안 된 채로
  워킹 트리에 남아있음** (`git status`로 확인: 17개 파일 수정 + 13개 신규 파일). origin과
  로컬 HEAD는 동일(밀린 커밋 없음) — 즉 커밋만 안 한 상태. 다음 세션은 먼저 `git status`/
  `git diff`로 무슨 변경인지 확인하고, 사용자 승인 받아서 커밋할 것(이 세션에선 요청 없어서
  안 함).
- 전체 테스트 173개 통과 확인됨(`cd review-agent && .venv/Scripts/python.exe -m pytest -q`,
  **cwd를 review-agent로 명시할 것** — 이번 세션에 cwd 꼬임으로 여러 번 삽질함).
- ①(판정 단계 수 → direct_verdict/1단계), ②(청킹 → paragraph_verdict/문단형)는 파일럿
  5문서(DOC-001/003/006/008/012)로 잠정 확정. 결과: `docs/experiments/
  results_2026-08-10_phase1_stage_count.md`, `results_2026-08-10_phase2_chunking.md`.
- **③+④(세분화×퓨샷 6콤보) 중 4개 코드 완성, 아직 실행 안 함** — 사용자가 "실행하기 전에
  인수인계·팀 공유 문서부터 써라"고 지시해서 지금 이 문서를 쓰는 중.

## 이번 세션에서 일어난 일 — 순서대로

### 1. Phase 1/2 결과 정리 → Notion 형식 문서화

`docs/experiments/results_2026-08-10_phase1_stage_count.md`,
`results_2026-08-10_phase2_chunking.md` 작성. 처음엔 불릿 목록으로 썼다가, 사용자가 "표가
깨진다"고 해서 표 형식으로 재작성(빈 헤더 셀 제거, 화살표/곱셈 기호 같은 특수문자 최소화)
— 이후 이 형식이 표준이 됨. **버그/구현 세부사항과 결과·분석·결론을 분리**해서, 전자는
`docs/progress.md`에만, 후자는 `docs/experiments/results_*.md`에만 쓰는 관례가 이때
확립됨.

### 2. Phase 3 퓨샷 예시 선정 계획 — 데이터 소스 조사

`data/qa_dataset/qa_dataset_frozen.xlsx`의 "golden dataset"(131행, 41룰 전부 커버)과
"예외조건 golden dataset"(59행, 26룰 커버) 시트를 위반/예외 예시 소스로 확인. **리키지
문제 발견**: golden dataset 예시를 그대로 쓰면 나중에 그 문서가 벤치마크로 채점될 때
정답을 유출함 → DOC-001..020(벤치마크)에 속한 행은 제외하고 DOC-000/021~040(벤치마크
밖)만 사용. 예외조건 시트는 전부 `DOC-000-SH-032` 같은 합성 스니펫이라 100% 안전.
**AE-03, MI-05는 안전한 위반 예시가 0개** — 사용자 지시로 **합성 예시는 절대 안 만들고
그냥 비워둠**(41룰 전부 커버 요건도 없음).

### 3. Phase 1/2 오류 패턴 분석 (Opus 서브에이전트)

파일럿 5문서의 review.json + eval-agent report.json(Judge/Triage가 이미 남긴 FP/미스
근거) + golden dataset를 대조 분석. 발견한 패턴 4가지:
1. **AE-03이 "애매하면 다 AE-03" 만능 라벨로 오용됨** — FP 최다 원인(13건).
2. **하나의 근원 문제가 여러 룰·여러 청크로 폭발** — FP 74건 중 약 40건이 이 패턴.
3. **위계(level)를 "실제 범위"가 아니라 "지금 본 청크 크기"로 정함** — level 오류 6건 중
   5건.
4. **크로스섹션 정합성 추론은 6/6 실패**, 반대로 시도할 땐 허위 충돌을 창작.

패턴 2·3은 프롬프트 지시문으로, 패턴 4(허위대립 방지)도 프롬프트로 고칠 수 있다고 판단해
사용자 승인 받아 즉시 반영. 패턴 3(level 승격)은 출력 스키마 변경이 필요해서 별도로
승인받아 나중에 반영함(아래 6번).

### 4. 모델 정책 재정정 — **중요, 다음 세션이 꼭 알아야 함**

Phase 0/1/2가 전부 Gemini+Gemini로 실행됐는데, **이게 원래 의도와 다름**을 사용자가
재차 정정함. 진짜 스크리닝 단계가 있는 구조(cell3)만 screen=Gemini, **나머지는 전부
(confirm/single_pass 역할) Sonnet**이어야 함 — ①의 결론(1단계)상 Phase 3 이후 모든
구조는 스크리닝 콜이 없으므로 전체가 Sonnet으로 돌아야 정책에 맞음.

**결정**: 시간 제약상 Phase 3부터 Sonnet 정책 적용, **Phase 1&2(Gemini+Gemini로 나온
기존 결과)는 나중에 재실행 예정**. Phase 3의 "콜분리×룰전부" 셀도 기존
`paragraph_verdict`의 Gemini 결과를 재사용하지 않고 Sonnet으로 새로 돌려야 함. 메모리
`project_phase12_model_policy_redo`에 기록해뒀음(자동으로 다음 세션에도 로드됨).

### 5. Phase 3 코드 완성 — 4콤보 + fewshot_bank

- `src/planqa_review/structures/fewshot_bank.py`(신규): 리키지 세이프 풀에서 룰마다
  위반 최대 2개 + 예외 최대 1개 큐레이션. `tests/test_fewshot_bank.py`로 리키지·룰ID
  유효성 검증.
- `structures/category_fewshot.py`(콜분리×퓨샷만), `structures/bundled_verdict.py`
  (콜통합×룰전부), `structures/bundled_fewshot.py`(콜통합×퓨샷만) 신규 작성 +
  `STRUCTURES` 등록 + 각각 테스트. `paragraph_verdict.py`가 이미 콜분리×룰전부 셀이라
  재사용(단, Sonnet으로는 아직 재실행 안 함).
- `direct_verdict.py`/`paragraph_verdict.py`/`category_fewshot.py`/`bundled_verdict.py`/
  `bundled_fewshot.py` 5개 구조 전부에 시스템 프롬프트 지시문 3개 반영: (a) 같은 근원
  문제 중복 발화 금지(1이슈=1룰, 1청크 대표), (b) 관계형 카테고리 허위대립 방지, (c)
  **level 필드로 실제 범위 승격 가능**.
- **level 필드 스키마 변경**: `document.py`에 `resolve_reported_level()` 추가 — 모델이
  출력에 `"level"`을 명시하면 지금 본 청크보다 더 넓을 때만 승격 인정(좁히는 건 항상
  무시), 위치 문자열의 " > " 앞부분을 잘라 상위 라벨 근사. 5개 구조 전부에 파싱 로직
  반영.

### 6. 콜분리 비용/시간 최적화 (사용자 요청)

사용자가 "멀티에이전트나 tool-calling 쓰냐"고 물어서 **아니라고 확인** — 파이썬 코드가
룰북 기준으로 카테고리를 이미 정해두고 `ThreadPoolExecutor`로 병렬 API 콜만 보내는
구조(초기 실험계획의 1안/2안 둘 다 아님, tool-calling은 이전 세션에 이미 검토 후 제외됨).
두 가지 최적화를 `paragraph_verdict.py`/`category_fewshot.py`에 적용:
1. `max_workers` 동적화(기본값 None → 그 패스의 카테고리 수만큼 한꺼번에 병렬, 배치 대기
   없어짐) — 비용 불변, wall time만 감소.
2. **Anthropic 프롬프트 캐싱**: `llm/base.py`의 `complete_json`에 `cache_prefix`
   파라미터 추가(다른 백엔드는 그냥 이어붙여서 하위호환), `llm/anthropic.py`가 실제로
   `cache_control: ephemeral` 적용(시스템 프롬프트 항상 캐시 + 카테고리 콜마다 공유되는
   문서 본문도 캐시). 프롬프트를 "공유 본문(cache_prefix) + 카테고리별 룰/퓨샷(prompt)"
   으로 재구성.
   **`direct_verdict.py`/`bundled_*`는 이번엔 안 건드림** — Phase 1&2 Sonnet 재실행 때
   필요하면 같이 적용할 것.

### 7. 또 다른 버그 수정 (이번 세션 중 발견)

- **JSON 파싱 방어 로직**: 모델이 이스케이프 안 된 백슬래시/트레일링 콤마를 JSON에 넣어서
  파싱 실패 → 그 콜의 결과가 통째로 유실되던 버그. `llm/base.py`의 `parse_json_response`
  에 복구 폴백 추가(1차 strict parse 실패 시 정규식으로 복구 후 재시도, 그래도 안 되면
  원래 예외 그대로).
- **AskUserQuestion에 `\uXXXX` 유니코드 escape를 손으로 타이핑해서 텍스트가 깨진 사고** —
  세 번째 재발. 메모리(`feedback_no_unicode_escapes_in_tool_text`)에 재발 방지 체크리스트
  추가 강화함.

## 다음 세션이 즉시 해야 할 일

**사용자가 이미 승인한 다음 단계**: 4콤보(콜통합×룰전부, 콜통합×퓨샷만, 콜분리×퓨샷만,
콜분리×룰전부=`paragraph_verdict` Sonnet 재실행)를 Sonnet + 파일럿 5문서로 실행, 비교표
확인.

**체크리스트**:
- [ ] 이번 세션 변경사항 커밋 여부 사용자에게 확인(현재 전부 uncommitted).
- [ ] 4콤보 Sonnet 파일럿 실행 — `--backend anthropic` (또는 필요시 `--confirm-backend
      anthropic`), 5문서(DOC-001/003/006/008/012).
- [ ] 결과 보고 나서 **동적퓨샷 2콤보**(콜분리×동적퓨샷, 콜통합×동적퓨샷) 진행 여부/방식
      결정 — 검색 방식은 임베딩 API 대신 간단한 텍스트 유사도로 시작 추천(계획 문서 참고).
- [ ] Phase 3 결과 문서화(`docs/experiments/results_2026-08-10_phase3_*.md`, 표 형식).
- [ ] **최종적으로 Phase 1&2를 Gemini+Sonnet 정책으로 재실행** — direct_verdict/cell3에도
      필요하면 프롬프트 캐싱 최적화 이식.
- [ ] 계획 파일 `C:\Users\HYESEO\.claude\plans\replicated-jingling-pudding.md`에 상세
      실행 순서/조사 결과 다 남아있음 — 참고.

## 이번 세션에서 새로 저장/갱신된 메모리

- `project_phase12_model_policy_redo` — 모델 정책 정정 내용(위 4번) 전문.
- `feedback_no_unicode_escapes_in_tool_text` — 세 번째 재발 기록, 체크리스트 추가.

## 참고 — 산출물 위치

- 신규 구조: `src/planqa_review/structures/{fewshot_bank,category_fewshot,bundled_verdict,bundled_fewshot,direct_verdict,paragraph_verdict}.py`
- 신규 테스트: `tests/test_{fewshot_bank,category_fewshot,bundled_verdict,bundled_fewshot,direct_verdict,paragraph_verdict}.py`
- 결과 문서: `docs/experiments/results_2026-08-10_phase{1_stage_count,2_chunking}.md`
- 팀 공유용 문서(이번에 같이 작성): `docs/share_dev_2026-08-10.md`, `docs/share_planning_2026-08-10.md`
