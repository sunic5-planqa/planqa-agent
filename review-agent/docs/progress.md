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
