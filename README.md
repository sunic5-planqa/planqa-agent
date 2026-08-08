# planqa-agent

`uv` workspace 모노레포. `docs/adr/0001-monorepo-workspace-and-async-eval-service.md`에 왜
이렇게 나눴는지 전체 배경이 있다.

```
services/            # 배포되는 것
  review-agent/       # 기획서를 룰북 기준으로 검토 (planqa-backend에 벤더링되어 실서비스 중)
  eval-service/        # review-agent의 실제 서비스 결과를 골든셋 없이 비동기로 채점 (신규)

tools/                # 배포 안 되는 것 — CI 전용
  eval-agent/          # review-agent 결과를 golden dataset과 대조해 recall/precision 측정

packages/
  planqa-schemas/      # Issue/RuleBook — review-agent/eval-agent가 각자 들고 있던 100% 동일
                        # 코드였던 걸 이번에 통합
```

## 설치

```bash
uv sync --all-packages
```

## 패키지별 실행

```bash
# 각 tests/ 경로를 명시해야 함 — 여러 멤버가 test_pipeline.py처럼 같은 이름의 테스트
# 파일을 갖고 있고, conftest를 `from conftest import ...`로 직접 import하는 기존 관례라
# (각 프로젝트가 독립 최상위였을 때부터의 컨벤션, 안 바꿈) pytest importlib 모드로 전체를
# 한 번에 모으면 깨짐 — 패키지별로 경로를 좁혀서 돌리는 게 맞음.
uv run --package planqa-review pytest services/review-agent/tests
uv run --package planqa-eval pytest tools/eval-agent/tests
uv run --package planqa-eval-service pytest services/eval-service/tests
uv run --package planqa-schemas pytest packages/planqa-schemas/tests

uv run --package planqa-review planqa-review review --input <기획서.md> --doc-id DOC-001
uv run --package planqa-eval planqa-eval evaluate --predictions <review.json>
uv run --package planqa-eval-service uvicorn planqa_eval_service.api:app --reload
uv run --package planqa-eval-service planqa-eval-service-worker
```

각 패키지의 자세한 사용법/아키텍처는 그 폴더의 README를 참고.
