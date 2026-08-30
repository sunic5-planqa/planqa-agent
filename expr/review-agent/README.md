# planqa-review

기획서(markdown)를 업로드하면 PlanQA 룰북 기준으로 검토하고, 결과를 원문 vs 제안 **diff**
형태로 보여주는 에이전트. 구조 설명은 [`docs/review_agent_architecture.md`](docs/review_agent_architecture.md)
참고.

이 폴더는 `planqa-eval-agent` 모노레포 안에서 독립적으로 관리되는 프로젝트다 — `eval-agent/`
(평가 에이전트, 별도 폴더/브랜치 소유)와 코드를 공유하지 않는다.

## 설치

```bash
uv sync
```

## LLM 백엔드 설정

`.env.example`을 복사해서 `.env`를 만들고 값을 채운다.

```bash
cp .env.example .env
```

- `PLANQA_LLM_BACKEND` — `gemini`(기본) 또는 `ollama`(로컬)
- `GEMINI_API_KEY` 또는 `GEMINI_API_KEYS`(콤마 구분, 여러 키 라운드로빈) — Gemini 무료 티어는
  일일/분당 요청 한도가 낮아 여러 키를 준비해두는 게 좋다
- Gemini 모델명은 자주 바뀐다 — 커맨드가 404/429로 안 되면 아래 스크립트로 그 키가 실제로
  쓸 수 있는 모델을 먼저 확인할 것:
  ```python
  from google import genai
  for m in genai.Client(api_key="...").models.list():
      print(m.name)
  ```

## 실행

```bash
uv run planqa-review review \
  --input <검토할 기획서.md> \
  --doc-id DOC-001 \
  --backend gemini --screen-model <저비용 모델> --verify-model <고비용 모델> \
  --profile gemini_lite
# → outputs/review/<timestamp>/review.json, review.md
```

`--profile`은 어떤 프롬프트/로직 전략을 쓸지(`src/planqa_review/models/` 참고, 모델 실험용),
`--backend`/`--screen-model`/`--verify-model`은 어떤 LLM을 호출할지 — 서로 독립적으로 조합
가능하다.

`review.json`은 eval-agent의 Issue 스키마와 필드 호환이라, `eval-agent/`에서
`uv run planqa-eval evaluate --predictions <이 파일>`로 바로 정확도를 평가할 수 있다.

## 테스트

```bash
uv run pytest
```

## 현재 상태

초안(v1). 자세한 설계 배경과 알려진 제약은 [`docs/review_agent_architecture.md`](docs/review_agent_architecture.md),
작업 이력은 [`docs/progress.md`](docs/progress.md) 참고.
