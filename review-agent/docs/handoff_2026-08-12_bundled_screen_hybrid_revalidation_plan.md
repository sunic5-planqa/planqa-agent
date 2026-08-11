# 인수인계 — bundled_screen_hybrid 20문서 재검증 + 정확도 개선 (2026-08-12)

> compact 직전에 작성. 이 문서는 plan 파일(`C:\Users\HYESEO\.claude\plans\
> replicated-jingling-pudding.md`)의 "신규: bundled_screen_hybrid 20문서 재검증 +
> 정확도 개선" 절을 실행하는 데 필요한 세부 사실·근거·아직 안 끝난 논의를 보존한다.
> **plan 파일이 실행 순서의 최종본이고, 이 문서는 그걸 실행할 때 참고할 배경 자료다.**
> 둘 다 같이 읽을 것.

## 지금 상태

- 사용자가 **실제 사용자 피드백 원문을 다음 턴에 직접 붙여넣을 예정** — 그걸 보고
  plan의 "정확도 개선" 절(특히 발견1/발견2, 실행 순서 1번)을 더 보완해야 한다. 아직
  plan 승인이 최종 확정된 건 아니고, 이 피드백 반영 후 다시 조율 필요.
- plan 파일은 ExitPlanMode로 "승인됨" 상태지만, 사용자가 마지막으로 남긴 코멘트
  (Batch API 관련, 아래 "미해결 질문" 참고)에 대한 답을 아직 안 준 상태에서 compact
  요청이 들어왔다.
- 지금까지 이 세션에서 실행한 코드/커밋은 **전혀 없음** — 전부 조사·계산·plan 파일
  갱신뿐이었다(마지막 실제 코드 커밋은 이전 세션의 eval-agent 결정론적 채점 +
  Sentence 강등 수정, 이미 완료·아카이브됨).

## 미해결 질문 (다음 턴에서 먼저 답할 것)

사용자의 마지막 plan 코멘트: **"Batch API 관련해서 — 너무 많은 수정이 필요해? 어차피
발표가 곧이라 실험은 이게 끝이 되긴 할 거야."**

- 맥락: plan에 "Batch API(50% 할인)는 엔지니어링 비용 대비 이득이 적어서(1회성 $7
  실행에 ~$3.5 아끼는 정도) 이번엔 제외, 반복될 예정이면 재검토"라고 써놨는데, 사용자가
  "이게 마지막 실험일 것 같다"는 정보를 새로 줌 — 이건 오히려 "반복 안 될 거면 Batch
  API 투자할 이유가 더 없다"는 뜻으로 해석하는 게 자연스럽다(1회성이라는 전제가 이미
  Batch API 제외 논리의 핵심이었으므로).
- **아직 답 안 했음** — 다음 턴에서 "1회성이면 오히려 Batch API 안 하는 게 더
  맞다"는 결론을 명확히 전달하고 확인받을 것. (구현 자체가 크게 부담되는 수준은
  아니다 — `llm/anthropic.py`에 배치 제출/폴링 메서드 하나 추가 + `bundled_screen_
  hybrid.py`/실행 스크립트를 "제출→대기→결과수집" 흐름으로 바꾸는 정도지만, 20문서
  ×4~5콜 남짓 규모에서 ~$3.5 아끼려고 새 비동기 경로를 만들고 검증하는 건 발표
  일정 앞두고 리스크 대비 이득이 작다.)

## Plan 파일 요약 (전체 내용은 plan 파일 참고, 여기선 핵심만)

### 무엇을 하기로 했는가

1. **`bundled_screen_hybrid`(데모2, 실제 서비스 구조) 하나만 leak-safe DOC-001~020
   전체로 재실행** — 12개 구조 전부 재실행($184)이 아니라 이 구조 하나만($7). ①②
   (판정 단계 수/청킹 방식)는 기존 6건 표본 결론이 이미 견고해서 재확인 생략.
2. **정확도 개선 2건**을 이 재실행 전에 review-agent 소스에 직접 반영(아래 "발견1/2"
   참고) — 사용자가 "정확도를 엄청 올려야 해"라고 명시적으로 요청.
3. **속도/비용 최적화**: prompt caching(`cache_prefix`), confirm 프롬프트 룰 블록
   중복 제거, 문서 단위 병렬 실행. Batch API는 위 "미해결 질문" 참고, 기본 제외.
4. `fewshot_bank.py`를 leak-safe(DOC-000+021~040만 소스)로 재구축 — 20문서 전체를
   채점 대상으로 쓰려면 필수(안 하면 나머지 15문서가 퓨샷 소스로 쓰이고 있어서 leak).

### 왜 로컬 모델(Qwen3 등)로 대신 측정하는 걸 기각했는가

이 프로젝트 안에서 이미 실증된 사실: **모델을 바꾸면 "어느 구조가 이기는지" 결론
자체가 뒤집힌다** — ①번 실험에서 confirm=Gemini일 때 "1단계 승", confirm=Sonnet일
때 "2단계 승"으로 뒤집혔음(보류 건수 22→96건, `docs/experiments/results_2026-08-10_
phase1_2_sonnet_revalidation.md` 참고). 로컬 모델로 재실행하면 "그 로컬 모델 기준
어느 구조가 이기는가"에 대한 답만 나오고, 실제 서비스(Sonnet5) 성능 평가를 대신하지
못함. 게다가 AMD Radeon RX 6900 XT(16GB VRAM, Windows)+Ollama+MoE 모델(Qwen3-30B-A3B)
조합은 검색 결과 호환성이 불안정하다고 나왔고 실측도 안 했다.

### 비용 계산 — 정확한 도출 과정 (재현 가능하도록 남김)

1. 처음에 `cell3`/`direct_verdict`(무거운 실험 구조)의 confirm 토큰수에서 사용자가
   말한 "$0.3~0.4/문서"를 역산해 **$10/M 토큰**으로 잘못 추정.
2. **사용자가 직접 확인**: 그 $0.3~0.4/문서는 `bundled_screen_hybrid`(데모2) 자체를
   돌렸을 때 나온 숫자였음.
3. `bundled_screen_hybrid`의 실측 데이터(`review-agent/outputs/experiments/
   phase3_content_axis/bundled_screen_hybrid/predictions.json`의 `stats.by_stage`):
   confirm+context(둘 다 Sonnet 사용) 토큰이 5문서 평균 **8,792토큰/문서**.
4. 역산: $0.35(중간값)/8,792토큰×1,000,000 ≈ **$39.8/M**(범위: $34~46/M, 중간값
   **$40/M로 채택**).
5. 이 $40/M을 다른 구조들의 실측 토큰(같은 방식으로 `by_stage`에서
   `confirm`/`single_pass`/`context` 합산, 5문서 평균 후 ×4로 20문서 추정)에 적용해서
   구조별 20문서 비용을 재계산 — plan 파일의 표 그대로.
6. `bundled_screen_hybrid` 20문서 재추정 = **$7.00**(8,792×4×$40/1,000,000 ≈ $7.03,
   plan엔 $7.00으로 표기).

**주의**: 이 $40/M은 딱 하나의 실측 기준점(bundled_screen_hybrid, "$0.3~0.4/문서")에서
역산한 값이라 다른 구조에 그대로 적용하는 게 완벽히 정확하진 않을 수 있다(호출당
고정비용, prompt 구조 차이 등으로 실제 단가가 구조마다 조금 다를 수 있음) — 그래도
이전의 $10/M보다는 훨씬 근거 있는 값이다. **실제 재실행 후 API 응답의 실비용과 이
추정치($7)를 반드시 대조할 것**(plan의 검증 절에 이미 명시).

## 정확도 개선 — 조사 원문 근거 (GitHub, `gh` CLI 없어서 REST API로 직접 조회)

`gh` CLI가 이 환경에 없다(Bash/PowerShell 둘 다 인식 못 함). 대신 **비인증
`curl`/GitHub REST API**로 공개 저장소를 조회했다 — 앞으로도 이 방법을 쓸 것:
`curl -s "https://api.github.com/repos/<org>/<repo>/issues/<n>"`,
`.../pulls/<n>/files` (patch 필드에 diff가 통째로 들어있음).

### 저장소 식별

- `sunic5-planqa/planqa-agent` — 이 모노레포(지금 작업 중인 저장소).
- `sunic5-planqa/planqa-backend` → **`sunic5-planqa/planqa`로 리네임됨**(API가 301
  리다이렉트로 알려줌). 실제 배포 백엔드. **로컬 클론 없음** — `C:\Users\HYESEO\
  Desktop\` 전체를 훑어도 없었다. `git worktree list`로 확인한 이 저장소의 다른
  워크트리(`eval-agent-check`/`eval-agent-latest`/`review-agent-demo-2`)는 전부
  `planqa-agent` 브랜치일 뿐, `planqa`/`planqa-backend`가 아니다.

### 발견 1 — 카테고리 오분류 (이슈 #26 → PR #27/#61)

- 이슈: https://github.com/sunic5-planqa/planqa-agent/issues/26 (2026-08-10,
  kayo2e 작성 — "카테고리 오분류(GA↔TC, TC↔MI) 및 재현율/일관성 문제"). 4가지 사례:
  ① GA가 TC로 오분류, ② TC가 MI로 오분류, ③ 재현율 저조(심어둔 위반 6건 중 4건
  미탐지), ④ 같은 문서 재검토 시 비결정성(1차엔 잡힌 AE 위반이 2차엔 안 잡힘).
- PR https://github.com/sunic5-planqa/planqa-agent/pull/27 — ①②만 대응(③④는 재현
  입력이 없어서 보류). `dev` 브랜치의 `services/review-agent/src/planqa_review/
  structures/bundled_screen_hybrid.py`에 `_CATEGORY_BOUNDARY_NOTES` 상수 추가(순수
  프롬프트 텍스트, 시그니처 변경 없음). **정확한 위치**: `_RELATIONAL_CATEGORIES`
  정의 직후, `_SCREEN_HYBRID_SYSTEM`/`_CONFIRM_HYBRID_SYSTEM` 양쪽 끝(JSON 응답 형식
  지시 직전)에 `f"{_CATEGORY_BOUNDARY_NOTES}\n"`로 삽입.
- 상수 전체 텍스트(영문, 그대로 포팅할 내용):
  > "Two category mix-ups come up often enough to call out specifically. GA (상위
  > 목표와 세부 내용의 정합성) is about two statements making genuinely DIFFERENT or
  > CONFLICTING claims about what happens, is true, or is allowed... TC (용어 및
  > 단어의 일관성) is about the SAME claim/fact being restated with inconsistent
  > wording... If two statements disagree on the facts, that's GA, never TC...
  > Separately: before flagging something as MI (정보 누락) because a term or
  > concept seems undefined, consider whether it might just be a reworded reference
  > to something already established elsewhere in the document... that's TC, not
  > MI. You're only given a short document-context summary here, not a full
  > glossary... lean toward TC over MI whenever a plausible earlier referent
  > exists, and reserve MI for things the document doesn't address at all."
  (`_CONFIRM_HYBRID_SYSTEM`에 삽입할 때는 뒤에 한 문장 추가: "A candidate you're
  confirming was already assigned its rule_id by the screening pass, which can
  mis-tag exactly these two confusions — if the candidate doesn't actually fit the
  rule you were given for that reason, set violated=false rather than confirming a
  violation of the wrong rule.")
- PR https://github.com/sunic5-planqa/planqa/pull/61 — 위 수정을 백엔드에 벤더링
  (동기화만, 로직 변경 없음).
- **우리 `feature/review-agent`의 `bundled_screen_hybrid.py`엔 이 상수가 없다** —
  demo2 병합(PR #21, 그 이전 시점) 이후 나온 후속 수정이라 못 받았음. 포팅 필요.
  단, 우리 `_CONFIRM_HYBRID_SYSTEM`은 이번 세션에 이미 한 번 수정됨(Sentence 강등
  지시 추가, `docs/handoff_2026-08-11_eval_agent_deterministic_plan.md` 참고) —
  두 수정을 합칠 때 충돌 없이 이어붙이면 됨(둘 다 프롬프트 끝쪽에 별개 문단으로 추가
  하는 방식이라 서로 안 겹침).

### 발견 2 — MI/AE 과탐지, "정보가 실제로 있는데 없다고 판정" (PR #28/#55)

- **"소제목 부분이 내용이 부족하다고 오류로 잡히는" 정확한 문구는 못 찾았다** — 다만
  증상이 정확히 일치하는 실제 사례를 찾음.
- PR https://github.com/sunic5-planqa/planqa/pull/28 (`planqa`=백엔드,
  2026-08-10 머지): 실서버 DOC-001의 "8. 런칭 계획" 섹션에 "목표 런칭일: February
  10, 2024" 같은 날짜가 **실제로 명시돼 있는데도** MI(정보 누락)로 오탐된 사례.
  파서 문제인지 먼저 확인했으나 아니었음(HTML→마크다운 변환에서 날짜가 정확히
  뽑힘) — **confirm이 좁은 chunk(그 문단)만 보고 "여기 없다"를 "문서 전체에 없다"로
  착각**한 진짜 hallucination.
  - `services/eval-service`의 `judge.py`(`judge_review_result`)로 걸러볼 수 있는지
    검토했으나 **그건 원본 문서 텍스트를 아예 안 받는 reference-free 구조**라("근거는
    논리적인데 전제가 문서와 안 맞는" 유형은 원천적으로 못 잡음) 재사용 불가 판단.
  - 해법: `backend/src/sunnic_backend/api/qa_jobs.py`에 `_verify_mi_finding(document_
    text, issue, llm)` 추가 — MI 이슈마다 **문서 전체 텍스트**를 다시 주고
    `{"actually_missing": bool, "reason": str}` 재확인, `actually_missing=false`면
    그 이슈를 최종 결과에서 제외. `_run_review_sync`에서 `review_document()` 결과의
    MI 이슈들을 이걸로 필터링. **LLM 에러/응답 이상 시엔 원래 판정 유지**(fail-safe —
    조용히 숨기지 않고, 검증 실패를 오탐 확정으로 오해하지 않게).
  - **`review_agent/**` 벤더링 파일은 손대지 않음** — PR #25 설명에 "review_agent/**
    벤더링 파일 안의 지적이라 ADR 0001 정책상 로컬에서 고치지 않음"이라고 명시. 즉
    백엔드팀은 **의도적으로 우회 패치를 택함**, review-agent 소스 자체를 못 고치는
    입장이었다(우리는 그 소스를 직접 소유하고 있으니 이 제약이 없음).
- PR https://github.com/sunic5-planqa/planqa/pull/55 (백엔드, 2026-08-11): 같은
  패턴을 AE(모호한 표현)에도 확장 — "알파테스트 재보고: MI뿐 아니라 AE도 과탐지
  경향". `_verify_ae_finding` 신설(AE-01/AE-04의 "다른 곳에 정의/참조되면 예외" 조건
  재확인), `_verify_mi_finding`/`_verify_ae_finding`을
  `_FALSE_POSITIVE_VERIFIERS: dict[str, Callable]`로 일반화해서 `_run_review_sync`의
  필터링을 `rule.category != "MI"` 하드코딩에서 딕셔너리 조회로 바꿈(카테고리 늘어날
  때 한 줄만 추가하면 되게).
  - **MI/AE만 이렇게 하는 이유(코드 커밋 코멘트 원문)**: "문서 전체를 봐야 판단
    가능한 예외조건을 가진 건 이 둘뿐(MI, AE) — 나머지 카테고리로는 안 넓힘(비용
    문제도 있음)."
  - PR #55 마지막 노트: "이어서 사용자가 대량으로 재보고한 다른 이슈들(프레이밍
    실패 재발/카테고리 오분류/재현성 문제 등)은 별도로 다룸 — 진행 중." → **이보다
    더 최신 이슈/PR이 있을 가능성이 높음**, plan의 실행 순서 1번에서 재확인하기로
    했었음. 사용자가 다음 턴에 원문을 직접 준다고 했으니 그걸로 대체/보강.
- PR https://github.com/sunic5-planqa/planqa/pull/35 (백엔드): 같은 위치/인용문에
  여러 카테고리가 동시에 걸릴 때 우선순위 높은 카테고리 하나만 남기는 사후 dedup —
  MI/AE 재검증과는 별개 이슈, 이번 조사에서 깊게 안 봄. 필요하면 나중에 참고.

### review-agent 자체 코드에서 확인한 근본 원인

- `review-agent/data/rulebook/rulebook_v1.0.md:150-163`: MI-01~08은 전부 "~가
  존재해야 한다" 형태의 존재-확인형 룰(목적/처리과정/결과/예외처리/외부연계/시간조건/
  양방향처리).
- `review-agent/src/planqa_review/tiers.py`의 `ABSENCE_CHECK_RULE_IDS =
  frozenset({"LG-01", "TC-02"})` — 룰북 §1이 "부재 확인형(문서 전체를 봐야 판단
  가능)"이라고 명명한 건 이 두 개뿐이고, **MI 카테고리는 여기 없다**. 즉 MI는
  문단(Paragraph) 단위로만 검토돼서 confirm이 "이 문단엔 없다"밖에 알 수 없음 —
  PR #28이 고친 것과 정확히 같은 구조적 원인.
- `review-agent/docs/progress.md`에 이미 이 갭이 TODO로 남아 있었음("Absence Check
  확장 검토") 및 유사 증상이 별도로 관찰된 기록도 있음("MI-05류 예외 처리 누락을
  숫자 제한 문장마다 지적").
- `bundled_screen_hybrid.py`의 `_paragraph_and_document_rules()`가 GA/LG/LF(관계형)
  +`ABSENCE_CHECK_RULE_IDS`를 문서 tier로, 나머지를 문단 tier로 나누는 지점 —
  여기에 MI를 추가하거나, 아니면(더 유력한 방향) **문단 tier는 그대로 두고 confirm
  이후 별도 재검증 단계를 추가**하는 게 plan에서 채택한 방향(백엔드 PR #28/#55 방식
  포팅).

## 다음 턴에서 할 일 (순서대로)

1. 사용자가 붙여넣을 **실제 사용자 피드백 원문을 읽고**, 위 발견1/2 및 plan의 실행
   순서 1번("최신 피드백 재확인")을 그 원문 기준으로 다시 보완 — 특히 "소제목 부분
   내용 부족 오류"가 지금 추정한 MI 메커니즘과 정확히 일치하는지, 아니면 다른
   메커니즘(예: 다른 카테고리, 다른 원인)인지 확인.
2. "Batch API, 이게 마지막 실험" 코멘트에 답하기(위 "미해결 질문" 참고) — 결론
   후보: 1회성이면 Batch API 안 하는 쪽으로 재확인.
3. 위 둘이 정리되면 plan 파일의 "정확도 개선"/"실행 순서" 절을 최종 업데이트하고,
   실제 구현 착수(plan 파일의 실행 순서 1~10번).

## 관련 파일/메모리 포인터

- Plan 파일: `C:\Users\HYESEO\.claude\plans\replicated-jingling-pudding.md` (이
  세션의 모든 계획이 여기 있음 — 이 handoff는 배경 자료일 뿐, 실행 순서의 원본은
  plan 파일).
- 이전 handoff: `review-agent/docs/handoff_2026-08-11_eval_agent_deterministic_plan.md`
  (eval-agent 결정론적 채점 + Sentence 강등 수정 — 이미 완료·아카이브).
- 실험 결과: `review-agent/docs/experiments/results_2026-08-11_deterministic_rescore.md`
  (v3, 이번 재실행 결과를 여기에 새 절로 추가할지 별도 문서로 뺄지 아직 미정).
- 기획팀 공유 문서: `review-agent/docs/architecture_explainer_for_planning_team.md`
  (완료, 4차 갱신 — 이번 정확도 개선이 실제로 반영되면 이 문서도 갱신 후보).
- 메모리: `feedback_no_synthetic_fewshot_examples`(fewshot 재구축 시 합성 금지 원칙
  재확인), `feedback_no_push_without_request`(이번 작업도 브랜치 로컬에만, push 요청
  없으면 안 함), `feedback_additive_structures_only`(pipeline.py/gemini_lite 직접
  수정 금지, 이번 수정은 전부 `bundled_screen_hybrid.py`/`tiers.py` 등 개별
  구조·설정 파일 범위 안 — 이 원칙에 위배 안 됨).
