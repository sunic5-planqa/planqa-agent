# 실험 결과 종합

> 모델/파이프라인 구조/퓨샷 ablation 실험 결과를 여기에 정리한다. 설계 배경·실행 방법은
> `docs/review_agent_architecture.md`, 회차별 작업 로그는 `docs/progress.md`,
> 구조 로스터 정의는 `docs/handoff_2026-08-08_structure_ablation.md` 참고.
>
> 이 실험의 목적: 발표에서 "이 구조/모델 선택에 정당성이 있었다"를 뒷받침하는 것 —
> 실서비스 운영 목적이 아니다.

---

## 1. 모델 (Model Pilot)

구조 실험(2번) 전체에 고정해서 쓸 모델 하나를 정하기 위한 파일럿. baseline 구조(제안5,
`gemini_lite`)만 재사용하고, 후보 모델별로 클라이언트/백엔드만 바꿔서 같은 문서 세트를
검토시킨 뒤 시간/토큰/정확도(eval-agent)를 비교한다. 정확도는 review-agent가 직접
계산하지 않고 eval-agent(`planqa-eval evaluate`)로 측정한다.

### 후보 모델

| 모델 | 백엔드/모델 ID | 비고 |
|---|---|---|
| Gemini | `--backend gemini` (기존) | 이미 구축됨, 엔지니어링 비용 0 |
| Claude Sonnet 5 | `--backend gateway --screen-model claude-sonnet-5` | mindlogic 게이트웨이 경유 |
| GPT-5.4 | `--backend gateway --screen-model gpt-5.4` | mindlogic 게이트웨이 경유 |
| EXAONE | `--backend gateway --screen-model LGAI-EXAONE/K-EXAONE-236B-A23B` | 국산, 규정 기반 추론(법률/과학/의학) 강점으로 룰북 위반 판정과 유사 |
| Solar Pro3 | `--backend gateway --screen-model solar-pro3` | 국산(Upstage), 한국어 자연스러움 — HyperCLOVA X 대체(게이트웨이에 HyperCLOVA X는 없음) |

### 파일럿 문서 (`[멘토용]_오류_정답지.md` 난이도 기준 + golden dataset row 수)

| 문서 | 난이도 | 골든 row 수 | 오류 유형 |
|---|---|---|---|
| DOC-006 | 1단계(기본) | 2 | 모호한 표현 다수(SLA 기준 없는 표현) |
| DOC-003 | 2단계(중급) | 2 | 모호한 표현 + 내부 모순 |
| DOC-012 | 2단계(중급) | 1 | 상위 목표 정합성(GA) |
| DOC-001 | 3단계(고급) | 1 | 논리 오류, 문서 내 먼 섹션 연결 필요 |
| DOC-008 | False Positive 테스트 | 0 | 정상 문서 — 과탐지 확인용 |

### 결과

*(실행 후 채움)*

| 모델 | 총 소요시간(초) | 총 토큰 | recall | precision | 한국어 품질(사람 평가) |
|---|---|---|---|---|---|
| Gemini | | | | | |
| Claude Sonnet 5 | | | | | |
| GPT-5.4 | | | | | |
| EXAONE | | | | | |
| Solar Pro3 | | | | | |

**선정 모델**: *(미정)*

---

## 2. 파이프라인 (구조)

### 2-1. 전체 구조 (제안0 / 제안5 / 셀3 / 셀3R / 셀4 / 셀1 / 셀1R / 셀2)

1번에서 고정한 모델로, 벤치마크 DOC-001~020 전체를 대상으로 각 구조를 비교한다.

| 구조 | 정의 | 총 소요시간 | 총 토큰 | recall | precision |
|---|---|---|---|---|---|
| 제안0 | 위계 청킹, 2단계 없이 위계당 1콜로 바로 최종 판정 | | | | |
| 제안5 | baseline — 위계 청킹, 2단계(스크리닝→정밀판정), 카테고리 묶음 1콜 | | | | |
| 셀3 | 위계 청킹, 카테고리별 독립 병렬 호출(tool-calling 없음) | | | | |
| 셀3R | 셀3 + 룰 단위까지 병렬 세분화(tool-calling 없음) | | | | |
| 셀4 | 셀3R + 룰별 tool-calling(스킵 허용) | | | | |
| 셀1 | 문단 청킹 + 카테고리별 병렬 (GA는 문서 전체 1회 별도) | | | | |
| 셀1R | 셀1 + 룰 단위 세분화 | | | | |
| 셀2 | 셀1R + 룰별 tool-calling | | | | |

**선정 구조**: *(미정)*

### 2-2. 얹는 보강 (제안6 / 제안7 / 제안8 / 제안9)

2-1에서 고른 최선 구조 위에, 하나씩만 켜서 비교(동시에 여러 개 켜지 않음).

| 보강 | 정의 | 적용 전 recall/precision | 적용 후 recall/precision | 비용 변화 |
|---|---|---|---|---|
| 제안6 | Generator-Critic (confirm 이후 재검토 단계) | | | |
| 제안7 | Chain-of-Verification (판정을 하위질문 체인으로 분해) | | | |
| 제안8 | confirm 호출을 위계당 1회 → 문서당 1회로 배치 축소 | | | |
| 제안9 | Self-consistency 앙상블 (temperature>0으로 screen N회 반복, 다수결) | | | |

---

## 3. 퓨샷

구조/모델이 확정된 뒤 진행. 후보 방안(제안8/9/10 — few-shot 전달 방식 관련, 구조 제안과
번호가 겹치니 문서 내에서 "few-shot 제안"으로 구분):

- 검색 기반 동적 few-shot
- 정적 룰별 few-shot 뱅크 + 프롬프트 캐싱
- 위반:예외 비율 조정 (995행 "예외조건 golden dataset" 시트 활용 가능)

*(실행 후 채움)*
