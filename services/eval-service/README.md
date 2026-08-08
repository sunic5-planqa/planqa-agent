# eval-service

review-agent가 실제로 서비스 중인 문서에 대해 낸 결과를(golden 데이터 없이) 비동기로 채점하는
서비스. `tools/eval-agent`(골든셋 대조, CI 전용, 배포 안 됨)와는 별개 — 이쪽은 배포되고,
review-agent의 응답 경로를 절대 막지 않는다.

## 설계

```
POST /review  (사용자 요청, review-agent)
  → review-agent가 분석
  → 사용자에게 즉시 응답 반환
  → (BackgroundTasks, fire-and-forget) POST eval-service:/evaluate-async { review_result }
       → eval-service는 202 즉시 응답, SQLite outbox에 INSERT만 하고 끝
       → worker.py가 별도 프로세스로 주기 폴링(기본 5초)해서 처리
       → 결과는 별도 조회용 (review-agent는 조회하지 않음 — 순수 모니터링/품질 측정용)
```

Redis/Celery 등 외부 인프라 의존성 없음 — SQLite 파일 하나로 durable한 큐를 구현 (재시작해도
안 날아감, 인메모리 큐와 다른 점).

`queue.py`의 `EvalQueue`는 Protocol이라, 처리량이 커지면 `ArqEvalQueue`(Redis 기반) 같은
구현체로 교체 가능 — `arq`는 현재 "maintenance only mode"라 v1 기본 채택은 보류 (`docs/adr/
0002-...md` 참고).

## 실행

```bash
uv run --package planqa-eval-service uvicorn planqa_eval_service.api:app --reload
uv run --package planqa-eval-service planqa-eval-service-worker   # 별도 프로세스
```

## `judge.py` — reference-free LLM cascade

golden 데이터 없이 채점해야 해서 `tools/eval-agent`의 `judge_match()`(golden 답안과 비교하는
방식)를 그대로 못 씀 — 대신 룰 텍스트 + 에이전트 자신이 인용한 근거만으로 "confirm의 판정이
진짜 맞는가"를 재검증한다. 비용을 낮추려고 [LLM Cascade](https://github.com/stanford-futuredata/FrugalGPT)
/ [RouteLLM](https://github.com/lm-sys/RouteLLM) 패턴을 씀 (전부 다 앙상블로 재검증하면
비효율적이라):

```
Tier 1 (전체, 저렴한 모델 1개, 배치 1콜)
  → 대부분 "confident"로 끝남 — 그대로 최종 판정
  → "uncertain"만 Tier 2로 에스컬레이션

Tier 2 (uncertain인 것만, EVAL_SERVICE_ENSEMBLE 설정 시)
  → 앙상블 멤버 여러 개가 병렬로 재검증 (run_ensemble)
  → 2/3 이상 합의 → 다수결 채택
  → 합의 안 되면(ambiguous) → arbiter(EVAL_SERVICE_BACKEND) 최종 판정
```

review-agent 자신의 screen(싸게 넓게)→confirm(비싸게 좁게) 구조와 같은 원리를 채점 레이어에
한 번 더 적용한 것 — 전수를 3~4번씩 재검증하지 않고, 애매한 소수에만 비용을 씀.

환경변수:
- `EVAL_SERVICE_BACKEND` — tier-1/arbiter 모델 (기본 `gemini`)
- `EVAL_SERVICE_ENSEMBLE` — tier-2 앙상블, `name:backend[:model]` 콤마 구분. 비어있으면
  tier-2 자체가 없음 (tier-1 uncertain 판정이 그대로 최종)
- `EVAL_SERVICE_RULEBOOK_PATH` — 기본은 `data/rulebook_v1.0.md`(번들 포함)

자세한 설계 배경(왜 cascade인지, 실제 GitHub 레포 대조 확인 결과)은
`docs/adr/0001-monorepo-workspace-and-async-eval-service.md` 참고.
