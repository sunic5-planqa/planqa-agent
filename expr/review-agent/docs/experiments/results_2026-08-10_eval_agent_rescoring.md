# 실험 결과 — 6개 구조를 팀원 최신 eval-agent로 재채점

## 배경

지금까지의 recall/precision은 전부 review-agent 자체 채점(`scoring.py`, rule_id 완전일치 +
위치 부분포함)이었다. 팀원이 origin/main에 올린 최신 eval-agent(LLM 매칭 + `valid_but_
unlabeled` triage, `overall_relaxed`/`tier_accuracy` 분리)로 같은 6개 구조의
`predictions.json`을 재채점했다. screen=Gemini, confirm=Sonnet, 파일럿 5문서, eval-agent
자체는 Gemini flash-lite(기본값, 가장 가벼운 옵션) 사용.

## 결과

| 구조 | 콘텐츠 | review-agent 자체채점 precision | eval-agent strict | eval-agent relaxed precision | eval-agent relaxed recall(보정 전) | **recall(보정, /6)** | valid_but_unlabeled |
| --- | --- | --- | --- | --- | --- | --- | --- |
| paragraph_screen | 룰만 | 6.7% | 0% | **100%** | 16.7% | 16.7% | 14 |
| bundled_screen | 룰만 | 5.3% | 0% | **100%** | 33.3% | 33.3% | 17 |
| paragraph_screen_fewshot | 퓨샷만 | 0% | 0% | 50% | 16.7% | 16.7% | 7 |
| bundled_screen_fewshot | 퓨샷만 | 0% | 0% | 0% | 0% | 0% | 0 |
| paragraph_screen_hybrid | 룰+퓨샷 | 7.1% | 0% | **100%** | ~~40%~~ | 33.3% | 12 |
| bundled_screen_hybrid | 룰+퓨샷 | 33.3% | 0% | **100%** | ~~50%~~ | 33.3% | 1 |

## 중요 발견 1 — review-agent 자체채점은 precision을 심하게 과소평가하고 있었다

`valid_but_unlabeled`(golden에 안 라벨링됐지만 실제로는 맞는 지적) 건수가 구조당 최대
17건. 예를 들어 `paragraph_screen`(룰만)은 review-agent 자체채점으로는 FP 14건이었는데,
eval-agent LLM judge가 그 14건을 전부 읽고 "실제로 맞는 지적인데 golden이 안 적어놓은
것"이라고 판단해서 **relaxed precision이 6.7% → 100%로 뛰었다.** 판단 근거를 직접 읽어봐도
전부 구체적이고 타당하다(예: "PDP라는 약어를 정의 없이 최초 사용 → 용어 일관성 위반이
맞음", "검색 결과 0건일 때 처리가 없음 → 정보 누락이 맞음"). 이번 세션 내내 관찰했던
"Sonnet이 Gemini보다 과다지적한다"는 현상의 상당 부분이, 실제로는 **틀린 지적이 아니라
golden 데이터셋 자체가 완전하지 않아서 생긴 것**이었다는 근거가 확보됐다.

## 중요 발견 2 — eval-agent의 recall 원본 숫자는 구조마다 비교 기준이 다르다(보정 필요)

eval-agent의 `run_full_evaluation`은 "predicted가 다룬 문서만 golden으로 채점"하는 로직이
있다(팀원이 20문서 벤치마크 중 일부만 돌렸을 때 안 건드린 문서가 자동으로 미스 처리되는
버그를 막으려고 넣은 것). 그런데 **우리 파일럿은 5문서를 항상 다 검토하지만, 구조에 따라
특정 문서에서 "찾아낸 게 0건"이면 그 문서 자체가 predicted에서 빠져서 golden 채점 대상에서
통째로 제외된다** — "검토했는데 못 찾음"과 "검토 안 함"을 eval-agent가 구분하지 못하는
경우다.

- `bundled_screen_fewshot`은 DOC-003만 predicted에 있어서 golden도 DOC-003(2건)만 채점됨
  (원래 6건 중 4건 제외).
- `paragraph_screen_hybrid`는 DOC-012가 빠져서 golden 5건만 채점(1건 제외).
- `bundled_screen_hybrid`는 DOC-001·DOC-012가 빠져서 golden 4건만 채점(2건 제외).

**보정**: TP는 이 문제와 무관(실제 매칭 건수 그대로)하므로, recall을 전체 golden 6건
기준으로 다시 계산(TP/6)하면 `paragraph_screen_hybrid`·`bundled_screen_hybrid` 둘 다
33.3%로 낮아진다(원본은 40%/50%로 과장돼 있었음). **precision은 이 문제와 무관**(분모가
predicted 쪽 기준이라 영향 없음) — 100%는 그대로 유효하다.

## 결론

- **precision 기준으로는 `bundled_screen_hybrid`가 압도적**(자체채점 33.3% → eval-agent
  100%) — 여전히 최고 후보.
- **recall을 공정하게(6건 기준) 비교하면 `bundled_screen`·`paragraph_screen_hybrid`·
  `bundled_screen_hybrid`가 33.3%로 동률**이다. precision까지 같이 보면 `bundled_screen_
  hybrid`(precision 100%, 콜 수 19회로 최저비용)가 종합 1위.
- eval-agent의 문서 스코핑 로직은 "일부 문서만 리뷰했을 때"를 가정한 것이라, "5문서를 다
  리뷰했지만 일부에서 0건 지적"인 우리 상황에는 그대로 안 맞는다 — 팀원에게 참고로 공유할
  만한 내용.
