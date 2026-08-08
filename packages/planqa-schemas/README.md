# planqa-schemas

`review-agent`와 `eval-agent`가 지금까지 각자 독립적으로 복사해 들고 있던 `Issue`/`RuleBook`
정의 — 두 파일 모두 import 경로 한 줄만 다르고 나머지는 byte-identical이었던 게 확인되어
(`docs/adr/0002-monorepo-workspace-and-async-eval-service.md` 참고) 이번에 워크스페이스
공유 패키지로 통합했다.

`verifier.py`는 통합하지 않았다 — review-agent 쪽은 `has_valid_reference_exception`만 남기고
`VerifiedMatch`/`VerifiedMiss`/`verify_matches`/`verify_misses`(golden 비교 전용, eval-agent
에서만 쓰임)는 의도적으로 뺀 서브셋이라 진짜 중복이 아니다 — 그대로 각자 유지.

## 포함

- `schema.py` — `Issue`, `Level`, `KOREAN_LEVEL_NAMES`
- `rulebook.py` — `RuleDef`, `RuleBook`, `parse_rulebook`
