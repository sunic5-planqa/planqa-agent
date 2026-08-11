# 결정론적 재채점 + Sentence 강등 버그 수정 — 종합 결과

> 이 문서는 `results_2026-08-10_final_summary.md`(구조 실험 최종 요약)를 대체하지 않고
> **보완**한다 — 거기서 "eval-agent 재채점"이 의존했던 LLM 기반 매칭·триage가 이번에
> 결정론적으로 교체되면서 같은 predictions.json들을 다시 채점한 결과와, 그 과정에서
> 발견/수정한 review-agent 자체의 Level(위계) 보고 버그를 정리한다. 발표에서 recall/
> precision 숫자를 인용할 때는 이 문서의 "주의사항" 절을 먼저 읽을 것.

## 배경 — 무엇을, 왜 고쳤나

GitHub 이슈 #20: eval-agent의 매칭(어떤 predicted 이슈가 어떤 golden 이슈에 대응하는가)과
FP 판정(안 매칭된 predicted 이슈가 진짜 오탐인가)이 전부 **단일 LLM 호출 하나**에 의존해서,
같은 predictions.json을 다시 채점해도 매번 다른 숫자가 나올 수 있었다. 팀원을 기다리지
않고 우리가 직접 고쳐서, review-agent 구조 실험 비교에 쓸 숫자를 더 신뢰할 수 있게
만들었다. 동시에, 이 작업 중 review-agent 자체의 버그도 하나 발견해 같이 고쳤다:
`resolve_reported_level`이 모델이 "이 문단 청크 중 이 문장 하나만의 문제"라고 좁혀
보고하는 것(강등)을 무조건 거부하고 있었다 — golden의 Sentence 라벨과 구조적으로 영원히
못 맞을 수밖에 없는 버그였다.

두 작업 모두 `feature/eval-agent`/`feature/review-agent` 브랜치에만 있고 `dev`에는
올리지 않았다(review-agent는 데모2가 실서비스 최종 후보라 더 안 건드리기로 했고,
eval-agent는 우리 재채점 목적의 구조 변경을 팀 도구에 합의 없이 얹지 않기로 했다).

## 1. eval-agent — 무엇이 결정론적으로 바뀌었나

| 항목 | 이전 (LLM 기반) | 이후 (결정론적) |
| --- | --- | --- |
| 매칭 | 카테고리 버킷 안에서 LLM 한 번 호출, "대충 같은 문제면 매칭" | `rule_id` 완전일치 + `location` 유사도(숫자 토큰 겹침 우선, 없으면 문자 바이그램 Jaccard)로 점수 행렬을 만들고 `scipy.optimize.linear_sum_assignment`로 최적 이분매칭 |
| 미매칭 predicted 판정 | LLM이 4가지(`false_positive`/`new_rule_candidate`/`valid_but_unlabeled`/`human_review`)로 분류 | `rule_id`가 rulebook에 없으면 `false_positive`, 그 외는 전부 중립 `unmatched_count`(둘 다 판단하기엔 결정론적 코드로는 근거 부족 — 이게 바로 예전 4-way LLM triage가 하려던 일을 결정론적으로는 할 수 없다는 뜻) |
| Level(위계) | 맞았는지(bool)만 집계 | 신규 `level_distance`/`mean_level_distance`(부분점수) 추가 — 완전히 additive, 기존 strict/relaxed 집계 방식은 안 건드림 |

재현성 검증: 같은 predictions.json을 여러 번 재채점해도 항상 같은 숫자가 나온다(LLM 호출이
매칭/판정 경로에 전혀 없음 — judge 단계의 rubric 채점만 LLM을 씀, 그건 이번 범위 밖).

## 2. 기존 predictions.json 22개 전체 재채점 (API 비용 없음)

기존 실험에서 이미 만들어둔 predictions.json 22개를 전부 새 eval-agent로 재채점했다 —
review-agent를 다시 돌리지 않았으므로 **API 비용 발생 없음**. golden 데이터셋/rulebook은
eval-agent와 review-agent 양쪽 사본이 바이트 단위까지 동일함을 먼저 확인했다(golden
dataset 시트 131행 완전 일치).

| 파일럿 | 문서 수 | strict TP/FN/FP | relaxed TP/FN/FP | tier_accuracy | mean_level_distance | unmatched |
| --- | --- | --- | --- | --- | --- | --- |
| model_pilot/gemini | 4 | 1/4/1 | 2/3/0 | 0.50 | 1.00 | 12 |
| phase1_stage_count/cell3 | 5 | 0/6/3 | 3/3/0 | 0.00 | 1.67 | 43 |
| phase1_stage_count/direct_verdict | 5 | 1/5/2 | 3/3/0 | 0.33 | 1.00 | 22 |
| phase1_stage_count_sonnet/cell3 | 5 | 1/5/2 | 3/3/0 | 0.33 | 1.00 | 23 |
| phase1_stage_count_sonnet/direct_verdict | 5 | 1/5/1 | 2/4/0 | 0.50 | 1.00 | 96 |
| phase1_stage_count_sonnet/paragraph_verdict | 5 | 0/6/2 | 2/4/0 | 0.00 | 1.00 | 50 |
| phase2_chunking/paragraph_verdict | 4 | 0/5/2 | 2/3/0 | 0.00 | 1.00 | 9 |
| phase3_content_axis/bundled_screen_fewshot | 1 | 0/2/0 | 0/2/0 | — | — | 1 |
| **phase3_content_axis/bundled_screen_hybrid** | 2 | 0/4/3 | **3/1/0** | 0.00 | 1.00 | 0 |
| phase3_content_axis/paragraph_screen_fewshot | 5 | 0/6/1 | 1/5/0 | 0.00 | 1.00 | 8 |
| phase3_content_axis/paragraph_screen_hybrid | 4 | 0/5/2 | 2/3/0 | 0.00 | 1.00 | 12 |
| phase3_fewshot_static4/bundled_fewshot | 4 | 0/4/0 | 0/4/0 | — | — | 10 |
| phase3_fewshot_static4/bundled_verdict | 5 | 0/6/2 | 2/4/0 | 0.00 | 1.00 | 30 |
| phase3_fewshot_static4/category_fewshot | 5 | 0/6/1 | 1/5/0 | 0.00 | 2.00 | 25 |
| phase3_fewshot_static4/paragraph_verdict_sonnet | 5 | 0/6/3 | 3/3/0 | 0.00 | 1.00 | 42 |
| phase3_hybrid_subaxis/bundled_screen_hybrid_dynamic | 3 | 0/5/2 | 2/3/0 | 0.00 | 1.00 | 2 |
| phase3_hybrid_subaxis/bundled_screen_hybrid_ratio | 4 | 0/6/2 | 2/4/0 | 0.00 | 1.00 | 4 |
| phase3_hybrid_subaxis/bundled_screen_hybrid_violation_ratio | 4 | 0/5/2 | 2/3/0 | 0.00 | 1.00 | 4 |
| phase3_screen_static4/bundled_screen | 5 | 0/6/3 | 3/3/0 | 0.00 | 1.00 | 16 |
| phase3_screen_static4/bundled_screen_fewshot | 2 | 0/2/0 | 0/2/0 | — | — | 2 |
| phase3_screen_static4/paragraph_screen | 5 | 0/6/1 | 1/5/0 | 0.00 | 1.00 | 14 |
| phase3_screen_static4/paragraph_screen_fewshot | 5 | 0/6/1 | 1/5/0 | 0.00 | 1.00 | 9 |

(원본 데이터: `outputs/eval_rescored/summary.json` + 파일럿별 `outputs/eval_rescored/<pilot>/report.json`.)

### 발견 1 — tier_accuracy가 거의 전부 0.00, mean_level_distance가 거의 전부 1.00

**22개 중 20개**가 tier_accuracy 0.00 또는 매우 낮은 값이고, rule_id가 맞은 쌍의
level_distance는 거의 항상 정확히 1이다 — 즉 review-agent가 rule_id는 맞혔는데
Level을 정확히 한 단계씩 못 맞히는 경우가 압도적으로 많다. 예전 리포트에서는
`overall`(strict) 숫자가 낮게 나온 이유를 "골든셋이 불완전해서"(`valid_but_unlabeled`)로만
설명했는데, 이번에 처음으로 "Level 자체가 체계적으로 어긋난다"는 게 숫자로 드러났다 —
바로 아래 3절에서 고친 그 버그다.

### 발견 2 — relaxed 채점(rule_id만)에서는 대부분 precision이 사실상 100%

`unmatched`(중립, precision 분모·분자 어디에도 안 들어감)를 빼고 나면 relaxed FP는
거의 항상 0이다 — review-agent가 존재하지 않는 rule_id를 지어내는 경우는 없다는 뜻.
"저조한 precision"으로 보였던 것 대부분은 실제로는 "golden에 아직 라벨 안 된 것"과
"진짜 다른 문제"를 결정론적으로 구분할 수 없어 중립으로 뺀 `unmatched`였다.

## 3. review-agent — Sentence 위계 강등(demotion) 버그 수정

`document.py::resolve_reported_level`이 모델이 청크보다 **좁은** 위계를 주장하는 것
("이 문단 전체가 아니라 이 문장 하나만의 문제")을 무조건 무시하고 있었다. 근거:

- **승격**(더 넓게 주장) = 청크 밖의 것에 대한 주장 → 실제로 넓은 시야가 있어야 신뢰 가능.
- **강등**(더 좁게 주장) = 청크 **안에서** 범위를 좁히는 주장 → `original_text`가 그 청크의
  실제 인용문인 이상 그 자체로 근거가 있음. 무조건 거부는 버그였다.

golden의 AE-03/DOC-003 항목(`level=Sentence`, location은 문단급 라벨 그대로)이 이 버그의
직접적인 증거였다 — review-agent가 뭐라고 답하든 Sentence로는 절대 보고될 수 없는 구조였다.

### 수정 전/후 비교 (DOC-003 + DOC-006, `bundled_screen_hybrid`)

기존 predictions.json(수정 전 코드로 생성됨)을 재채점만 해서는 이 수정의 효과가 반영되지
않는다 — 그래서 같은 2개 문서에 대해 수정된 코드로 **새로 한 번** 실행했다(API 비용
발생, 소규모로 한정).

| | strict TP/FN/FP | relaxed TP/FN/FP | tier_accuracy | mean_level_distance |
| --- | --- | --- | --- | --- |
| 수정 전 (기존 predictions.json) | 0/4/3 | 3/1/0 | 0.00 | 1.00 |
| 수정 후 (재실행) | 1/3/2 | 3/1/0 | **0.33** | 1.33 |

수정 후 매칭 3건 중 하나(`AE-03`)가 golden `Sentence` ↔ predicted `Sentence`로 **완전
일치** — 수정 전에는 같은 자리가 `Sentence` ↔ `Paragraph`로 어긋났던 바로 그 케이스다.
나머지 두 쌍(`AE-01`/`AE-03`, golden=`Logical Unit` ↔ predicted=`Sentence`)은 오히려
반대 방향으로 어긋났다 — 강등을 허용하니 모델이 golden이 기대한 것보다 더 좁게 보고하는
새로운 종류의 불일치도 나타날 수 있다는 뜻. 2문서·3쌍짜리 표본이라 방향성 확인 이상의
결론(예: "정확히 몇 %p 개선")을 내리기엔 이르다.

## 주의사항 (반드시 같이 읽을 것)

1. **문서 커버리지가 파일럿마다 다르다** — 위 표의 "문서 수"가 1~5로 제각각이다(예:
   `bundled_screen_hybrid`는 DOC-003/006 2개만, `paragraph_screen_hybrid`는 DOC-001/003/
   006/008 4개). eval-agent가 predicted가 다룬 문서로만 golden을 좁히는 로직 때문에,
   recall 분모(golden-in-scope)가 파일럿마다 다르다 — `results_2026-08-10_final_summary.md`
   에 이미 기록된 메타 발견이며 이번 세션에서 고친 범위(이슈 #20) 밖이다. 파일럿 간
   직접 비교보다는 "같은 문서를 커버한 파일럿끼리" 비교가 안전하다.
2. **22개 predictions.json 전부 Sentence 강등 수정 이전 코드로 생성됨** — 3절의 tier_accuracy
   /mean_level_distance는 "그때 review-agent가 실제로 무엇을 보고했는가"를 정확히 반영하지만,
   "수정 후 review-agent를 다시 돌리면 얼마나 좋아지는가"는 3절의 2문서짜리 검증 실험
   외에는 아직 측정되지 않았다.
3. **표본 크기가 작다** — 파일럿 전체가 5문서/golden 위반 6건 기준이다. %p 단위 절대
   수치보다 "방향성"으로 읽을 것 (`results_2026-08-10_final_summary.md`의 기존 주의사항과
   동일).
4. **judge(rubric 채점)는 이번 결정론화 범위 밖** — 매칭·미매칭 판정만 결정론적으로
   바뀌었고, 매칭된 쌍의 root_cause_accuracy 등 rubric 점수는 여전히 LLM 호출 하나에
   의존한다.

## 다음 단계 (미해결)

- **`bundled_screen_hybrid`(현재 최종 추천 구조) 5문서 전체를 수정된 코드로 다시 실행**하면
  이번 세션에서 발견한 Level 버그 수정의 실제 효과를 5문서/6위반 기준의 깨끗한 숫자로
  확인할 수 있다 — API 비용 발생, 이번 세션에서는 2문서 검증까지만 진행하고 사용자 승인
  대기 중.
- eval-agent의 문서 스코핑 로직(주의사항 1번)은 이슈 #20과 별개 문제로, 팀에 공유할
  가치가 있는 발견이지만 이번 세션 범위 밖.
