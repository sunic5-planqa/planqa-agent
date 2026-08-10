# 실험 결과 — ③+④ 세분화×퓨샷 정적 4콤보, cell3형(2단계) 기준으로 재구축

## 실험 설계

①② Sonnet 재검증(`results_2026-08-10_phase1_2_sonnet_revalidation.md`)에서 ①(판정 단계
수)의 승자가 Gemini+Gemini 기준 1단계에서 Sonnet 기준 2단계(screen→confirm)로 뒤집혔다.
그래서 Phase 3(세분화×퓨샷) 4콤보를 1단계 구조(direct_verdict/paragraph_verdict 기반) 대신
2단계(screen=Gemini/confirm=Sonnet) 기반으로 다시 지었다 — ②의 승자인 문단형 청킹은 그대로
유지.

| 구조 | 세분화 | 판정 콘텐츠 | 단계 |
| --- | --- | --- | --- |
| paragraph_screen | 콜분리 | 룰 텍스트 전체 | 2단계 (신규) |
| paragraph_screen_fewshot | 콜분리 | 퓨샷 예시만 | 2단계 (신규) |
| bundled_screen | 콜통합 | 룰 텍스트 전체 | 2단계 (신규) |
| bundled_screen_fewshot | 콜통합 | 퓨샷 예시만 | 2단계 (신규) |

조건: 문서 5건(DOC-001/003/006/008/012), screen=Gemini flash-lite, confirm=Claude Sonnet,
temperature=0.0.

## 결과

### 비용 (5문서 합산)

| 구조 | LLM 콜 수 | 총 토큰 | 소요 시간 |
| --- | --- | --- | --- |
| paragraph_screen | 86 | 322,183 | 403.9초 |
| paragraph_screen_fewshot | 78 | 357,358 | 280.5초 |
| bundled_screen | 26 | 112,349 | 263.9초 |
| bundled_screen_fewshot | 19 | 105,352 | 127.1초 |

### 정확도 (같은 5문서, golden 위반 6건)

| 구조 | TP | FP | FN | recall | precision |
| --- | --- | --- | --- | --- | --- |
| paragraph_screen | 1 | 14 | 5 | 16.7% | 6.7% |
| paragraph_screen_fewshot | 0 | 10 | 6 | 0% | 0% |
| bundled_screen | 1 | 18 | 5 | 16.7% | 5.3% |
| bundled_screen_fewshot | 0 | 2 | 6 | 0% | 0% |

### 1단계(스크리닝 없음) 대비 개선 폭 — 같은 세분화 축끼리 비교

| 세분화 | 1단계(이전 파일럿) precision | 2단계(이번) precision | 배수 |
| --- | --- | --- | --- |
| 콜분리×룰전부 (paragraph_verdict → paragraph_screen) | 1.9%* | 6.7% | 약 3.5배 |
| 콜통합×룰전부 (bundled_verdict → bundled_screen) | 3.1% | 5.3% | 약 1.7배 |

*재시도 로직 수정 반영 후 재실행 수치(`results_2026-08-10_phase1_2_sonnet_revalidation.md`).

## 관찰

- **스크리닝 단계 추가가 precision을 뚜렷하게 개선한다** — 콜분리/콜통합 양쪽 모두. Gemini
  스크리닝이 Sonnet에게 넘기는 후보 자체를 좁혀줘서, Sonnet 특유의 과다지적 성향
  (`results_2026-08-10_phase3_fewshot.md` 관찰 1)이 원천적으로 억제되는 것으로 보인다.
- **2단계에서는 콜분리(paragraph_screen)가 콜통합(bundled_screen)보다 다시 precision이
  높다** — 1단계 파일럿에서는 콜분리가 같은 문장을 여러 룰로 중복 지적하는 문제가 콜통합보다
  심했는데(`results_2026-08-10_phase3_fewshot.md` 관찰 2), 스크리닝이 카테고리별로 후보를
  먼저 좁혀주면서 그 문제가 줄어든 것으로 보인다. 다만 비용은 콜통합이 훨씬 낮다(26 콜/
  112K 토큰 vs 86 콜/322K 토큰) — precision 차이(6.7% vs 5.3%)가 크지 않은 걸 감안하면
  용도에 따라 bundled_screen이 비용 효율적인 대안이 될 수 있다.
- **퓨샷만 조합은 세분화·스크리닝 여부와 무관하게 이번 표본에서 계속 recall 0** —
  AE-03/MI-05처럼 안전한 예시가 없는 룰에 이번 6건의 golden 위반 중 일부가 몰려 있을
  가능성이 높다(표본이 작아 확정은 아님).
- 잔존 오류(빈 응답/깨진 JSON)가 paragraph_screen에서 3건(재시도 4회 모두 실패) 남았다 —
  `llm/anthropic.py`의 재시도로도 못 살리는 소수의 지속적 실패가 있다는 뜻이나, 전체
  86콜 중 3건(3.5%)으로 결과에 큰 영향은 없다.

## 결론

- Phase 3의 기준 구조를 cell3형(2단계)으로 바꾼 게 유효했다 — 1단계 대비 모든 조합에서
  precision이 개선됐다.
- **콜분리×룰전부(paragraph_screen)가 이번 표본에서 정확도 최고**, **콜통합×룰전부
  (bundled_screen)가 비용 대비 효율 최고** — 둘 다 유력한 후보로 남겨둔다.
- 퓨샷 축은 이번 표본(golden 6건)에서는 결론을 내리기 어렵다 — AE-03/MI-05 편향 때문에
  더 큰 표본이나 다른 문서셋으로 재확인이 필요하다.
- 표본이 작아(golden 6건) 이 결과도 최종 확정은 아니다.
