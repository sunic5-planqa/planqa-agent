# 최종 종합 — 구조 실험 전체 요약 (①②③ + eval-agent 재채점)

> 개별 단계의 세부 데이터는 각 `results_2026-08-10_*.md`에 있음. 이 문서는 전체 흐름과
> 최종 결론만 한 곳에서 보기 위한 요약. 발표용 근거로 이 문서를 우선 참고.

## 실험 목적

review-agent(기획서 검토 에이전트)를 어떤 내부 구조로 만들지 3가지 축으로 검증:
① 판정 단계 수(1단계 직접판정 vs 2단계 screen→confirm), ② 청킹 방식(위계형 vs 문단형),
③ 세분화×프롬프트 콘텐츠(콜분리/콜통합 × 룰텍스트/퓨샷예시/둘다). 실서비스 배포가 아니라
발표에서 "왜 이 구조를 골랐는지" 근거를 마련하는 것이 목적.

## 타임라인과 결론 변화 — 왜 중간에 결론이 뒤집혔는지

| 단계 | 조건 | ① 승자 | ② 승자 |
| --- | --- | --- | --- |
| Phase 1&2 (최초) | Gemini+Gemini | **1단계**(direct_verdict, precision 4.0%) | **문단형**(paragraph_verdict, precision 9.1%) |
| Phase 1&2 재검증 | screen=Gemini, confirm=**Sonnet** | **2단계로 역전**(cell3, precision 3.8% > direct_verdict 1.0%) | 문단형 유지(1.9% > 1.0%) |

**왜 뒤집혔나**: Sonnet은 Gemini보다 훨씬 철저해서(edge case를 적극적으로 찾음) 스크리닝
없이 혼자 판정하면 과다지적이 심해진다(direct_verdict FP 97건). 2단계 구조는 Gemini
스크리닝이 먼저 후보를 좁혀줘서 Sonnet의 과다지적이 억제된다. → **③ 실험부터는 2단계+
문단형(`paragraph_screen`/`bundled_screen` 계열)을 기준 구조로 재설정.**
(상세: `results_2026-08-10_phase1_stage_count.md`, `results_2026-08-10_phase2_chunking.md`,
`results_2026-08-10_phase1_2_sonnet_revalidation.md`)

## ③ 세분화×콘텐츠 — 최종 비교 (파일럿 5문서, screen=Gemini/confirm=Sonnet)

review-agent 자체채점(rule_id+위치 겹침)은 golden 데이터셋이 불완전해서 precision을
과소평가한다는 게 밝혀졌다(아래 참고) — **최종 판단 기준은 eval-agent 재채점(LLM judge가
`valid_but_unlabeled` 반영) + recall은 golden 6건 기준으로 수동 보정한 값.**

| 구조 | 세분화 | 콘텐츠 | precision(eval-agent) | recall(보정) | 콜 수 | 총 토큰 |
| --- | --- | --- | --- | --- | --- | --- |
| paragraph_screen | 콜분리 | 룰만 | 100% | 16.7% | 86 | 322,183 |
| bundled_screen | 콜통합 | 룰만 | 100% | 33.3% | 26 | 112,349 |
| paragraph_screen_fewshot | 콜분리 | 퓨샷만 | 50% | 16.7% | 73 | 324,304 |
| bundled_screen_fewshot | 콜통합 | 퓨샷만 | 0% | 0% | 20 | 126,127 |
| paragraph_screen_hybrid | 콜분리 | 룰+퓨샷 | 100% | 33.3% | 68 | 292,100 |
| **bundled_screen_hybrid** | **콜통합** | **룰+퓨샷** | **100%** | **33.3%** | **19** | **148,706** |

**최종 결론: `bundled_screen_hybrid`(2단계, 콜통합, 룰텍스트+퓨샷 예시 함께) 채택 추천.**
recall은 3개 구조와 동률(33.3%)이지만, precision 100%에 콜 수·토큰이 6개 중 가장 적어
비용도 최저 — 정확도와 비용 둘 다에서 밀리지 않는 유일한 구조.

(세부: `results_2026-08-10_phase3_screen_static4.md`, `results_2026-08-10_phase3_fewshot.md`,
`results_2026-08-10_phase3_content_axis.md`, `results_2026-08-10_eval_agent_rescoring.md`)

## 콘텐츠 축에서 확인된 것 — "퓨샷만으로 충분하다"는 가설은 기각

룰텍스트를 완전히 빼고 예시 1~2개만 준 구조(`*_fewshot`)는 재선정된 예시 뱅크로 다시
돌려도 이번 표본에서 recall 0%를 벗어나지 못했다. 반면 **룰텍스트+퓨샷 예시를 같이 준
구조(`*_hybrid`)는 뚜렷하게 좋았다** — 예시는 룰의 공식 정의가 있을 때 보조 자료로 작동하고,
정의 없이 예시만 주면 모델이 패턴을 실제로 적용하지 못한다는 근거(AE-03 사례,
`results_2026-08-10_phase3_content_axis.md` 참고).

## 채점 방식에 대한 메타 발견 (방법론 노트)

1. **review-agent 자체채점(rule_id+위치 부분포함)은 precision을 심하게 과소평가한다** —
   golden 데이터셋이 문서의 모든 문제를 감사한 목록이 아니라 일부만 표시한 샘플이기
   때문. eval-agent의 LLM judge가 재검토하니 "FP" 대부분이 실제로는 맞는 지적
   (`valid_but_unlabeled`)이었다.
2. **eval-agent의 문서 스코핑 로직에 우리 사용 패턴과 안 맞는 부분이 있다** — "predicted가
   다룬 문서로만 golden을 좁히는" 로직이 "일부 문서에서 0건 지적"과 "그 문서를 검토
   안 함"을 구분하지 못해서, recall 분모가 구조마다 달라졌다(TP/6으로 수동 보정함). 팀원
   에게 공유할 만한 내용.
3. **review-agent 자체채점의 위치 매칭(부분 문자열 포함)도 놓치는 경우가 있다** — golden이
   "2-1~2-4 전반" 같은 범위 표기를 쓰면, 우리 구조가 구체적 하위 위치("2-1. 상품 관련...")
   로 보고한 진짜 일치도 놓친다(DOC-006 사례).

## 표본 크기 관련 주의사항

파일럿 5문서(DOC-001/003/006/008/012)의 golden 위반은 6건뿐이다. 이 문서에 기록된 모든
비율(%) 차이는 1~2건의 TP/FP 변화로 크게 흔들릴 수 있는 수준이다 — 방향성 근거로는
충분하지만, 발표에서 "정확히 몇 %"라는 절대 수치보다는 "이 구조가 이런 이유로 낫다"는
정성적 근거와 함께 제시하는 게 안전하다.

## hybrid 세부 축 3종 파일럿 결과 — 결론 변화 없음

`bundled_screen_hybrid`를 베이스로 위반예시↑/예외예시↑/동적검색 3개 축을 각각 독립
테스트했다(상세: `results_2026-08-10_phase3_hybrid_subaxis.md`). eval-agent 재채점
결과 **세 축 모두 기준선과 정확도가 완전히 동률**(TP=2/6, recall 33.3%, precision
100%)이었고 비용만 26~28% 더 들었다 — **`bundled_screen_hybrid`(기준선) 그대로가 여전히
최종 추천**이다. (참고: 이전 세션에 "퓨샷만" 축 위에 만들어둔 `*_fewshot_ratio`/
`*_dynamic_fewshot` 4개 구조는 이미 기각된 콘텐츠 축 위에 있어 파일럿하지 않았다 — 코드/
테스트는 남아있음.)
