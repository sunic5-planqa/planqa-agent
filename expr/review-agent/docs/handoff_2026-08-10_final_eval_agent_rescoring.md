# 인수인계 — ③ 세분화×콘텐츠 최종 파일럿 + eval-agent 재채점 완료 (2026-08-10 세션 종료 시점)

> `docs/progress.md`가 너무 요약적이라 만든 상세 인수인계 문서. 이전 handoff
> (`docs/handoff_2026-08-10_phase3_ready_for_pilot.md`)를 이어받은 세션이 다룬 범위가
> 여기까지다. **이 문서는 일회성 스냅샷이라 다시 업데이트하지 않는다** — 이후 진행 상황은
> `docs/progress.md`에 이어서 기록할 것. 실험 결과 자체의 최종 결론은
> `docs/experiments/results_2026-08-10_final_summary.md` 하나만 보면 됨(이 문서는 "무슨
> 일이 있었는지"에 집중).

## 지금 정확히 어디에 있는가

- 브랜치 `feature/review-agent`. **이번 세션 변경사항 전부 커밋 안 된 채로 워킹 트리에
  남아있음**(`git status --short`로 확인: 약 42개 파일, 수정 14개 + 신규 28개). 커밋 요청은
  이번 세션엔 없었음(memory: 사용자 요청 없이는 커밋/푸시 안 함) — 다음 세션은 커밋 여부
  사용자에게 먼저 확인할 것.
- 전체 테스트 219개 통과 확인됨(`.venv/Scripts/python.exe -m pytest -q`, **cwd를
  `review-agent/`로 명시할 것** — 이 저장소는 실제로는 `planqa-eval-agent/`가 git 루트고
  `review-agent/`는 그 하위 디렉터리다).
- **실험 결론이 최종 확정됨**: `bundled_screen_hybrid`(2단계 screen→confirm, 콜통합,
  룰텍스트+퓨샷 예시 함께) 채택 추천. 근거와 전체 흐름은
  `docs/experiments/results_2026-08-10_final_summary.md`에 정리돼있음 — **다음 세션이
  실험 관련 질문을 받으면 이 문서부터 읽을 것.**
- eval-agent 재채점용 별도 git worktree가 `C:\Users\HYESEO\Desktop\eval-agent-latest`에
  살아있음(origin/main 체크아웃, venv+의존성 설치 완료, PYTHONPATH로 `planqa_eval`/
  `planqa_schemas` 연결). 재사용 가능 — 아래 "참고" 섹션에 실행 방법 정리.

## 이번 세션에서 일어난 일 — 순서대로

1. **`paragraph_screen_hybrid`/`bundled_screen_hybrid` 파일럿 실행**(직전 세션에서 코드만
   만들고 API 소진으로 미뤄뒀던 것). 동시에 재선정된 `fewshot_bank.py`로
   `paragraph_screen_fewshot`/`bundled_screen_fewshot`도 재실행(구 뱅크 결과는
   `results_2026-08-10_phase3_screen_static4.md`에 남아있음, 참고용).
   → **`bundled_screen_hybrid`가 review-agent 자체채점 precision 33.3%로 이번 세션
   최고치**. 룰+퓨샷 함께 준 게 퓨샷만 준 것보다 뚜렷하게 나음(퓨샷만은 재선정 후에도
   recall 0% 유지 — AE-03 실 예시가 생겼는데도 안 잡음).
2. **eval-agent 최신본 통합 준비**. 사용자가 팀원이 origin/main에 올린 eval-agent
   개선사항(`valid_but_unlabeled` triage, `overall_relaxed`/`tier_accuracy`)을 "최신버전
   가져와서 써야 한다"고 지시. `../eval-agent-latest` git worktree로 origin/main 체크아웃,
   uv가 없어서 pip+PYTHONPATH로 `tools/eval-agent`+`packages/planqa-schemas` 로컬 패키지
   연결. review-agent의 `predictions.json`(experiment.py가 이미 생성)이 eval-agent의
   `--predictions` 입력 포맷과 정확히 일치한다는 것 확인(기존 계약,
   `docs/adr/0001-review-agent-output-contract.md`).
3. **Gemini API rate limit** — 파일럿 도중 6개 라운드로빈 키가 전부 소진. 사용자가 새 키를
   `.env`(`planqa-eval-agent/.env`, review-agent 루트가 아니라 그 상위)에 넣을 때까지 대기.
4. **6개 구조를 eval-agent로 재채점**. 결과를 그냥 받아쓰지 않고 직접 report.json을 열어서
   검증함 — 그 과정에서 **2가지를 직접 발견**:
   - review-agent 자체채점의 FP 대부분이 eval-agent judge에게 `valid_but_unlabeled`(진짜
     맞는 지적, golden이 안 라벨링했을 뿐)로 재분류됨 — precision이 구조당 최대 6.7%→100%
     까지 뛰었음.
   - eval-agent의 "predicted가 다룬 문서로만 golden을 좁히는" 로직이 우리 상황("5문서 다
     검토했지만 일부에서 0건 지적")을 잘못 해석해서, 구조마다 recall 분모(6건 중 몇 건)가
     달라짐 — TP/6으로 수동 보정해서 다시 비교(`bundled_screen_hybrid`/`paragraph_screen_
     hybrid`의 recall이 원래 50%/40%로 부풀려져 있었고, 보정 후 33.3%로 낮아짐).
5. **결과 종합 문서화**: `docs/experiments/results_2026-08-10_final_summary.md`(①②③ 전체
   흐름 + 최종 결론 + 방법론 노트), `docs/experiments/results_2026-08-10_eval_agent_
   rescoring.md`(eval-agent 재채점 상세), `docs/experiments/results_2026-08-10_content_
   axis.md`(콘텐츠축 3방향 비교 상세) — 개별 문서.

## 다음 세션이 알아야 할 것 / 체크리스트

- [ ] **커밋 여부 사용자에게 확인** — 현재 전부 uncommitted(약 42개 파일).
- [ ] 실험 자체는 **결론 확정됨**(`bundled_screen_hybrid`) — 추가 파일럿이 필요하다고
  사용자가 판단하지 않는 한, 실험은 이걸로 마무리해도 됨.
- [ ] 아직 안 돌린 것: `paragraph_screen_fewshot_ratio`/`bundled_screen_fewshot_ratio`
  (비율조정), `paragraph_screen_dynamic_fewshot`/`bundled_screen_dynamic_fewshot`
  (동적퓨샷) — 코드/테스트는 완성(전체 219개 테스트에 포함), 파일럿은 안 함. 지금
  결론에 영향 안 준다고 판단해서 스킵했음 — 사용자가 원하면 진행.
- [ ] eval-agent의 문서 스코핑 이슈(위 4번)는 팀원에게 참고로 전달할 만한 내용 — 아직
  전달 안 함.
- [ ] `../eval-agent-latest` worktree는 그대로 남겨둠(재사용 가능). 정리하려면
  `git worktree remove ../eval-agent-latest` (review-agent 루트가 아니라
  `planqa-eval-agent/`에서 실행).

## 참고 — eval-agent 재실행 방법

```
cd C:\Users\HYESEO\Desktop\eval-agent-latest\tools\eval-agent
# PYTHONPATH: src + ../../packages/planqa-schemas/src (Windows 경로, ; 구분)
# GEMINI_API_KEYS는 review-agent와 같은 상위 .env(planqa-eval-agent/.env)에서 로드
```
직접 호출 예시 스크립트는 스크래치패드에 있었음(`run_eval_agent.py`, 세션 종료 후
사라짐) — `planqa_eval.harness.full_eval.run_full_evaluation` + `planqa_eval.reporter.
write_report`를 구조별로 순회 호출하는 패턴, 필요하면 재작성.

## 참고 — 결과 문서 전체 목록 (날짜순)

`results_2026-08-10_phase1_stage_count.md` → `results_2026-08-10_phase2_chunking.md` →
`results_2026-08-10_phase1_2_sonnet_revalidation.md`(①역전) →
`results_2026-08-10_phase3_screen_static4.md` → `results_2026-08-10_phase3_fewshot.md` →
`results_2026-08-10_phase3_content_axis.md` → `results_2026-08-10_eval_agent_rescoring.md`
→ **`results_2026-08-10_final_summary.md`(최종 종합, 여기부터 읽을 것)**.

## 관련 메모리

- `feedback_no_synthetic_fewshot_examples` — fewshot_bank.py는 실제 xlsx 행만 사용, 합성
  절대 금지(리키지 범위는 조정 가능하지만 이 원칙은 안 바뀜).
- `project_phase12_model_policy_redo` — 모델 정책(screen=Gemini, confirm=Sonnet) 최종본.
- `feedback_review_agent_scope` — review-agent는 비용/시간, 정확도는 (지금부터는 최종
  eval-agent 재채점 결과를 신뢰) eval-agent 담당이라는 원래 역할 분리가 이번 세션에서
  실제로 작동함을 확인.
