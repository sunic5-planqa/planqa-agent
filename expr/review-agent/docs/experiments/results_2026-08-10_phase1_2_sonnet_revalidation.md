# 실험 결과 — ①②(판정 단계 수·청킹 방식) Sonnet 정책 재검증

## 배경

①(direct_verdict 1단계 승리)·②(paragraph_verdict 문단형 승리)는 원래 Gemini+Gemini로
실행됐는데, 모델 정책이 정정되어 실제로는 진짜 스크리닝 역할이 있는 구조(cell3)만
screen=Gemini, 나머지 전부(direct_verdict/paragraph_verdict의 단일 판정 역할 포함)는
confirm=Sonnet이어야 한다. Phase 3 파일럿(정적 4콤보, Sonnet)에서 모델을 바꾸는 것만으로
콜분리 구조의 정확도 특성이 크게 달라지는 걸 확인했기 때문에, Phase 3를 더 진행하기 전에
①②를 올바른 모델 정책으로 재검증했다.

조건: 파일럿 5문서(DOC-001/003/006/008/012), temperature=0.0. cell3는 screen=Gemini
flash-lite/confirm=Claude Sonnet, direct_verdict·paragraph_verdict는 confirm 역할 전체가
Claude Sonnet.

## 결과

### ① 판정 단계 수 — direct_verdict(1단계) vs cell3(2단계)

| 구조 | 모델 | TP | FP | FN | recall | precision | LLM 콜 | 총 토큰 | 소요 시간 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| direct_verdict | Gemini+Gemini (Phase 1) | 1 | 24 | 5 | 16.7% | 4.0% | 140 | 315,191 | 159.9초 |
| cell3 | Gemini+Gemini (Phase 1) | 1 | 45 | 5 | 16.7% | 2.2% | 240 | 545,135 | 203.8초 |
| direct_verdict | Sonnet (재검증) | 1 | 97 | 5 | 16.7% | 1.0% | 152 | 171,139 | 476.1초 |
| cell3 | Gemini+Sonnet (재검증) | 1 | 25 | 5 | 16.7% | 3.8% | 188 | 539,679 | 559.1초 |

**결론이 뒤집힌다.** Gemini+Gemini에서는 direct_verdict(1단계)가 precision 4.0% > cell3
2.2%로 더 나았는데, Sonnet에서는 cell3(2단계) precision 3.8% > direct_verdict 1.0%로
정반대다. 원인은 명확하다 — Sonnet은 원래 지적을 훨씬 많이 하는 성향이 있는데
(`results_2026-08-10_phase3_fewshot.md` 관찰 1 참고), direct_verdict는 그 성향을 걸러줄
스크리닝 단계가 없어 그대로 다 노출된다(FP 97). cell3는 Gemini 스크리닝이 먼저 후보를
좁혀준 뒤에야 Sonnet이 판정하므로, 애초에 Sonnet이 볼 수 있는 후보 자체가 줄어 과다지적이
억제된다(FP 25). 비용은 cell3가 더 들지만(토큰 3.2배), precision 개선(3.8배)이 그보다
크다.

### ② 청킹 방식 — direct_verdict(위계형) vs paragraph_verdict(문단형), 둘 다 1단계·콜분리

| 구조 | 모델 | TP | FP | FN | recall | precision | LLM 콜 | 총 토큰 | 소요 시간 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| direct_verdict (위계형) | Gemini (Phase 1) | 1 | 24 | 5 | 16.7% | 4.0% | 140 | 315,191 | 159.9초 |
| paragraph_verdict (문단형) | Gemini (Phase 2) | 1 | 10 | 5 | 16.7% | 9.1% | 53 | 107,712 | 73.2초 |
| direct_verdict (위계형) | Sonnet (재검증) | 1 | 97 | 5 | 16.7% | 1.0% | 152 | 171,139 | 476.1초 |
| paragraph_verdict (문단형) | Sonnet (재검증) | 1 | 51 | 5 | 16.7% | 1.9% | 56 | 60,311 | 171.2초 |

**결론은 유지된다.** 문단형이 위계형보다 비용(콜 수 63%↓, 토큰 65%↓)과 precision(1.9배)
양쪽에서 여전히 우위다 — Sonnet으로 바꿔도 방향은 같다. 위계형은 문서/논리단위/문단/문장
4단계 각각을 별도 콜로 도는 구조라, 콜 수가 늘어날수록 같은 문장이 여러 위계·여러
카테고리에서 중복 지적될 기회도 늘어나는 것으로 보인다.

## 결론 및 제안

- **②(문단형 채택)는 그대로 유지.**
- **①(1단계 채택)은 재검토가 필요하다** — Sonnet 정책에서는 스크리닝 단계(cell3형)가
  과다지적을 억제하는 데 실질적으로 도움이 된다. Phase 3(세분화×퓨샷)를 direct_verdict/
  paragraph_verdict 기반(스크리닝 없음)으로 계속 쌓기보다, cell3형(Gemini 스크리닝 +
  Sonnet 정밀판정)을 기준 구조로 다시 검토할 필요가 있다.
- 표본이 여전히 작다(golden 6건) — recall이 모든 조합에서 동일(16.7%, TP 1건)이라 이번
  재검증은 precision 방향성에 대한 근거이지, 최종 확정은 아니다.
