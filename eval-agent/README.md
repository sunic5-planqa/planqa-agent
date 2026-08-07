# planqa-eval-agent

PlanQA 프로젝트의 **평가 에이전트** — 룰북 기반 기획서 품질 검토 에이전트(별도 프로젝트, 아직
미완성)의 출력을 사람이 라벨링한 골든 데이터셋과 대조해 recall/precision을 측정합니다.

## 데이터

- `data/rulebook/` — 검토 룰북 (8개 카테고리, 41개 룰, 문서 위계·예외조건 정의)
- `data/qa_dataset/` — golden dataset(현재 38문서/131건, 계속 늘어남) + Documents 마스터(41개) +
  사람 리뷰어 6명(Review1-6, 현재 1-4만 작성됨) 시트
- `data/source_documents/` — golden dataset이 참조하는 원문 기획서 40건 (DOC-000은 원본이 빈
  파일이라 없음 — `docs/progress.md` 2026-08-05 항목 참고)
- `data/sample_review_output.json` — **19건짜리 구 golden dataset 기준으로 만든 예시라 지금은
  낡음.** 검토 에이전트 실제 출력이 없는 동안 파이프라인 배선을 확인하는 용도로만 쓰세요 (recall/
  precision 수치는 참고하지 마세요).

## 설치

```bash
uv sync
```

## LLM 백엔드 설정

`.env.example`을 복사해서 `.env`를 만들고 값을 채웁니다.

```bash
cp .env.example .env
```

- `PLANQA_LLM_BACKEND` — `gemini`(기본) 또는 `ollama`(로컬 Qwen)
- Gemini 무료 티어는 하루 요청 한도가 낮습니다(모델/키마다 다르지만 하루 20회 수준도 있음). 여러
  키를 콤마로 묶어 `GEMINI_API_KEYS`에 넣으면 한 키가 quota에 걸릴 때마다 자동으로 다음 키로
  넘어가며 씁니다 (`GEMINI_API_KEY` 단일 키도 계속 지원).
- Ollama를 쓰려면 로컬에 [Ollama](https://ollama.com)를 설치하고 모델을 pull해둬야 합니다:
  ```bash
  brew install ollama
  brew services start ollama
  ollama pull qwen2.5:1.5b     # 기본 모델
  ollama pull exaone3.5:2.4b   # 앙상블 저지용 (한국어 특화)
  ollama pull gemma2:2b        # 앙상블 저지용
  ```

## 실행

```bash
uv run planqa-eval evaluate --predictions data/sample_review_output.json

# LLM-as-judge 오케스트레이션: 4축 rubric 채점/FP triage를 로컬 sLLM 3개 합의로 (갈리면
# --backend의 모델이 arbiter로 재판정)
uv run planqa-eval evaluate --predictions data/sample_review_output.json \
  --judge-ensemble qwen:ollama:qwen2.5:1.5b,exaone:ollama:exaone3.5:2.4b,gemma:ollama:gemma2:2b
```

`--predictions`에는 검토 에이전트의 JSON 출력을 넣습니다 (기대 스키마는
`docs/adr/0001-review-agent-output-contract.md` 참고). 실제 에이전트가 아직 없는 동안은
`data/sample_review_output.json`으로 파이프라인을 시험해볼 수 있습니다.

## 테스트

```bash
uv run pytest
```

## 현재 상태 (2026-08-02)

`data/sample_review_output.json` + 실제 Gemini API로 전체 파이프라인(Parser→Matcher→Verifier→
Judge→신규룰 판별→Aggregator→Reporter) 검증 완료:

- recall / precision 89.5% (19건 중 18건 매칭)
- DOC-006 AE-01 예외조건 반례가 실제 LLM 파이프라인에서도 정확히 판정됨 (`excused=False`)
- 일부러 넣은 레벨 오분류(DOC-003 AE-03: Sentence→Paragraph)와 신규이슈 2건(new_rule_candidate /
  false_positive 판정)도 의도대로 잡힘

로컬 Ollama(`qwen2.5:1.5b`)로도 같은 파이프라인 검증 완료 (recall/precision 84.2%, quota 없이
바로 실행됨). DOC-006처럼 같은 위치에 골든 이슈가 2개(AE-01/AE-03) 겹치는 애매한 매칭에서는
Gemini보다 약한 모습을 보였는데 — 이런 모델별 신뢰도 차이를 잡아내는 게 바로 `--judge-ensemble`
(LLM-as-judge 오케스트레이션, `docs/progress.md` 2026-08-07 항목)의 역할입니다: 로컬 sLLM 3개가
합의하면 그대로, 갈리면(`ambiguous`) 강모델(arbiter)이 한 번 더 판정합니다 (메모리:
planqa-model-selection-policy).

검토 에이전트의 실제 JSON 출력은 아직 없어서 입력 스키마는 가정 상태입니다. 자세한 작업 이력은
`docs/progress.md`, 설계 결정은 `docs/adr/`를 참고하세요.
