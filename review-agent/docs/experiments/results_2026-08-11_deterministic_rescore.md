# 결정론적 재채점 + Sentence 강등 버그 수정 — 종합 결과 (v2)

> 이 문서는 `results_2026-08-10_final_summary.md`(구조 실험 최종 요약)를 대체하지 않고
> **보완**한다 — 거기서 "eval-agent 재채점"이 의존했던 LLM 기반 매칭·triage가 이번에
> 결정론적으로 교체되면서 같은 predictions.json들을 다시 채점한 결과와, 그 과정에서
> 발견/수정한 review-agent 자체의 Level(위계) 보고 버그를 정리한다. 발표에서 recall/
> precision 숫자를 인용할 때는 이 문서의 "주의사항" 절을 먼저 읽을 것.
>
> **v2 수정사항**: 초판(v1)은 predicted 이슈가 실제로 있는 문서만 "검토한 문서"로 잘못
> 집계해서(파일럿마다 문서 수가 1~5로 제각각으로 보였음) 파일럿 간 recall 분모가 달라
> 보이는 오류가 있었다. 실제로는 **22개 파일럿 전부 동일한 5개 문서**
> (DOC-001/003/006/008/012)를 대상으로 실행됐다(`outputs/experiments/<pilot>/DOC-*/`
> 디렉토리로 확인 — 0건 지적한 문서도 실제로는 검토했었다). v2는 golden을 이 5개 문서로
> 고정해서 재채점했고, 시간/토큰 비용과 페이즈별 실험 설명, golden 6건 커버리지 매트릭스,
> "Sentence 강등 크레딧" 한시적 재채점을 추가했다.

## 배경 — 무엇을, 왜 고쳤나

GitHub 이슈 #20: eval-agent의 매칭과 FP 판정이 전부 **단일 LLM 호출 하나**에 의존해서,
같은 predictions.json을 다시 채점해도 매번 다른 숫자가 나올 수 있었다. 우리가 직접 고쳐서
review-agent 구조 실험 비교에 쓸 숫자를 더 신뢰할 수 있게 만들었다. 동시에 review-agent
자체의 버그도 하나 발견해 같이 고쳤다: `resolve_reported_level`이 모델이 "이 문단 청크 중
이 문장 하나만의 문제"라고 좁혀 보고하는 것(강등)을 무조건 거부하고 있었다 — golden의
Sentence 라벨과 구조적으로 영원히 못 맞을 수밖에 없는 버그였다.

두 작업 모두 `feature/eval-agent`/`feature/review-agent` 브랜치에만 있고 `dev`에는
올리지 않았다.

## eval-agent — 무엇이 결정론적으로 바뀌었나

| 항목 | 이전 (LLM 기반) | 이후 (결정론적) |
| --- | --- | --- |
| 매칭 | 카테고리 버킷 안에서 LLM 한 번 호출, "대충 같은 문제면 매칭" | `rule_id` 완전일치 + `location` 유사도(숫자 토큰 겹침 우선, 없으면 문자 바이그램 Jaccard)로 점수 행렬을 만들고 `scipy.optimize.linear_sum_assignment`로 최적 이분매칭 |
| 미매칭 predicted 판정 | LLM이 4가지로 분류(`false_positive`/`new_rule_candidate`/`valid_but_unlabeled`/`human_review`) | `rule_id`가 rulebook에 없으면 `false_positive`, 그 외는 전부 중립 `unmatched_count` |
| Level(위계) | 맞았는지(bool)만 집계 | `level_distance`/`mean_level_distance`(부분점수) 추가 — additive |

재현성: 같은 predictions.json을 여러 번 재채점해도 항상 같은 숫자가 나온다(매칭/판정 경로에
LLM 호출이 전혀 없음 — judge 단계의 rubric 채점만 LLM 사용, 이번 범위 밖).

## 실험 설계 총정리

전체 파일럿은 **동일한 5개 문서**(DOC-001/003/006/008/012), **동일한 golden 6건**
(아래 표)을 기준으로 비교된다. 페이즈는 시간순으로 ①판정 단계 수 → ②청킹 방식 →
③세분화×콘텐츠 → hybrid 세부 축, 매 단계마다 이전 단계의 승자를 고정하고 다음 축만 바꿨다.

| golden 항목 | 문서 | rule_id | Level | 설명(요약) |
| --- | --- | --- | --- | --- |
| 1 | DOC-001 | LG-05 | Document | 3장 KPI vs 4장 기술 제약 — 관계형(문서 전체 시야 필요) |
| 2 | DOC-003 | AE-03 | Sentence | "4. 상품 컨디션 등급 기준" 표 상단 A/B/C 서술 |
| 3 | DOC-003 | AE-03 | Sentence | 같은 섹션의 표 하단 서술 (위와 다른 문장) |
| 4 | DOC-006 | AE-01 | Logical Unit | 2-1~2-4 전반 |
| 5 | DOC-006 | AE-03 | Logical Unit | 2-1~2-4 전반 (AE-01과 같은 위치, 다른 룰) |
| 6 | DOC-012 | GA-01 | Document | 2장 KPI vs 6장 마일스톤 — 관계형 |

**모든 recall은 이 6건이 분모다.** 표에 나오는 구조별 "판정 단계 수"·"청킹 방식"·"세분화"·
"콘텐츠" 용어의 정의는 `results_2026-08-10_final_summary.md` 및 각 `results_2026-08-10_
phase*.md`에 이미 정리돼 있다 — 아래에서는 페이즈별로 다시 표로 묶어 간단히 반복한다.

## 페이즈별 결과

### model_pilot — 초기 단일모델 파일럿 (Gemini만, 본 ablation 이전)

정식 ①②③ 실험을 설계하기 전, `gemini_lite` 기본 프로필(제안5 baseline, screen/confirm
둘 다 Gemini flash-lite)로 돌려본 최초 파일럿.

| 구조 | strict TP/FN/FP | recall | precision | relaxed recall | tier_accuracy | mean_level_distance | unmatched | Sentence-credit TP(recall) | 콜 수 | 토큰 | 시간 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gemini_lite (baseline, Gemini+Gemini) | 1/5/1 | 16.7% | 50.0% | 33.3% | 0.50 | 1.00 | 12 | 1 (16.7%) | 41 | 106,530 | 120.7s |

### Phase 1 — 판정 단계 수 (1단계 vs 2단계), Gemini+Gemini

세분화(콜분리×룰전부)와 청킹(위계형)을 고정하고 판정 단계 수만 비교.

| 구조 | strict TP/FN/FP | recall | precision | relaxed recall | tier_accuracy | mean_level_distance | unmatched | Sentence-credit TP(recall) | 콜 수 | 토큰 | 시간 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cell3 (2단계: 스크리닝→정밀판정) | 0/6/3 | 0.0% | 0.0% | 50.0% | 0.00 | 1.67 | 43 | 1 (16.7%) | 237 | 538,788 | 203.8s |
| direct_verdict (1단계) | 1/5/2 | 16.7% | 33.3% | 50.0% | 0.33 | 1.00 | 22 | 1 (16.7%) | 135 | 301,598 | 159.9s |

**당시 결론**(1단계 승)은 Gemini+Gemini 조건에서만 성립 — 아래 Sonnet 재검증에서 뒤집힌다.

### Phase 1 재검증 — confirm=Sonnet으로 바꾸면 결론이 뒤집힘

Sonnet은 Gemini보다 훨씬 철저해서 스크리닝 없이 혼자 판정하면 과다지적이 심해진다(아래
`unmatched` 96건 참고 — 대부분 rulebook엔 있는 rule_id를 댄 "혹시 몰라 지적"으로 보임).

| 구조 | strict TP/FN/FP | recall | precision | relaxed recall | tier_accuracy | mean_level_distance | unmatched | Sentence-credit TP(recall) | 콜 수 | 토큰 | 시간 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cell3 (2단계, screen=Gemini/confirm=Sonnet) | 1/5/2 | 16.7% | 33.3% | 50.0% | 0.33 | 1.00 | 23 | 1 (16.7%) | 178 | 481,182 | 559.1s |
| direct_verdict (1단계, confirm=Sonnet) | 1/5/1 | 16.7% | 50.0% | 33.3% | 0.50 | 1.00 | 96 | 1 (16.7%) | 148 | 167,143 | 476.1s |
| paragraph_verdict (1단계 문단형, confirm=Sonnet) | 0/6/2 | 0.0% | 0.0% | 33.3% | 0.00 | 1.00 | 50 | 1 (16.7%) | 56 | 60,311 | 171.2s |

**결정론적 재채점으로 다시 봐도** direct_verdict의 unmatched=96이 압도적으로 커서(관대한
1단계 판정이 rule_id 자체는 존재하는 지적을 대량 생성) → **2단계(cell3) 구조가 비용
대비 더 안전**하다는 원래 결론이 유지된다. relaxed recall/precision만 보면 비슷해
보이지만 unmatched 규모 차이가 결정적이다.

### Phase 2 — 청킹 방식 (위계형 vs 문단형), 1단계 direct_verdict 기반

| 구조 | strict TP/FN/FP | recall | precision | relaxed recall | tier_accuracy | mean_level_distance | unmatched | Sentence-credit TP(recall) | 콜 수 | 토큰 | 시간 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| direct_verdict (위계형: 문서/논리단위/문단/문장 4단계 청킹) | 1/5/1 | 16.7% | 50.0% | 33.3% | 0.50 | 1.00 | 96 | 1 (16.7%) | 148 | 167,143 | 476.1s |
| paragraph_verdict (문단형: 문단 단위만) | 0/6/2 | 0.0% | 0.0% | 33.3% | 0.00 | 1.00 | 9 | 1 (16.7%) | 53 | 107,712 | 73.2s |

**흥미로운 재발견**: 결정론적 채점에서는 recall/precision이 거의 동률로 보이지만,
**unmatched가 96 vs 9로 10배 이상 차이난다** — 위계형(direct_verdict)이 문단형보다 훨씬
많은 "판단하기 애매한" 지적을 쏟아낸다는 뜻. 시간도 476초 vs 73초로 6배 이상 차이난다.
원래 결론(문단형 채택)은 정확도 동률 + 압도적으로 낮은 비용/노이즈로 **더 강하게** 재확인된다.

### Phase 3 — 세분화×콘텐츠 정적 4콤보 (screen=Gemini/confirm=Sonnet, 문단형)

| 구조 | strict TP/FN/FP | recall | precision | relaxed recall | tier_accuracy | mean_level_distance | unmatched | Sentence-credit TP(recall) | 콜 수 | 토큰 | 시간 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| paragraph_screen (콜분리 × 룰만) | 0/6/1 | 0.0% | 0.0% | 16.7% | 0.00 | 1.00 | 14 | 1 (16.7%) | 77 | 216,209 | 403.9s |
| bundled_screen (콜통합 × 룰만) | 0/6/3 | 0.0% | 0.0% | 50.0% | 0.00 | 1.00 | 16 | 1 (16.7%) | 26 | 112,349 | 263.9s |
| paragraph_screen_fewshot (콜분리 × 퓨샷만) | 0/6/1 | 0.0% | 0.0% | 16.7% | 0.00 | 1.00 | 9 | 0 (0.0%) | 78 | 357,358 | 280.5s |
| bundled_screen_fewshot (콜통합 × 퓨샷만) | 0/6/0 | 0.0% | — | 0.0% | — | — | 2 | 0 (0.0%) | 19 | 105,352 | 127.1s |

콜통합(bundled)이 콜분리(paragraph)보다 relaxed recall이 항상 같거나 높고, 콜 수/토큰은
훨씬 적다 — "룰만" 콘텐츠에서는 콜통합이 명확히 유리.

### Phase 3 — 콘텐츠 축 3방향 최종 비교 (룰만 vs 퓨샷만 vs 룰+퓨샷)

| 구조 | strict TP/FN/FP | recall | precision | relaxed recall | tier_accuracy | mean_level_distance | unmatched | Sentence-credit TP(recall) | 콜 수 | 토큰 | 시간 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| paragraph_screen (콜분리, 룰만) | 0/6/1 | 0.0% | 0.0% | 16.7% | 0.00 | 1.00 | 14 | 1 (16.7%) | 77 | 216,209 | 403.9s |
| bundled_screen (콜통합, 룰만) | 0/6/3 | 0.0% | 0.0% | 50.0% | 0.00 | 1.00 | 16 | 1 (16.7%) | 26 | 112,349 | 263.9s |
| paragraph_screen_fewshot (콜분리, 퓨샷만) | 0/6/1 | 0.0% | 0.0% | 16.7% | 0.00 | 1.00 | 8 | 0 (0.0%) | 72 | 320,052 | 250.1s |
| bundled_screen_fewshot (콜통합, 퓨샷만) | 0/6/0 | 0.0% | — | 0.0% | — | — | 1 | 0 (0.0%) | 20 | 126,127 | 122.9s |
| paragraph_screen_hybrid (콜분리, 룰+퓨샷) | 0/6/2 | 0.0% | 0.0% | 33.3% | 0.00 | 1.00 | 12 | 1 (16.7%) | 68 | 292,100 | 197.1s |
| **bundled_screen_hybrid (콜통합, 룰+퓨샷)** | 0/6/3 | 0.0% | 0.0% | **50.0%** | 0.00 | 1.00 | 0 | 1 (16.7%) | **19** | **148,706** | 127.9s |

**"퓨샷만으로 충분하다" 가설 기각 재확인**: `*_fewshot`(퓨샷만) 두 구조는 relaxed
recall도 0%다 — 룰텍스트 없이 예시만 주면 모델이 패턴을 실제로 적용하지 못한다.
**`bundled_screen_hybrid`가 relaxed recall 50%(6건 중 3건 rule_id 일치)로 이 그룹에서
최고이면서 콜 수(19)·토큰(148,706)도 최저, unmatched도 0건**(=애매한 지적이 하나도
없었다) — 원래 결론("bundled_screen_hybrid 채택")이 결정론적 채점에서도 유지된다.

주의: strict recall/precision은 이 그룹 전부 0%다 — 3개의 rule_id 일치 쌍
(DOC-006 AE-01/AE-03, DOC-003 AE-03) 전부 golden보다 한 단계 좁은 Level(Paragraph)로
보고돼서 strict 채점에서 전부 탈락했다. 바로 이 현상이 이번에 고친 Sentence 강등
버그다 — 아래 "Sentence 강등 크레딧" 절 참고.

### Phase 3 — hybrid 세부 축 3종 (bundled_screen_hybrid를 기준으로 퓨샷 구성만 변경)

| 구조 | strict TP/FN/FP | recall | precision | relaxed recall | tier_accuracy | mean_level_distance | unmatched | Sentence-credit TP(recall) | 콜 수 | 토큰 | 시간 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 기준선 (위반 2 + 예외 1, 정적) | 0/6/3 | 0.0% | 0.0% | 50.0% | 0.00 | 1.00 | 0 | 1 (16.7%) | 19 | 148,706 | 127.9s |
| 위반 예시 2→3개 | 0/6/2 | 0.0% | 0.0% | 33.3% | 0.00 | 1.00 | 4 | 1 (16.7%) | 22 | 190,351 | 194.2s |
| 예외 예시 1→2개 | 0/6/2 | 0.0% | 0.0% | 33.3% | 0.00 | 1.00 | 4 | 1 (16.7%) | 20 | 187,032 | 143.0s |
| 동적 검색 | 0/6/2 | 0.0% | 0.0% | 33.3% | 0.00 | 1.00 | 2 | 1 (16.7%) | 20 | 189,875 | 158.9s |

**결정론적 채점으로도 결론 불변**: 세 축 모두 기준선보다 relaxed recall이 낮거나
같고(33.3% < 50.0%), 비용은 더 든다 — **기준선(`bundled_screen_hybrid`) 그대로가 여전히
최종 추천**.

## golden 6건 커버리지 — 어떤 구조도 못 잡은 것과 항상 어긋나는 것

22개 파일럿 전체를 놓고 golden 6건 각각을 누가 어떻게 맞혔는지 정리(원본:
`outputs/eval_rescored_v2/coverage.json`):

- **DOC-012 GA-01(Document)과 DOC-003의 두 번째 AE-03(Sentence, "표 하단 서술")은
  22개 파일럿 전부 단 한 번도 rule_id조차 매칭시키지 못했다** — 구조 선택과 무관한,
  아직 아무도 못 푼 case.
- **DOC-003의 첫 번째 AE-03(Sentence)**은 대부분의 파일럿이 rule_id는 맞혔지만, **문단형
  청킹 계열(`bundled_screen_hybrid`, `paragraph_screen_hybrid`, `bundled_verdict` 등)은
  전부 Paragraph로 보고**했고, **위계형 청킹 계열(`direct_verdict`, `cell3`,
  `paragraph_verdict`의 Gemini/Sonnet 여러 버전)은 절반 정도가 정확히 Sentence로 맞혔다.**
  → **위계형 청킹은 애초에 Sentence 단위 청크를 따로 주기 때문에 강등 없이도 맞힐 수
  있다.** 이번에 고친 강등 버그는 **문단형 청킹 계열에만 해당하는 문제**였다 — 문단형이
  ②에서 비용/노이즈 이유로 채택된 구조이므로, 이 버그는 채택된 구조에 정확히 영향을
  주고 있었다는 뜻.
- **DOC-006의 AE-01/AE-03(둘 다 Logical Unit)**은 문단형 계열이 전부 Paragraph(한 단계
  좁음), 위계형 계열이 전부 Sentence(한 단계 더 좁음)로 보고했다 — **Logical Unit으로
  정확히 보고한 파일럿은 하나도 없다.** 문단형은 애초에 Logical Unit 청크가 없고,
  위계형은 청크 자체가 이미 그보다 잘게 쪼개져 있어서 "이 문단/문장이 아니라 논리단위
  전체의 문제"라고 승격 보고할 유인이 약했던 것으로 보인다.
- **DOC-001 LG-05(Document, 관계형)**은 4개 파일럿만 rule_id를 맞혔고, 그나마도
  Logical Unit/Paragraph로 보고 — `bundled_screen_hybrid` 계열(GA/LG/LF를 문서 tier로
  라우팅하도록 고쳐진 최신 구조)은 이 항목을 아예 하나도 못 잡았다(위 표의 FN에 포함).
  최신 구조가 예전 구조보다 이 특정 항목에서는 오히려 후퇴했다는 뜻 — 표본이 1건뿐이라
  일반화하기엔 이르지만 기록해 둘 가치가 있다.

## Sentence 강등 크레딧 — 한시적 재채점 (API 비용 없음)

**API 호출을 추가로 대량 발생시키기 어려운 제약** 하에서, "만약 이 22개 predictions.json이
전부 Sentence 강등 수정 이후의 review-agent로 만들어졌다면 얼마나 달라졌을까"를 근사하기
위해 **한시적 채점 규칙**을 하나 추가해 재채점했다:

> rule_id가 일치하는 매칭 쌍 중 **golden Level이 Sentence이고 predicted Level이
> Paragraph**인 경우만 `level_match=True`로 간주(다른 방향의 불일치는 전혀 건드리지 않음).

이건 **eval-agent의 실제 채점 로직에 반영된 변경이 아니다** — `verifier.py`/`aggregator.py`는
그대로이고, 위 규칙은 보고서용 별도 재계산 스크립트(`outputs/eval_rescored_v2/*__sentence_credit/`)
로만 적용했다. 실제 검증(review-agent를 수정된 코드로 다시 돌려서 확인)은 아래 "실측
검증" 절 참고.

| 파일럿 | strict TP (원본) | strict TP (Sentence 크레딧) | tier_accuracy (크레딧) |
| --- | --- | --- | --- |
| model_pilot/gemini | 1 | 1 (변화없음 — 이미 Sentence로 맞혔던 항목) | 0.50 |
| phase1_stage_count/cell3 | 0 | 1 | 0.33 |
| phase1_stage_count/direct_verdict | 1 | 1 | 0.33 |
| phase1_stage_count_sonnet/* (3개) | 0~1 | 1 (전부) | 0.33~0.50 |
| phase2_chunking/paragraph_verdict | 0 | 1 | 0.50 |
| phase3_screen_static4/* (룰만·룰+퓨샷 4개) | 0 | 1 (fewshot 제외) | 0.33~1.00 |
| **phase3_content_axis/bundled_screen_hybrid** | 0 | **1** | **0.33** |
| phase3_fewshot_static4/*fewshot* | 0 | 0 (fewshot 계열은 애초에 이 항목 자체를 못 잡음) | — |
| phase3_hybrid_subaxis/* (3개) | 0 | 1 (전부) | 0.50 |

크레딧을 적용해도 strict TP는 최대 1(=6건 중 1건)까지만 올라간다 — DOC-003 두 번째
AE-03과 DOC-006 두 건은 애초에 golden Level이 Sentence가 아니거나(Logical Unit)
아예 매칭이 안 됐기 때문에 이 규칙의 대상이 아니다. **즉 이번 수정이 과거 predictions.json
전체에 소급 적용됐다고 가정해도, 그 효과는 "6건 중 최대 1건"으로 제한적**이다 — 이건
버그 수정이 무의미하다는 뜻이 아니라, **애초에 golden 6건 중 문단형 청킹 계열이 강등으로
도움받을 수 있는 항목이 1건뿐이었다**는 뜻이다(나머지는 아예 못 잡거나, Logical Unit
방향으로 어긋나서 이 수정과 무관하다).

## 실측 검증 — DOC-003/DOC-006만 수정된 코드로 재실행 (API 비용 소액 발생)

한시적 크레딧이 아니라 실제로 수정된 코드를 돌려서 확인(사용자 승인 받음, 49초):

| | strict TP/FN/FP | relaxed TP/FN/FP | tier_accuracy |
| --- | --- | --- | --- |
| 수정 전 (기존 predictions.json, 이 2문서 범위) | 0/4/3 | 3/1/0 | 0.00 |
| 수정 후 (재실행, 같은 2문서) | 1/3/2 | 3/1/0 | **0.33** |

수정 후 매칭 3건 중 `AE-03`(DOC-003, 표 상단) 하나가 golden `Sentence` ↔ predicted
`Sentence`로 **완전 일치** — 위 크레딧 분석이 예측한 것과 정확히 같은 항목이 실제로도
고쳐졌다. 나머지 두 쌍은 golden `Logical Unit` ↔ predicted `Sentence`로 오히려 반대
방향(모델이 더 좁게 보고)으로 어긋났다 — 강등을 허용하면 golden이 기대한 것보다 더 좁게
보고하는 새로운 종류의 불일치도 나타날 수 있음을 보여준다. 2문서·3쌍 표본이라 방향성
확인 수준.

## 결론 재확인

- **`bundled_screen_hybrid` 채택 추천은 유지된다** — relaxed recall(50%, 이 그룹 최고),
  콜 수·토큰(19/148,706, 이 그룹 최저), unmatched 0건(애매한 지적 없음)이 근거. strict
  recall이 0%인 건 이 구조만의 문제가 아니라 **문단형 청킹 계열 전체에 걸친 Level
  보고 버그**였고, 이번 세션에서 원인을 찾아 고쳤다.
- ①(2단계)·②(문단형) 단계의 결론도 결정론적 재채점에서 더 강하게 재확인됐다 —
  특히 unmatched 개수 차이(위계형 96건 vs 문단형 9건)가 예전 리포트에는 없던,
  이번에 새로 드러난 근거다.
- Sentence 강등 수정의 정량적 효과는 "golden 6건 중 최대 1건"으로 제한적이지만,
  DOC-003 AE-03이 실제로 Sentence로 정확히 보고되는 것을 실측으로 확인했다 — 방향은
  맞고, 전체 정확도에 미치는 영향의 크기는 표본이 작아 아직 불확실하다.

## 주의사항 (반드시 같이 읽을 것)

1. **golden 6건은 매우 작은 표본이다** — 1~2건의 TP/FP 변화가 %p를 크게 흔든다.
   %단위 절대 수치보다 방향성 근거로 읽을 것.
2. **22개 predictions.json 전부 Sentence 강등 수정 이전 코드로 생성됨** — 표의
   tier_accuracy/mean_level_distance/Sentence-credit 열은 "그때 review-agent가 실제로
   무엇을 보고했는가"의 정확한 기록이지, 수정된 코드의 실측 결과가 아니다(단, "실측 검증"
   절의 DOC-003/006 재실행분은 실측이다).
3. **Sentence 강등 크레딧은 임시 분석 도구다** — eval-agent의 실제 채점 로직에는
   반영되지 않았고, 이 문서의 재채점 스크립트에서만 한시적으로 적용했다.
4. **judge(rubric 채점)는 이번 결정론화 범위 밖** — 매칭·미매칭 판정만 결정론적으로
   바뀌었고, 매칭된 쌍의 rubric 점수는 여전히 LLM 호출 하나에 의존한다.
5. **모델/백엔드 정책이 페이즈마다 다르다** — model_pilot/phase1(Gemini+Gemini) →
   phase1 재검증부터(confirm=Sonnet) 정책이 바뀌었다. 페이즈를 넘나드는 직접 비교(예:
   model_pilot vs phase3)는 모델 차이도 같이 비교하는 것이니 주의.

## 다음 단계 (미해결)

- `bundled_screen_hybrid` 5문서 전체를 수정된 코드로 재실행하면 이번 수정의 효과를
  6건 전체 기준 깨끗한 숫자로 확인 가능 — API 비용 발생, 현재는 2문서 검증까지만 진행.
- DOC-012 GA-01, DOC-003 두 번째 AE-03(22개 파일럿 전부 미검출)은 구조와 무관한 별도
  원인 분석이 필요해 보인다 — 이번 세션 범위 밖.
- eval-agent의 문서 스코핑 로직(0건 지적과 미검토를 구분 못 하는 문제, v1에서 발견)은
  이슈 #20과 별개, 팀 공유 가치는 있으나 이번 세션 범위 밖. v2는 golden 문서 목록을
  수동으로 고정해서 우회했다.
