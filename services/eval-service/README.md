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

## `judge.py`는 지금 더미다

실제 rubric 로직은 다음 작업. **golden 데이터 없이** 채점해야 하므로 `tools/eval-agent`의
`judge_match()`를 그대로 복사해오면 안 됨(그건 golden 답안과 비교하는 방식) — reference-free로
새로 설계해야 함. 자세한 이유는 ADR 0002 참고.
