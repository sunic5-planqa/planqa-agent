# Progress Log

## 2026-08-03 — Review agent v1 draft (the missing "separate project" this repo evaluates)

### Done

- New `planqa_eval.review_agent` subpackage (branch `feature/review-agent`, off
  `feature/eval-agent`): the actual rulebook-based review agent, which up to now only
  existed as a stand-in (`data/sample_review_output.json`). Given a fresh 기획서 markdown
  file, it reviews it against `rulebook_v1.0.md` and outputs findings as an original-vs-
  suggested diff. Design follows two things approved in the 0730 mentoring notes: the
  cheap-screen/expensive-verify two-stage process ("방안 2"), and the Global Context ->
  Target Selection -> Parallel Execution -> Dedupe 4-stage orchestration.
- 6-stage pipeline: `context.py` (1x Global Context extraction, reused in every later
  prompt) -> `document.py` (§1 hierarchy split: Document/Logical Unit/Paragraph/Sentence,
  pure code, no LLM) -> `tiers.py` (§2 tier->category map, hand-transcribed — that table's
  markdown cells contain literal newlines from a Notion export, not safely regex-parseable)
  -> `screener.py` + `confirmer.py` (one batched screen call + one batched confirm call per
  tier, same indexed-batch-with-drop-on-miss pattern as `matcher.py`/`judge.py`) ->
  `dedupe.py` (same rule_id at overlapping locations collapses to the finest tier) ->
  `diff_report.py` (`review.json` + `review.md`).
- Reused rather than reimplemented: `rulebook.parse_rulebook`, `schema.Issue`/`Level`,
  `llm.factory.build_llm_client` (called twice, once per stage, so screen/confirm can run
  different models or even different backends), and — importantly —
  `verifier.has_valid_reference_exception` for the §3 reference-exception rules
  (LG-04/TC-02/AE-01/GA-03): the LLM's own `excused` claim is not trusted, the same
  deterministic proxy the eval-agent already validated against the DOC-006 AE-01 case
  decides it.
- `review.json` is field-compatible with `docs/adr/0001-review-agent-output-contract.md`,
  so it plugs directly into `planqa-eval evaluate --predictions review.json` — the review
  agent and the eval agent now actually connect inside this one repo.
- `review.md` renders each issue's `original_text` -> `fix_direction` as a line-level
  `difflib.SequenceMatcher` diff inside a ` ```diff ` fence, so GitHub/VSCode preview it
  with red/green highlighting — the "diff 방식으로 노출" requirement.
- New CLI: `planqa-review review --input <path.md> --doc-id DOC-001 [--backend]
  [--screen-model] [--verify-model] [--out]` (`pyproject.toml` script entry added).
- 7 new test files (`tests/test_review_*.py`), all against the existing `ScriptedLLM`
  fixture — no network/API key needed. `document.py` also tested against the real
  `DOC-001_*.md` source file's actual heading structure. Full suite: 80 passed (up from the
  existing 35 + `test_gemini_client.py`'s addition).
- `docs/review_agent_architecture.md`: the requested structure writeup — mermaid diagram of
  the 6 stages, per-stage rationale tied back to the mentoring notes, reuse table, CLI usage,
  and a "known limitations / extension points" section (word tier unassigned in rulebook §2,
  table rows treated as one sentence unit instead of per-cell, dedupe doesn't catch
  Document-tier vs finer-tier overlaps since the Document chunk's location is just the doc
  title).

### Notes

- No Python/uv was on PATH in this sandbox by default (only the Windows Store stub); found a
  real interpreter at `C:\Users\HYESEO\AppData\Local\Python\bin\python.exe`, built a throwaway
  `.venv` (already gitignored) to run the test suite instead of `uv run`.
- Same constraint as the rest of this repo: no `GEMINI_API_KEY`/Ollama available here, so this
  was verified with `ScriptedLLM` only — no live LLM run yet.

### Next

- Run it for real against Gemini/Ollama on an actual source document, sanity-check the
  screen/confirm prompts produce sensible diffs, and tune `--screen-model`/`--verify-model`
  for cost vs. recall.
- Decide the Document-tier vs finer-tier dedupe gap (see architecture doc) once a real
  overlapping case shows up.
- Word-tier review, once rulebook §2 actually assigns categories/input unit to it.

## 2026-08-05 — First live run against real Gemini, one bug fixed

### Done

- Ran `planqa-review review` against the real `DOC-001_홈화면_PRD_v1.0.md` with an actual
  `GEMINI_API_KEY` for the first time — the whole pipeline (Global Context, 4 tiers x
  screen+confirm, dedupe, report) completed end to end. Result: 6 issues (5x AE-03 vague
  expression, 1x TC-02 undefined abbreviation "PDP"), each with a real quoted original_text
  and a concrete fix_direction, rendered as ```diff blocks. Output kept at
  `outputs/review/20260805T090623Z/` as a real example (gitignored, not committed).
- Model names in the CLI examples/docs had rotted: `gemini-2.5-pro` is quota-0 on this
  free-tier key, `gemini-2.5-flash` 404s as "no longer available to new users". Probed
  `client.models.list()` and found the ones this key can actually call:
  `gemini-flash-lite-latest`, `gemini-3.1-flash-lite`, `gemini-3.5-flash-lite` all work
  (including in JSON mode); every non-`-lite` "pro"/"flash" tier is 429 quota-exhausted.
  Used `gemini-flash-lite-latest` (screen) + `gemini-3.5-flash-lite` (confirm) for this run.
  Documented the "list available models before trusting any hardcoded model name" lesson in
  `docs/review_agent_architecture.md`.
- Fixed a real bug this run surfaced: `cli.py`'s completion `print()` has an em dash (`—`),
  which crashed with `UnicodeEncodeError` on this Windows machine's cp949 console codepage
  — *after* the review had already finished and both report files were written, so the
  pipeline's actual output was fine but the CLI looked like it failed. Fixed with
  `sys.stdout.reconfigure(encoding="utf-8")` at the top of `main()`. Re-ran the full test
  suite after the fix (80 passed).

### Notes

- Environment quirk unrelated to the code: this sandbox had no `uv` and no real `python` on
  PATH (only the Windows Store stub) — found a working interpreter at
  `C:\Users\HYESEO\AppData\Local\Python\bin\python.exe` and built a `.venv` (gitignored) with
  `pip install -e . pytest` to run both the test suite and the live CLI run.

### Next

- Now that a live run works, do a second pass reading the actual issues found against
  DOC-001 by eye to sanity-check quality (the 6 issues above look reasonable on a skim, but
  haven't been compared against the golden dataset's DOC-001 rows).
- Consider pinning known-good model aliases as the CLI's defaults instead of leaving
  `--screen-model`/`--verify-model` required knowledge every time the Gemini lineup shifts.

## 2026-08-05 (later) — Model-profile restructure + team/branch alignment

### Done

- Team decision: this repo now permanently hosts both the eval agent and the review agent
  (no longer "eval agent evaluates a separate not-yet-built project") — a different repo
  will own frontend/backend integration. Branch roles clarified: `main` = production,
  `dev` = shared test branch, `feature/eval-agent`/`feature/review-agent` = individual dev
  branches per owner. User owns the review agent going forward and wants to run experiments
  across several models.
- `git fetch` surfaced a real branch-name collision: `origin/feature/review-agent` already
  existed (pushed by the user from elsewhere), diverged from `main`'s initial commit rather
  than from `feature/eval-agent`, containing only a scaffolding commit (`CLAUDE.md` +
  `.gitignore` + `docs/adr/.gitkeep` + empty `docs/progress.md`). Diffed the two `CLAUDE.md`
  files byte-for-byte (line-ending-normalized) — the only real difference was the title
  (`PlanQA Eval Agent` vs `PlanQA Review Agent`); everything else (code style, commit
  template, progress log convention, ADR template) was identical. Resolved by retitling this
  repo's `CLAUDE.md` to `PlanQA — Review & Eval Agents` rather than merging branches — no
  push done, per explicit instruction not to push/PR until asked.
- Restructured `review_agent/` so the model-facing prompt/logic (Global Context extraction,
  screening, confirming) is swappable per "model profile", not hardcoded:
  `context.py`/`screener.py`/`confirmer.py` moved to
  `review_agent/models/gemini_lite/{context,screener,confirmer}.py` (git-mv'd to keep
  history), re-exported from `models/gemini_lite/__init__.py`. `models/__init__.py` holds a
  `PROFILES` registry + `DEFAULT_PROFILE`. `pipeline.review_document` now takes a `profile`
  (any module exposing `extract_global_context`/`screen_tier`/`confirm_candidates` with the
  same signatures) instead of importing those three functions directly — `document.py`,
  `tiers.py`, `dedupe.py`, `diff_report.py` are untouched (model-agnostic). `cli.py` gained
  `--profile` (default `gemini_lite`, choices from the registry).
  To add a new model experiment: copy `models/gemini_lite/` to `models/<name>/`, rewrite
  prompts/parsing/batching freely (or reuse individual functions from another profile), add
  one line to `PROFILES`.
- Updated all affected imports (`tests/test_review_screener.py`,
  `tests/test_review_confirmer.py`, `tests/test_review_pipeline.py`) and doc links in
  `docs/review_agent_architecture.md` (added a "모델 프로필" section explaining the contract
  and how to add a profile; fixed the CLI example's stale model names to the ones actually
  validated live). Full suite still green (80 passed) after the move.

### Next

- Decide what to do with `origin/feature/review-agent` once ready to push (force-push to
  replace it, since the only real content — CLAUDE.md's title — is already folded in and
  nothing else on that branch is real work).
- Sync the 1 commit `origin/feature/eval-agent` gained (`fix: default Ollama backend to the
  tested qwen2.5:1.5b model`) into this branch when convenient — small, unrelated diff.
- First real second model profile, once the user picks which model to try next.

## 2026-08-05 (later still) — Time/token usage tracking for model-comparison experiments

### Done

- User's plan: run the review agent across several documents/model profiles, compare
  time/token cost (this) against accuracy (the eval agent, separately) to settle on one
  config. That needs actual instrumentation — there wasn't any before this.
- Confirmed via a real Gemini call that `response.usage_metadata` exposes
  `prompt_token_count`/`candidates_token_count`/`total_token_count`; Ollama's `/api/chat`
  exposes `prompt_eval_count`/`eval_count` the same way.
- Added `CallStats` (elapsed_seconds + token counts) and `usage: list[CallStats]` to
  `LLMClient` (`llm/base.py`) — purely additive, no existing call site (matcher.py,
  judge.py, new_rule_triage.py, review_agent's screener/confirmer/context) needed to
  change, since `complete_json`'s return contract is untouched. `GeminiClient`/
  `OllamaClient` now append one `CallStats` per successful call; `ScriptedLLM` in
  `tests/conftest.py` does too (zeroed) so anything reading `.usage` doesn't crash under
  fakes. `elapsed_seconds` deliberately includes 429 retry/backoff sleep — a model that
  gets throttled a lot on the free tier really is slower in practice for that run, so
  stripping it out would make the time comparison misleading.
- New `review_agent/run_stats.py`: `RunStats`/`ModelUsage` + `build_run_stats()` reading
  `screen_llm.usage`/`confirm_llm.usage` plus wall-clock time measured around
  `review_document()` in `cli.py`. Wired into `diff_report.py`: `review.json` becomes
  `{"issues": [...], "stats": {...}}` when stats are passed (the ADR-0001 parser already
  accepts that dict-wrapped shape, so `planqa-eval evaluate` compatibility isn't broken;
  `to_json_dict`/`to_markdown`/`write_report` all keep working with no `stats` arg for
  existing callers/tests). `review.md` gets a "## 실행 통계" section up top. Recorded
  `profile`/`screen_model`/`verify_model` in the stats too, since the output directory's
  timestamp alone doesn't say which config produced it — closes the gap noted in the
  2026-08-05 (earlier) entry.
- Live-verified end to end (`outputs/review/stats_smoketest/`, DOC-001, gemini_lite
  profile): 17.3s wall time, screening 4 calls/7.0s/10,216 tokens, confirm 4 calls
  (includes Global Context)/10.3s/6,927 tokens — both files show the numbers correctly.
- Answered the multi-API-key question: yes, worth doing, and `GEMINI_API_KEYS` (comma-
  separated, round-robins on 429) already existed in `llm/gemini.py` from the eval-agent's
  earlier work — no new code needed there. Explained that separate quota needs separate
  AI Studio *projects*, not just new keys in the same project, and that avoiding 429s
  during a timed comparison run matters as much as raising total quota (backoff sleep
  would otherwise inflate that run's measured time for reasons unrelated to the model).
- New tests: `tests/test_llm_base.py` (pure `CallStats` aggregation), `tests/test_run_stats.py`
  (`build_run_stats` against a local fake `LLMClient`), plus stats-path cases added to
  `tests/test_review_diff_report.py`. Full suite: 91 passed.

### Next

- The actual 10-document comparison run the user planned (DOC-006/007/010/016 "기본" +
  DOC-003/004/005/011/012/015 "중급", per `[멘토용]_오류_정답지.md`'s recommended test
  order) — paused on the user's "기다려", not yet run.
- Once that's run for a first profile, feed `review.json` into
  `planqa-eval evaluate --predictions` to get the accuracy side of the comparison.

## 2026-08-05 (final) — First 10-document batch, 2 reliability bugs found and fixed live

### Done

- User added 4 `GEMINI_API_KEYS`, but pasted them into the singular `GEMINI_API_KEY` (one
  215-char blob) instead of the plural comma-rotated var — moved the value over in `.env`
  without ever printing it to any tool output, confirmed 4 keys of 53 chars each parse
  correctly.
- Ran the planned 10-doc batch (DOC-006/007/010/016 "기본" + DOC-003/004/005/011/012/015
  "중급", gemini_lite profile, gemini-flash-lite-latest/gemini-3.5-flash-lite) — 6/10
  succeeded first try, 4/10 crashed the whole document's output to zero. Root-caused two
  real bugs from the live failures rather than guessing:
  1. `GeminiClient.complete_json` only retried `ClientError` 429 — a `ServerError` 503
     ("model overloaded", transient) wasn't a `ClientError` at all, so it propagated
     immediately and killed the run (DOC-006). Fixed: also catch `genai_errors.ServerError`
     and retry it through the same key-rotation/backoff loop.
  2. Even in JSON mode, the model sometimes returns invalid JSON ("Invalid \uXXXX escape",
     "Expecting property name...") — DOC-007/011/016. The bigger problem wasn't the parse
     failure itself, it was that **one tier's parse failure discarded every other
     already-successful tier's results for that document** (`review_document` had no error
     boundary). Fixed: `pipeline.review_document` now wraps Global Context extraction and
     each tier's screen+confirm in its own `try/except`, recording failures into a new
     `ReviewResult.tier_errors: tuple[str, ...]` field instead of raising — one tier failing
     no longer loses the rest. Surfaced in `review.md` (a "⚠️ 일부 위계 검토 실패" section)
     and `review.json` (`tier_errors` key, dict-wrapped like `stats`), plus a stderr warning
     line from `cli.py`.
  3. Along the way, found `cli.py`'s UTF-8 stdout reconfigure (from earlier today) didn't
     cover stderr, so the new tier-failure warning's ⚠️ emoji printed as escaped
     `⚠️` on this Windows cp949 console — reconfigured both streams.
- Re-ran the 4 failed docs after the fixes: all 4 completed this time. DOC-016 still hit a
  Sentence-tier JSON parse failure on retry, but this time correctly returned its other
  3 tiers' 2 real issues instead of crashing — direct confirmation the fault-isolation fix
  works as intended, not just in unit tests.
- New test `test_review_document_isolates_a_single_tier_failure` (a fake client that throws
  on its first call, verifying the other 3 tiers still run and the failure lands in
  `tier_errors`). Full suite: 92 passed.
- Full batch results (`outputs/review/batch_20260805T121340Z/`, not committed —
  gitignored):

  | doc | issues | tier failures | wall seconds | total tokens |
  |---|---|---|---|---|
  | DOC-006 | 9 | 0 | 121.7 | 24,910 |
  | DOC-007 | 4 | 0 | 58.5 | 18,796 |
  | DOC-010 | 6 | 0 | 43.4 | 16,605 |
  | DOC-016 | 2 | 1 | 36.1 | 19,188 |
  | DOC-003 | 2 | 0 | 14.9 | 17,204 |
  | DOC-004 | 4 | 0 | 16.5 | 18,973 |
  | DOC-005 | 6 | 0 | 18.2 | 17,399 |
  | DOC-011 | 1 | 0 | 44.9 | 15,610 |
  | DOC-012 | 2 | 0 | 25.2 | 19,565 |
  | DOC-015 | 0 | 0 | 16.7 | 17,789 |
  | **total** | 36 | 1 | **396.3s (~6.6min)** | **186,039** |

### Next

- Fix or accept DOC-016's remaining Sentence-tier JSON parse failure — could add a
  best-effort JSON repair pass in `parse_json_response`, or just treat occasional per-tier
  loss as an acceptable cost of the free-tier lite models and move on.
- Compare this gemini_lite run's `36 issues / 396s / 186k tokens` baseline against a second
  model profile once the user builds one (this was the whole point of `run_stats`).
- Cross-check a few of these 36 issues against `[멘토용]_오류_정답지.md`'s answer key by
  eye, and/or feed a `review.json` into `planqa-eval evaluate --predictions` once its golden
  rows cover these particular documents.

## 2026-08-05 (very final) — Moved to its own top-level folder (monorepo split)

### Done

- Team decision realized: this repo now has `eval-agent/` and `review-agent/` as two fully
  independent top-level projects (own `pyproject.toml`, own package, own venv), not eval
  evaluating review as a nested subpackage. Triggered by discovering `origin/feature/
  eval-agent` had already moved everything into `eval-agent/` (commit `ec5bb8b`) — this
  session's work (previously `src/planqa_eval/review_agent/`) moved to `review-agent/src/
  planqa_review/` to match.
- **Rulebook changed substantially upstream while this was in flight** — eval-agent's
  `e9e8f45` refreshed `rulebook_v1.0.md` from 40 to 41 rules: §2's tier/category table was
  rebuilt (LG/LF/TC/TM/AE/MI/RD/GA renumbered and reworded in places, e.g. old LG-04 →
  new LG-03), §3's reference-exception rule set changed (LG-04→LG-03), and a new "부재
  확인형(Absence Check)" concept was added for rules that need whole-document scope
  regardless of where they're flagged. Pulled the new rulebook file and eval-agent's fixed
  `rulebook.py` (adds `_repair_wrapped_table_rows()`, solving the malformed-table-cell
  parsing problem this repo's `tiers.py` had cited as the reason for hardcoding §2 instead
  of parsing it). **Did not** re-derive `tiers.py`'s `TIER_CATEGORIES` from the new §2 or
  implement Absence Check — flagged both as an explicit TODO in
  `docs/review_agent_architecture.md`, deferred to the user's planned pipeline-architecture
  redesign (parallel/multi-agent/single-agent+tools/separate-review-tool variants) rather
  than done piecemeal now. `rulebook.reference_exception_rule_ids` needed no code change
  since it's parsed from the file at runtime, not hardcoded — it already reflects LG-03.
- **No cross-package dependency on eval-agent** — the user's constraint is that
  `feature/eval-agent` must not be touched, so `review-agent/` embeds its own independent
  copies of `rulebook.py`, `schema.py`, a trimmed `verifier.py` (just
  `has_valid_reference_exception` — dropped the golden-vs-predicted comparison functions
  that are eval-only), and `llm/{base,factory,gemini,ollama}.py`. Considered a uv path
  dependency instead, but rejected it: token-usage tracking needs the raw SDK response
  (`response.usage_metadata`), which the abstract `LLMClient.complete_json()` interface
  discards before returning — an external wrapper around a dependency's client can time
  calls but can never recover token counts, so owning the client code was the only way to
  keep that feature. Re-applied this session's earlier `CallStats`/usage-tracking and
  429/5xx-retry additions on top of eval-agent's latest `llm/` files (which had picked up
  an unrelated `qwen2.5:1.5b` Ollama default-model fix in the meantime).
- Added `rulebook_hash` (first 12 hex chars of the rulebook file's SHA-256) to `RunStats`,
  surfaced in both `review.json`'s `stats` block and `review.md`'s "실행 통계" section — the
  rulebook's own "V1.0" label doesn't change even when rule content does (as just observed),
  so a content hash is the only reliable way to trace which exact rulebook state produced a
  given run's results later, cross-referenced against `git log -p -- data/rulebook/
  rulebook_v1.0.md`.
- Split `docs/progress.md`: this file now holds only review-agent's own history (everything
  from 2026-08-03 onward); the original eval-agent-only sessions from 2026-08-02 stayed
  implicitly with eval-agent (this repo's old root-level copy was deleted, not eval-agent's
  actual copy under `eval-agent/`, which this session never touched).
  Renamed test files to drop the now-redundant `test_review_` prefix (`test_document.py`,
  `test_tiers.py`, etc.) since they no longer share a `tests/` folder with eval-agent's own
  tests. Full source_documents set brought over too — eval-agent's dataset grew from 20 to
  40 documents (`DOC-021`–`DOC-040`, mostly personal/team documents each human reviewer
  contributed) — didn't need all of them yet, but no reason to leave them behind.
- Rebuilt the venv from scratch inside `review-agent/`, reinstalled, reran the full suite:
  47 passed. Confirmed the new 41-rule rulebook parses cleanly (`rb.rules` == 41,
  `reference_exception_rule_ids` == `{GA-03, LG-03, AE-01, TC-02}`) and the CLI still works.
- Old root-level `data/`, `docs/`, `src/`, `tests/`, `CLAUDE.md`, `README.md`,
  `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore`, `.python-version` all removed
  from this branch (`git rm`, not touching `feature/eval-agent` — those files' real home is
  there now, at `eval-agent/...`, untouched by any of this).

### Next

- Force-push `feature/review-agent` (now structurally parallel to `feature/eval-agent`,
  finally) — was blocked pending exactly this restructure.
- Re-derive `tiers.py`'s tier→category mapping (and consider implementing Absence Check)
  as part of the next pipeline-architecture redesign session — see the TODO in
  `docs/review_agent_architecture.md`.
- Re-run the 10-document batch once the rulebook update is accounted for in `tiers.py` —
  the earlier batch's results were produced against the old 40-rule rulebook and are now
  stale relative to the current spec.

## 2026-08-06 — Switched to team's frozen data as the single source of truth

### Done

- Team decided this repo's `eval-agent/` (not something we own — never modify that branch)
  should no longer be treated as the data source either; the user's own "frozen" copies are
  now canonical. Confirmed `Rulebook Simple V1.0 frozen.md` is byte-identical to what was
  already pulled from eval-agent (no functional change), but replaced it anyway so
  provenance points at the frozen file directly rather than eval-agent's copy.
- Replaced `data/qa_dataset/` with `QA Dataset frozen.xlsx` (same "golden dataset" sheet
  content as eval-agent's `qa_dataset_2026-08-05.xlsx`, confirmed via row-by-row diff — but
  `Review3`/`Review4` have ~29-30 more rows each that eval-agent's copy didn't: a genuine
  **exception/false-positive example set** ("예외조건 data" marker row in Review4), 58 rows
  across 26 distinct rule IDs, each with 원문(text that superficially looks like a
  violation) + 근거(why it's actually excused). This is exactly the negative-example gap
  identified on 2026-08-05 — previously the only known negative examples were DOC-008
  (whole-document, 0 golden rows, explicitly labeled "False Positive 테스트" in the
  `Documents` sheet) and the DOC-006 AE-01 §3 counter-example.
- Replaced `data/source_documents/` (41 files: DOC-001–040 + a DOC000 placeholder docx)
  with the team's own raw-document folder, and added the mentor-facing answer key
  (`[멘토용]_오류_정답지.md`) to `data/qa_dataset/`. **Did not read the content of any
  document during this copy** — per explicit instruction, since these documents are the
  blind evaluation set and reading them while doing pipeline/prompt engineering would be
  leakage. Copied via filesystem operations only (`cp`/`Copy-Item`), never via the Read
  tool. Hit a real gotcha copying `[멘토용]_오류_정답지.md`: PowerShell's `Copy-Item -Path`
  interpreted the literal `[...]` in the filename as a wildcard character-class pattern
  (matching nothing, failing silently with no error) — fixed with `-LiteralPath`.
- Scoping decision (user's call, agreed): recall/precision/time/token measurement will use
  only DOC-001–020 (the real NxEF product docs) for now. DOC-021–040 are teammate-generated
  (mostly AI-generated) documents built specifically to backfill example coverage for
  under-represented rules — deliberately synthetic/wrong, not representative real-world
  documents, so they're set aside from general evaluation and saved for a later rule-
  coverage-gap-filling pass instead. Checked golden dataset's real split: DOC-001–020
  (excl. the unusable DOC-000 placeholder rows) = 19 rows/18 docs; DOC-021–040 = 36 rows/20
  docs — confirmed DOC-000 itself (76 of 131 total golden rows!) was never usable anyway,
  regardless of this scoping choice, since it has no real source document.
- Corrected an earlier miscategorization: proposals 6 (Generator-Critic) and 7 (Chain-of-
  Verification) are pipeline-*structure* options, not few-shot-*delivery* mechanisms —
  structure options are now: 셀1-4 (2×2 of 방안1/2 × 1안/2안) + 제안5 (deterministic
  tier×category parallel, no tool-calling) + 제안6 + 제안7. Few-shot delivery options
  (orthogonal, layer onto any structure): 제안8 (retrieval-based dynamic few-shot), 제안9
  (static per-rule bank + prompt caching), 제안10 (explicit violation:exception ratio —
  now buildable using the 58-row exception set above).
- Agreed experiment order: **구조 → 퓨샷 → 모델** (structure first since it's the most
  expensive to change/redo, few-shot second since it's cheap prompt-only iteration on a
  fixed structure, model swap last since it needs new client code) — reasoning validated
  independently, not just deferring to the user. Caveat flagged: model choice and few-shot
  design interact (weaker models lean more on examples), so plan to re-check the few-shot
  ratio specifically against whichever model wins the final model-ablation step, rather
  than assuming the recipe tuned on the first model transfers cleanly.

### Next

- Build the ablation infrastructure discussed: finer (tier, category) call granularity so
  time/tokens are attributable per rule/category (not just per tier), a review-agent-owned
  deterministic scorer against the frozen golden dataset (no LLM matching needed for a
  small fixed benchmark), a small experiment runner to sweep (structure × few-shot × model)
  combinations over a fixed DOC-001–020 benchmark subset, temperature/seed control for
  reproducibility, and at least one non-Gemini model client (OpenAI or Claude) for a
  meaningful model-family ablation axis.
- Pick the DOC-001–020 ablation benchmark subset (something like the 5-8 already-tested
  docs + DOC-008 for the false-positive check).
- Start executing: 구조 실험(제안5 vs 6 vs 7 등) 먼저.

## 2026-08-06 (checkpoint, mid-task) — Decisions locked in + ablation infra in progress

Written mid-task (context compaction imminent) specifically so none of this is lost.

### Standing decisions (durable, apply to all future sessions on this repo)

- **Experiment order, confirmed**: 구조(pipeline/agent structure) → 퓨샷(few-shot delivery)
  → 모델(model swap). Reasoning: structure changes need new code (most expensive to
  redo), few-shot is prompt-only (cheap to iterate once structure is fixed), model swap
  needs new client code (do last, fewest times). Caveat: re-check the few-shot ratio
  against whichever model wins the final model-ablation step, since model
  capability/few-shot need interact (weaker models lean on examples more).
- **User will build pipeline/agent structures ONE AT A TIME** after the measurement
  infra below is ready — not all at once. Each structure = its own model profile under
  `src/planqa_review/models/<name>/`, independently managed. **`outputs/` folder naming
  must make the originating agent structure obvious** (e.g. include profile name in the
  path) — this was an explicit instruction, implemented via `_timestamp()`-based
  `--out` default in `cli.py` gaining the profile name (see Next below — not done yet
  as of this checkpoint).
- **Evaluation scope**: recall/precision/time/token measurement uses **only DOC-001–020**
  for now (the real NxEF product docs). DOC-021–040 are teammate-generated
  (mostly-AI-generated, deliberately-wrong-by-design) documents built to backfill example
  coverage for under-represented rules — set aside for a later rule-coverage-gap-filling
  pass, not general evaluation. DOC-000 was never usable regardless (no real source text).
- **eval-agent may now be run live** (teammate gave permission) — but explicitly **not
  yet**: only after this repo's own time/token measurement work is finished. Do not start
  that integration until told.
- **Frozen files under `C:\Users\HYESEO\Desktop\혜서\suni\frozen_files\` are the single
  source of truth going forward** — not eval-agent's copies. Already pulled in:
  `Rulebook Simple V1.0 frozen.md` (byte-identical to what eval-agent had — no rule
  content changed by this swap), `QA Dataset frozen.xlsx` (has 58-row exception dataset
  eval-agent's copy lacked — see 2026-08-06 entry above), `01_Raw_Documents/` (41 files,
  DOC-001–040 + DOC000 placeholder) and `[멘토용]_오류_정답지.md`. **The document content
  itself must never be read while doing pipeline/prompt engineering work** (it's the blind
  eval set — reading it while tuning prompts is leakage). All copies so far were done via
  filesystem operations only (`cp`/`Copy-Item -LiteralPath`), never the Read tool. Watch
  for: frozen source filenames may arrive NFD-normalized (decomposed Hangul jamo) instead
  of NFC — normalize with `unicodedata.normalize("NFC", name)` before committing, or
  filename string-matching elsewhere in the codebase silently breaks.
- **Read-only/verification commands need no prior approval going forward** — including
  against `feature/eval-agent` (worktree, running its tests, etc.) or arbitrary bash.
  Only actual modifications (file edits, commits, pushes) need to be flagged/confirmed.
  (Consistent with existing memory `feedback-no-push-without-request`, but broader — that
  one was push-specific, this covers all read-only investigation.)
- Corrected categorization: pipeline-**structure** options = 셀1–4 (2×2 of 방안1/2 ×
  1안/2안) + 제안5 (deterministic tier×category parallel, no tool-calling) + 제안6
  (Generator-Critic) + 제안7 (Chain-of-Verification decomposition). Few-shot **delivery**
  options (orthogonal, layer onto any structure) = 제안8 (retrieval-based dynamic
  few-shot), 제안9 (static per-rule bank + prompt caching), 제안10 (explicit
  violation:exception ratio, now buildable with the 58-row exception set).

### This session's engineering task: ablation measurement infrastructure

User's explicit ask: build the **measurement structure** so ablation testing is possible,
*before* any new pipeline/agent structure gets built. Scope is instrumentation/harness
only — not fixing `tiers.py`'s stale (pre-41-rule) `TIER_CATEGORIES` mapping, which stays
deferred to the actual structure-building phase.

**Done so far (this checkpoint):**
- Moved `rules_for_tier()` from `models/gemini_lite/screener.py` to `tiers.py` — it's
  profile-agnostic rulebook/tier logic, and the instrumentation work below (in
  profile-agnostic `pipeline.py`) needs to call it without importing a specific profile's
  internals. Tests moved accordingly (`test_tiers.py` now owns those cases,
  `test_screener.py` trimmed). 47 passed after this refactor.
- Added `temperature: float = 0.0` (default, not each backend's own default — for
  ablation reproducibility, so re-running the same config isn't confounded by sampling
  noise) to `GeminiClient.__init__` (passed into `GenerateContentConfig`) and
  `OllamaClient.__init__` (passed into the request JSON's `options.temperature`).
  Threaded through `build_llm_client(backend, model, temperature=0.0)` in `llm/factory.py`.
  **Not yet done**: wiring a `--temperature` CLI flag through `cli.py` to the two
  `build_llm_client()` calls in `cmd_review` — next immediate step.

**Still to do (in order), per the todo list active at checkpoint time:**
1. Finish `--temperature` CLI plumbing (in progress when checkpoint was written).
2. Call-event instrumentation in `pipeline.py`: tag each LLM call with
   `(stage: "context"|"screen"|"confirm", tier: Level, rule_ids/category_codes covered)`
   by wrapping the tier loop (pipeline.py already knows the tier and can call
   `tiers.rules_for_tier()` itself) — record `len(llm.usage)` before/after each
   `profile.*` call to slice out the new `CallStats` entries and pair them with the tag.
   Design intent: whatever granularity a *future* profile actually calls at (per-tier
   today, maybe per-category or per-rule later) is what gets captured — don't force fake
   per-rule precision onto a batched call that covers multiple rules at once.
3. Extend `run_stats.py`: add rollups grouped by tier and by category/rule using the
   event log from step 2, not just the existing screen/confirm-bucket totals.
4. Add `openpyxl` to `review-agent/pyproject.toml` dependencies — needed for step 5.
5. New deterministic scorer module (e.g. `planqa_review/scoring.py`): reads golden rows
   for a given doc_id straight from the frozen xlsx (`data/qa_dataset/qa_dataset_frozen.xlsx`,
   sheet `"golden dataset"`), compares against a `review.json`'s issues by
   `rule_id` + location containment (deterministic, no LLM matching needed — eval-agent's
   fuzzy LLM matcher can't be reused since we must not touch `feature/eval-agent`, but a
   small fixed benchmark doesn't need fuzzy matching anyway). Produces recall/precision
   per rule_id, per category, and overall for one doc or a doc set.
6. Define the ablation benchmark doc list (e.g. in a new `planqa_review/benchmark.py`) —
   leaning toward reusing the 10 already-tested docs (DOC-003/004/005/006/007/010/011/
   012/015/016) + DOC-008 (the designated false-positive/clean-doc test case) rather than
   picking a fresh subset, since real historical run data already exists for those 10.
7. Experiment runner: sweeps the benchmark set for a given (profile, backend, models,
   temperature) combo, collects `RunStats` + scoring results, writes one aggregated
   report. Naming convention: `outputs/review/<profile>/<timestamp>/...` (profile name in
   the path — the explicit "폴더명으로 어떤 에이전트 구조인지 알기 쉽게" requirement).
   Also update the plain `cli.py review` command's default `--out` to the same
   `<profile>/<timestamp>` shape, not just the runner.
8. Tests for everything above.
9. Full test suite green.
10. Update `docs/review_agent_architecture.md` (new instrumentation/scoring/runner
    sections) and this progress log with the final state.
11. Commit locally (no push — standing rule, only push when explicitly asked).

## 2026-08-06 (continued) — Ablation measurement infrastructure complete

Finished every remaining item from the checkpoint above. All new code is `ScriptedLLM`-
tested, no network/API key needed to verify it.

- **`openpyxl>=3.1`** added to `pyproject.toml`, installed into the venv.
- **`planqa_review/scoring.py`** (new) — `load_golden_rows(xlsx_path)` reads the
  `"golden dataset"` sheet of `data/qa_dataset/qa_dataset_frozen.xlsx`. Inspected the raw
  sheet first: 983 rows, but only **131** carry real data (doc_id + rule_id present) — the
  other 852 are blank spacer rows the loader skips. Of those 131: 76 are DOC-000 (excluded
  from scope anyway), the rest span DOC-001–040. Confirmed the sheet's 41 distinct
  `Rule ID` values match the current (post 2026-08-05) 41-rule rulebook, and its `Level`
  column strings (`"Document"`/`"Logical Unit"`/`"Paragraph"`/`"Sentence"`) match
  `schema.Level`'s values exactly — no translation needed.
  `score_issues(doc_id, issues, golden_rows)` matches deterministically: same `rule_id` +
  overlapping (substring, either direction) `location` string = TP; unmatched golden row =
  FN; unmatched predicted issue = FP. `ScoreCounts` (TP/FP/FN + `recall`/`precision`
  properties) rolls up by rule, by category (derived from the rule_id prefix, no
  `RuleBook` dependency needed), and overall. `merge_score_results()` sums multiple
  documents' `ScoreResult`s into one. 14 tests, including two against the real xlsx file.
- **`planqa_review/benchmark.py`** (new) — `BENCHMARK_DOC_IDS`: the 10 previously-tested
  docs (DOC-003/004/005/006/007/010/011/012/015/016, all of which have golden rows) +
  DOC-008 (the deliberate zero-golden-row false-positive test case) = 11 docs. Verified
  each doc_id actually has 0 or 1 matching file in `source_documents/` via
  `resolve_source_path()` (glob `f"{doc_id}_*"`, raises if 0 or 2+ matches — filenames are
  Korean titles, not just the doc_id). 6 tests.
- **`planqa_review/experiment.py`** (new) — `run_experiment(config, rulebook,
  rulebook_path, source_dir, golden_rows, build_clients=None)` sweeps
  `config.doc_ids` (defaults to `BENCHMARK_DOC_IDS`), building a **fresh** LLM client pair
  per document (mixing usage across documents would corrupt per-document token/time
  stats) via an injectable `build_clients` callback — defaults to the real
  `build_llm_client`, tests override it with scripted clients. Produces
  `ExperimentSummary`: `RunStats`-shaped totals (`screen`/`confirm`/`by_stage`/`by_tier`/
  `by_rule`) summed across every document, plus the benchmark-wide `ScoreResult`.
  `write_experiment_report()` writes one `<doc_id>/review.{json,md}` per document (reusing
  `diff_report.write_report` — same shape a single `planqa-review review` run produces)
  plus a root `summary.json`/`summary.md` (category recall/precision table + per-document
  issue-count table). 4 tests (2-document sweep, per-document isolation check, markdown
  content check, file-write check).
- **CLI**: new `planqa-review experiment` subcommand (`--rulebook`/`--source-dir`/
  `--qa-dataset`/`--doc-ids`/`--backend`/`--screen-model`/`--verify-model`/
  `--temperature`/`--profile`/`--out`), output defaults to
  `outputs/experiments/<profile>/<timestamp>/`.
- **`run_stats.py`**: `RunStats` gained `by_stage`/`by_tier`/`by_rule` (derived from the
  `call_events` log, see `instrumentation.py`) alongside the existing `screen`/`confirm`.
  `diff_report.py`'s `review.json` output now includes those three breakdowns too
  (markdown summary unchanged — kept to the overall totals, fine detail stays JSON-only).
- Full suite: **83 passed** (59 before this session's scoring/benchmark/experiment work,
  +24 new: scoring 14, benchmark 6, experiment 4).
- `docs/review_agent_architecture.md`: added an "Ablation 측정 인프라" section covering
  all four new pieces (temperature reproducibility, call-event instrumentation, scoring,
  benchmark set, experiment runner) plus a 검증 상태 bullet noting the 83-test state.

### Next

- **Not yet done**: actually running `planqa-review experiment` against a real Gemini
  backend over the 11-doc benchmark set to get a real recall/precision/cost baseline —
  this infra has only been exercised with `ScriptedLLM`, never live. That's the natural
  next step before touching any new pipeline/agent structure.
- Per the agreed experiment order (구조 → 퓨샷 → 모델): once a live baseline exists, start
  building/comparing pipeline **structures** one at a time (each independently managed,
  named so its `outputs/` folder makes the structure obvious), using this harness to
  compare them.
- `tiers.py`'s `TIER_CATEGORIES` is still stale (pre-41-rule §2) — deliberately deferred to
  the structure-building phase, not touched by this ablation-infra work.
- eval-agent may be run live now (teammate approved) but only after this repo's own
  measurement work is done — that's now true, but running it wasn't asked for in this
  session and hasn't been done.

## 2026-08-06 (correction) — Scope check on the ablation infra, one gap fixed

User pushback: the ask was time/token measurement for ablation, not "build an accuracy
evaluation system" — accuracy is the teammate's separate eval-agent's job, run by hand
against this repo's `review.json` outputs. Clarified `scoring.py` isn't scope creep to
delete, though — the user may still want to compare their own review-agent-side accuracy
against the teammate's eval-agent numbers later, so it stays as-is.

Asked the user to confirm two things against their actual two goals (per-rule time/
accuracy-tradeoff visibility; ablation-style comparison of internal control variables):

1. **Gap found and fixed**: `ExperimentSummary`/`summary.json` didn't record `temperature`
   or `rulebook_hash` — two of the "control variables" being ablated, yet a saved
   `summary.json` couldn't say which values produced it (only the output folder's
   timestamp could, and that's not machine-readable). Added both fields to
   `ExperimentSummary`, `_summary_dict()`, and the markdown header. One new test
   (`test_summary_records_temperature_and_rulebook_hash_for_cross_run_comparison`).
2. **Gap found, deliberately deferred**: nothing yet aggregates multiple `summary.json`
   runs (different model/temperature combos) into one side-by-side comparison/ablation
   table — today each `planqa-review experiment` invocation produces one self-contained
   result; comparing configs means opening multiple `summary.json` files by hand. User
   chose to stop at measurement for now and design the comparison feature separately once
   there's a clearer idea of what the comparison view should look like.

Full suite: 84 passed (+1 from the temperature/rulebook_hash test).

### Next

- Same as the previous entry's "Next" — plus, whenever the comparison/ablation-table
  feature above gets picked up, it can lean on `summary.json`'s now-complete
  self-description (profile/backend/screen_model/verify_model/temperature/rulebook_hash)
  to know which file is which without parsing folder names.


지금까지 승인받은 계획을 다시 정리해서 설명드릴게요.

대상 7개 구조

제안5 (baseline) — 지금 이미 완성된 gemini_lite. tier 기준 그룹핑 + tool-calling 없음. 새로 안 만들고 나머지 비교 기준점으로만 씀.
셀1 (방안1×1안) — 문단 단위로 청킹, 문단마다 카테고리 8개를 각각 독립 호출로 검토
셀2 (방안1×2안) — 문단 단위 청킹 + 카테고리별 서브에이전트가 룰 단위 Tool까지 씀
셀3 (방안2×1안) — 지금 tier 청킹 그대로, 카테고리별로 독립된 호출 병렬 실행
셀4 (방안2×2안) — 지금 tier 청킹 그대로 + 룰 단위 서브에이전트 tool-calling
제안6 (Generator-Critic) — confirm 이후에 비판적으로 재검토하는 단계 하나 추가 (새 구조 아님, 기존 구조에 얹는 보강)
제안7 (Chain-of-Verification) — 판정을 하위질문 체인으로 쪼개서 검증 (역시 얹는 보강, 새 프로필 하나로 해결)
만들기 전 공통 선행 작업 (한 번만)

GeminiClient에 tool-calling 메서드 추가 (google-genai SDK에 이미 지원 있음, 새 패키지 필요 없음)
experiment.py가 지금 baseline 구조에 고정돼 있어서, 어떤 구조든 꽂을 수 있게 일반화 + cli.py에 --structure 플래그 추가
만드는 순서: 셀3 → 셀4 → 셀1 → 셀2 → 제안6 → 제안7

셀3이 제일 쌈: 청킹은 그대로 쓰고 카테고리별로 호출만 쪼갬(진짜 tool-calling도 필요 없고 그냥 병렬 호출로 충분)
셀4는 셀3에 룰 단위 tool만 얹음
셀1은 문단 청킹을 새로 짜야 해서 더 복잡, 셀2는 문단 청킹+룰 단위까지 다 필요해서 제일 나중
제안6/7은 어느 구조든 위에 얹는 거라 마지막
각 구조 만들 때마다: 독립 모듈로 구현 → ScriptedLLM으로 테스트 → 문서 12개 실제 API로 스모크 테스트(비용 확인) → 통과하면 벤치마크 DOC-001020 전체로 experiment 실행 → review.json은 팀원 eval-agent에 넣어서 정확도 확인(우리 쪽은 시간/토큰만 잼).

주의할 점: 룰 단위(셀2/4)는 호출 수가 크게 늘 수 있어서 전체 20개 문서 돌리기 전에 꼭 12개로 먼저 확인. Ollama는 tool-calling 검증 안 됐어서 셀14는 일단 Gemini 전용.

지금 셀3 이전 공통 선행 작업(1번, tool-calling 메서드)부터 다시 이어가면 될까요?

## 2026-08-06 (continued) — Fixed a stale TIER_CATEGORIES bug found while reviewing before Cell 3

While reviewing the codebase ahead of starting the Cell 3 structure work above (not started
yet), diffed `tiers.py`'s hand-transcribed `TIER_CATEGORIES` against the current rulebook
file's actual §2 table and found it badly out of sync — almost certainly stale from before
the 2026-08-05 40→41-rule rulebook refresh, despite the file's own comment saying to keep it
in sync. Confirmed by extracting §2's category order programmatically from the rulebook's `##`
headings (`LG, LF, TC, TM, AE, MI, RD, GA`) and cross-referencing each tier row:

| 위계 | 이전 (틀림) | 수정 후 (룰북 §2) |
|---|---|---|
| 문서 | LG,LF,TC,MI,RD,GA (6개, TM 누락) | LG,LF,TC,TM,MI,RD,GA (7개) |
| 논리단위 | LG,LF,TM,AE,MI (5개, TC/RD/GA 누락) | LG,LF,TC,TM,AE,MI,RD,GA (8개, 전체) |
| 문단 | TM,MI (2개, LG/LF/TC/AE/RD 누락) | LG,LF,TC,TM,AE,MI,RD (7개) |
| 문장 | TM,AE (2개, LG/TC/MI 누락) | LG,TC,TM,AE,MI (5개) |

Every past review run (including all `gemini_lite`/제안5 baseline numbers logged above) was
checking far fewer categories per tier than the rulebook actually specifies — worst at
Paragraph tier, 2 of 7 required categories. Fixed `TIER_CATEGORIES` in place; no other
production code needed to change (`rules_for_tier()` and every caller derive purely from this
dict, no hardcoded category assumptions elsewhere). Added
`test_tier_categories_matches_rulebook_section_2` to `tests/test_tiers.py` to pin the fix.
Existing tests were all internal-consistency checks (didn't pin specific values), so nothing
else needed updating. Full suite: 85 passed (+1).

Sandbox note: no `.venv` existed this session (fresh checkout); rebuilt one with system
`python` (3.13, found via `where python`) + `pip install -e . pytest` — worked fine despite an
initial transient DNS failure on the first attempt.

### Next

- Re-run any past baseline numbers if/when they matter again — they were produced against the
  stale mapping and will look different (more issues, esp. at Paragraph/Sentence tier) next
  time `gemini_lite` runs live.
- Resume the Cell 3 structure work per the checkpoint above: still deciding whether to build
  GeminiClient's tool-calling method now (originally-approved order) or defer it to when Cell 4
  actually needs a concrete tool schema — not yet decided.

## 2026-08-09 — Model pilot infra + 제안0/셀3/셀3R structures

### Done

- **Rulebook audit before touching anything live**: re-read the current 41-rule rulebook
  end to end and cross-checked every code path against it. `TIER_CATEGORIES`/parsing/§3
  exception rules all already correct (previous session's fix holds up). Found one real
  gap: §1's "부재 확인형(Absence Check)" concept (LG-01/TC-02 — rules that ask "does this
  exist anywhere in the document," unanswerable from a single paragraph/sentence chunk) was
  never implemented — those two rules were being checked at every tier, not just Document.
  Fixed in `tiers.py` (`ABSENCE_CHECK_RULE_IDS`, excluded outside Document tier). Fixed a
  stale comment in `confirmer.py` (said LG-04, current §3 target is LG-03 — logic was
  already dynamic/correct, only the comment was wrong).
- **Model pilot infrastructure**: discovered (via the user's own API gateway,
  `docs.mindlogic.ai/docs/sookmyung/api-gateway`) that Claude/GPT/Gemini/**EXAONE**/Solar
  Pro3 are all reachable through one OpenAI-compatible endpoint + one key — no separate
  vendor integrations needed. Built `llm/gateway.py` (`GatewayClient`), registered as
  backend `"gateway"` in `factory.py`. Real gotcha: Cloudflare fronts the gateway and
  blocks the default httpx/urllib User-Agent outright (error 1010, a bot-fingerprint rule,
  not an auth check) — fixed with a browser-shaped UA header. Verified actual routing (not
  just the model's own unreliable self-report) via the response's top-level `model` field
  for all 5 candidates. EXAONE (236B) measured 60s+ on a single trivial prompt — bumped
  `GatewayClient`'s timeout to 240s to give real pipeline-sized prompts headroom.
- **QA dataset refreshed** to the latest frozen file (user-provided) — golden dataset sheet
  unchanged, gained a new "예외조건 golden dataset" sheet (995 rows, exception-condition
  examples) for future few-shot work.
- **Pilot doc selection**: DOC-006/DOC-003/DOC-012/DOC-001/DOC-008, one per difficulty tier
  from `[멘토용]_오류_정답지.md`'s recommended test order plus the DOC-008 false-positive
  check — chosen instead of the full 20-doc benchmark to keep the pilot cheap.
- **`docs/experiments/results.md`** created — three sections (모델/파이프라인/퓨샷) to hold
  ablation results as they land, per the user's explicit ask.
- **`experiment.py` generalized**: `run_experiment()` now takes an optional `review_fn`
  (defaults to baseline via `models.PROFILES`/`pipeline.review_document` — fully backward
  compatible, all existing tests unchanged). `cli.py` gained `--structure` on **both**
  `review` and `experiment` subcommands, looking up `structures.STRUCTURES`.
- **Three new structures built** (all additive — `pipeline.py`/`models/gemini_lite/*`
  untouched), each in its own `structures/<name>.py`, tested with `ScriptedLLM`/content-aware
  fakes (no live API cost):
  - `proposal0.py` — 제안0: same tier chunking as baseline, but no screen/confirm split —
    one call per tier goes straight to a final verdict.
  - `cell3.py` — 셀3: same tier chunking, but each category assigned to a tier gets its own
    independent screen→confirm pass, dispatched concurrently via a thread pool (no real
    tool-calling — §2 already fixes category-to-tier assignment deterministically, so
    nothing needs "deciding").
  - `cell3r.py` — 셀3R: same as 셀3 but dispatch unit is one individual rule, not a whole
    category — inserted so "finer granularity" and "real tool-calling" (셀4) can be
    measured as separate variables instead of changing together.
  - Real gotcha hit twice building these: a naive `"candidates" in system` check to tell
    screen/confirm calls apart in test fakes broke because `_CONFIRM_SYSTEM`'s own prose
    says "most **candidates** should come back violated=false" — fixed by checking for
    `"verdicts"` (only in the confirm schema) instead.
  - `docs/review_agent_architecture.md` gained a "구조 레지스트리" section documenting the
    additive-only rule, the structure contract, and this table.
- **Model pilot run, live, twice interrupted**:
  - Gemini candidate completed cleanly: 5 docs, 120.7s wall (~24s/doc) — doesn't touch
    gateway credit at all (separate `GEMINI_API_KEY`), numbers stand as-is.
  - First live batch run killed mid-Claude on a false alarm — a single large real-document
    call to Claude via the gateway actually completes in ~8s, so the batch wasn't hung, just
    slower than the 1-line smoke test suggested. Rewrote the runner to show real-time
    per-document timing and auto-exclude any candidate whose *single document* exceeds 60s
    (user's rule), instead of judging a whole 5-doc batch at once.
  - **Gateway credit ran to ~50% used** (user-reported) partway through re-running
    Claude/GPT/Solar (EXAONE pre-emptively excluded from smoke-test evidence alone, never
    live-tested against the pilot documents) — paused all live calls immediately, confirmed
    with the user whether to keep going (yes — just stop *wasteful* exploratory calls, not
    the actual experiment), then resumed the same per-document-capped runner for
    Claude/GPT/Solar. **Still running as of this entry** — outcome not yet known.

### Next

- Land the Claude/GPT/Solar pilot results (or their exclusions) into
  `docs/experiments/results.md`'s 모델 section, then run each surviving candidate's
  `predictions.json` through eval-agent (`planqa-eval evaluate`, read-only worktree at
  `C:\Users\HYESEO\Desktop\eval-agent-check\eval-agent`, needs its own `.env` with an API
  key first — not yet set up) for recall/precision, plus a human read of Korean
  `fix_direction` quality (not an LLM judgment — bias risk).
- Pick the winning model, then decide 셀4's tool-calling home (gateway's OpenAI-compatible
  `tools`/`tool_choice` fields vs Gemini's native SDK) based on which backend won.
- Build 셀4, then decide the paragraph-line (셀1/셀1R/셀2) scope from how 셀3/셀3R/셀4 compare
  — per the handoff doc, not a fixed count decided in advance.
- Remaining known gap, unrelated to this session's work: `llm/gemini.py`'s
  `DEFAULT_MODEL = "gemini-2.5-flash"` is deprecated 2026-10-16 — low priority, may resolve
  itself if Gemini doesn't win the pilot.

## 2026-08-09 (continued) — Pilot blocked on credit, structure/few-shot plan rewritten, demo now priority #1

**Full detail in `docs/handoff_2026-08-09_model-pilot-and-demo.md` — this entry is a pointer,
not a duplicate.**

- Gateway credit ran out completely (402 Payment Required) mid-way through re-running
  Claude — only Gemini's pilot data is valid (5 docs, 120.7s). GPT-5.4/Solar Pro3 never
  ran; EXAONE pre-emptively excluded from smoke-test evidence alone.
- Switched to literature research in place of the blocked live pilot: KMMLU rankings,
  function-calling accuracy, pricing, TTFT/throughput, and — the most decision-relevant
  finding — three independent studies showing Gemini is inherently recall-oriented and GPT
  inherently precision-oriented on classification tasks, which maps directly onto the
  screen (wants recall) vs confirm (wants precision) role split. Leaning
  screen=Gemini Flash-Lite, confirm=Claude Sonnet 5, but the Sonnet lean was flagged to the
  user repeatedly as carrying self-bias risk (this assistant is Claude) — not user-confirmed.
- **Structure/few-shot plan rewritten**, replacing the previous handoff's 8-structure+4-addon
  roster: new sequential order (①단계수 → ②청킹 → ③+④세분화×퓨샷 묶어서) plus a clean 2×3
  matrix (콜통합/콜분리 × 룰전부명시/퓨샷만/동적퓨샷) replacing the old rule-level/tool-calling
  granularity line (셀3R/셀4 dropped — folded into the few-shot axis, and 셀4's cost-control
  rationale doesn't apply once granularity stops at category level). Saved to
  `docs/experiments/structure_plan_2026-08-10.md` (Notion-paste-ready) and the shared
  artifact map is now stale relative to it.
- **Hard constraint found by reading eval-agent's actual code** (read-only): predictions
  must include a specific `rule_id` — `matcher.py` derives category from it for bucketing,
  `verifier.py` checks exact equality. No rule_id → no valid recall/precision, even for the
  few-shot-only structure variants.
- `cell3r.py` (rule-level dispatch) built and tested this session, then shelved (not
  deleted) once the above matrix superseded it.
- **User's closing instruction, now the top priority for the next session**: stop
  experimenting for now, ship one working version as an actual demo service first. Scope
  (which structure/model, what "demo" means, credit source) is NOT decided — next session
  must clarify with the user before writing code.

### Next

See `docs/handoff_2026-08-09_model-pilot-and-demo.md`'s "다음 세션이 즉시 해야 할 일" —
short version: clarify demo scope with the user, don't touch the gateway (credit is at
zero), set up eval-agent's `.env` before trying to run it.

## 2026-08-10 — Demo v1 shipped: category_screen + Claude confirm, synced to dev

### Done

- Demo config decided with the user, in order: ① 2단계형(기존 baseline과 동일) ② 위계형
  청킹(기존 유지) ③+④ 새 구조 `structures/category_screen.py` — 스크리닝은 카테고리 라벨만
  받고(룰 텍스트 없음), 정밀판정이 카테고리 내 룰 전체를 놓고 구체적 rule_id를 직접 고름.
  퓨샷은 이번엔 안 넣음(후속 작업).
- `llm/anthropic.py` 신규 — Claude 직접 클라이언트(게이트웨이 아님, 팀 자체 크레딧).
  실제 문서로 스모크 테스트하다 라이브로 잡은 버그 2개: (1) `claude-sonnet-5`는
  `temperature` 파라미터 자체를 거부함(400) — 모델별로 온오프하는 `_NO_TEMPERATURE_MODELS`로
  해결. (2) extended thinking이 기본 켜져 있어 응답이 `ThinkingBlock`만 오고 텍스트가 없는
  경우 발생 — `thinking: disabled` 명시 + 첫 텍스트 블록을 스캔하도록 수정. 결과: DOC-006
  기준 213초 → 71초.
- GitHub issue #4(팀원 요청) 대응: `Issue.related_location` 필드 추가 — LG/LF/GA(관계형 룰)만
  채워지고 나머지는 항상 None. `diff_report.py`/마크다운 출력에도 반영.
- CLI에 `--structure`, `--screen-backend`/`--confirm-backend` 추가 — 스크리닝/정밀판정에
  서로 다른 백엔드(Gemini+Claude)를 쓸 수 있게 됨.
- `sunic5-planqa/planqa-agent`의 `dev` 브랜치를 조사하다 발견: dev(그리고
  `sunic5-planqa/planqa` 백엔드에 vendoring된 사본)의 `tiers.py`가 2026-08-05 룰북 개편
  이전 매핑을 쓰고 있었음(다수 카테고리 룰이 위계에서 누락) — GitHub 이슈 #6/#7로 등록.
- `dev` 기준으로 서비스에 필요한 부분만 이식해 PR #8 제출 → 팀원 리뷰 후 merge, 그 위에
  실제 버그 수정도 받음(dedupe가 서로 다른 `related_location`을 가진 관계형 이슈를 잘못
  합치던 버그, Anthropic `APIConnectionError` 재시도 누락, `category_screen.py`가
  baseline(`models/gemini_lite/context.py`)을 import해서 additive-only 원칙을 스스로
  어겼던 것 등) — 이 수정들을 다시 `feature/review-agent`로 역포팅함.
- **로컬 `feature/review-agent`가 origin보다 10커밋 밀려있었던 것도 이번에 발견해서 push함**
  — `ABSENCE_CHECK_RULE_IDS` 수정이 그 안에 있었는데 안 올라가 있어서, 이슈 #6에서 팀원이
  "해당 수정이 없다"고 잘못 판단하게 만들었음(원격만 보고 grep했으니 당연함). push 후
  이슈에 정정 코멘트 남김.

### Next

- PR #8 merge 확인 완료. 백엔드(`sunic5-planqa/planqa`)의 vendored 사본 재동기화는 아직 안
  함 — 다음에 논의.
- 퓨샷 예시(정적 엣지케이스) 추가는 보류 상태, 필요하면 후속 작업으로.
- 이제 다시 구조/모델 실험 계획으로 복귀 예정(다음 세션에서 이어감).