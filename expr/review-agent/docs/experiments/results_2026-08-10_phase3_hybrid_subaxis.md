# 실험 결과 — hybrid 기반 퓨샷 세부 축 3종 (위반예시↑ / 예외예시↑ / 동적검색)

## 배경

`results_2026-08-10_phase3_content_axis.md`에서 룰텍스트+퓨샷(hybrid, 특히 콜통합인
`bundled_screen_hybrid`)이 퓨샷만/룰만보다 뚜렷하게 나았다는 결론이 났다. 이번 실험은
"hybrid가 이겼으니, hybrid 안에서 퓨샷을 더 다듬으면 더 좋아지는가"를 검증한다 — 이전
세션에 미리 만들어둔 `*_fewshot_ratio`/`*_dynamic_fewshot` 4개 구조는 이미 기각된 "퓨샷만"
축 위에 있어서 이 질문에 답하지 못하므로, `bundled_screen_hybrid`를 베이스로 세 축을 새로
만들어 각각 독립적으로 테스트했다(한 번에 하나만 바꿔서 원인을 명확히 분리):

| 축 | 구조 | 바뀐 것 |
| --- | --- | --- |
| 기준선 | `bundled_screen_hybrid` | 위반 예시 2개 + 예외 예시 1개(정적, 큐레이션 순서) |
| ① 위반 예시↑ | `bundled_screen_hybrid_violation_ratio` | 위반 예시만 2→3개(예외는 기준선과 동일) |
| ② 예외 예시↑ | `bundled_screen_hybrid_ratio` | 예외 예시만 1→2개(위반은 기준선과 동일) |
| ③ 동적 검색 | `bundled_screen_hybrid_dynamic` | 위반·예외 예시 둘 다 정적 최상위 N개 대신, 검토 중인 청크와 가장 비슷한 것을 그때그때 검색(개수는 기준선과 동일: 위반2/예외1) |

실데이터 제약: 위반 예시는 40개 룰 중 32개가 실제로 3개 이상 있어 ①을 대부분 룰에 적용할
수 있었다(AE-03만 실 후보 1개뿐이라 그대로 1개). 예외 예시는 26개 룰 중 23개가 정확히
2개까지밖에 없어(합성 금지 원칙상 보충 불가) ②는 이미 대부분 룰에서 실데이터 상한에 도달한
상태다.

조건: 파일럿 5문서(DOC-001/003/006/008/012), screen=Gemini flash-lite, confirm=Claude
Sonnet, temperature=0.0. 정확도는 review-agent 자체 채점(1차)과 eval-agent 재채점(최종
판단 기준, `valid_but_unlabeled` triage 반영) 둘 다 확인.

## 결과 — 비용

| 구조 | 콜 수 | 총 토큰 | 소요 시간 |
| --- | --- | --- | --- |
| **bundled_screen_hybrid (기준선)** | **19** | **148,706** | **127.9초** |
| bundled_screen_hybrid_violation_ratio | 22 | 190,351 | 194.2초 |
| bundled_screen_hybrid_ratio | 20 | 187,032 | 143.0초 |
| bundled_screen_hybrid_dynamic | 20 | 189,875 | 158.9초 |

세 축 모두 기준선보다 콜 수(+1~3)·토큰(+26~28%)·시간이 늘었다 — 예시를 더 주거나 유사도
계산을 추가하면 당연히 비용이 오른다.

## 결과 — 정확도

review-agent 자체 채점(rule_id+위치 겹침):

| 구조 | TP | FP | FN | recall | precision |
| --- | --- | --- | --- | --- | --- |
| **bundled_screen_hybrid (기준선)** | 1 | 2 | 5 | 16.7% | **33.3%** |
| bundled_screen_hybrid_violation_ratio | 1 | 5 | 5 | 16.7% | 16.7% |
| bundled_screen_hybrid_ratio | 1 | 5 | 5 | 16.7% | 16.7% |
| bundled_screen_hybrid_dynamic | 1 | 3 | 5 | 16.7% | 25.0% |

자체 채점만 보면 세 축 모두 기준선보다 precision이 떨어진 것처럼 보인다. 그런데
eval-agent로 재채점하면 그림이 완전히 달라진다:

| 구조 | eval-agent relaxed TP | recall(보정, TP/6) | eval-agent relaxed precision | valid_but_unlabeled |
| --- | --- | --- | --- | --- |
| bundled_screen_hybrid (기준선) | 2 | 33.3% | 100% | 1 |
| bundled_screen_hybrid_violation_ratio | 2 | 33.3% | 100% | 4 |
| bundled_screen_hybrid_ratio | 2 | 33.3% | 100% | 4 |
| bundled_screen_hybrid_dynamic | 2 | 33.3% | 100% | 2 |

**네 구조 모두 TP=2(recall 33.3%), precision 100%로 완전히 동률이다.** 자체 채점에서 봤던
"precision이 떨어진 것"은 실제 오답이 늘어난 게 아니라, 예시를 더 준 구조일수록 golden에
없는 걸 더 많이 지적했고(valid_unlabeled 1→4/4/2), 그 지적들을 eval-agent judge가 검토해
보니 전부 실제로 맞는 지적(예: MI-05 예외처리 누락, AE-01 모호한 우선순위 기준 등)이었다는
뜻이다. 즉 예시를 늘리면 "더 넓게, 더 많이 지적"하게 되지만, 이번 골든 6건을 더 맞히거나
더 틀리게 만들지는 않았다.

## 결론

- **세 축 모두 정확도 개선 효과가 없다** — eval-agent 기준으로 recall/precision이 기준선과
  완전히 동일(33.3%/100%). 비용만 26~28% 더 든다.
- **`bundled_screen_hybrid`(기준선) 그대로 유지를 추천한다** — 위반/예외 예시를 더 주거나
  동적으로 검색해도 이번 골든 6건 표본에서는 득이 없고, 콜 수·토큰만 늘어난다.
- 다만 표본이 여전히 작다(골든 6건, 문서 5개) — "예시를 늘리면 더 넓게 지적한다"는 관찰
  자체는 일관되게 나타났으므로, 골든 데이터셋이 더 커지면(예: 20문서 전체) 다시 검증할
  가치는 있다. 지금 표본에서는 결론을 뒤집을 근거가 안 된다.
- 세 축의 실데이터 상한(예외 예시는 23/26 룰이 이미 2개가 한계, 위반 예시는 AE-03만 1개
  한계)도 "더 극단적으로" 밀어붙이기 어려운 이유 중 하나 — 합성 예시를 쓰지 않는 한 이보다
  더 큰 차이를 만들 여지가 많지 않다.
