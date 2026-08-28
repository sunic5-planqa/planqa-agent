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

## 2026-08-09 — 모노레포 이전 + eval-service 알림 훅 (셀3 큐와는 별개 작업)

**위 질문(셀3 선행 작업 재개 여부)은 아직 미답변** — 이번 세션은 그거 대신, 저장소 자체를
uv workspace 모노레포로 재구성하는 별도 작업을 사용자가 명시적으로 지시해서 진행함
(`docs/adr/0001-monorepo-workspace-and-async-eval-service.md` 참고). 제안6/7 큐 순서를
건드린 게 아니라, 그보다 더 기반이 되는 저장소 구조 작업.

### Done

- 이 폴더(`review-agent/`)가 `feature/review-agent` 브랜치에서 `dev` 기반 새 브랜치의
  `services/review-agent/`로 이동. 로직 변경 없음 — 순수 경로 이동.
- `schema.py`/`rulebook.py`를 삭제하고 `packages/planqa-schemas`(워크스페이스 공유
  패키지)에서 import하도록 변경 — eval-agent 쪽 사본과 diff해보니 import 경로 한 줄 빼고
  진짜 100% 동일한 코드였음.
- `eval_service_notify.py`(신규): `cmd_review`가 결과를 다 쓰고 나면 `services/eval-service`
  의 `/evaluate-async`로 fire-and-forget POST (백그라운드 스레드, 실패해도 로그만 남기고
  무시, `EVAL_SERVICE_URL` 안 걸려있으면 그냥 no-op). `cmd_experiment`/benchmark 쪽에는 안
  걸음 — ablation 실험 트래픽까지 eval-service에 흘려보낼 이유가 없어서.
- 86/86 테스트 통과 (기존 84 + notify 훅 신규 2개).

### Next

- 위 미답변 질문은 여전히 열려있음 — 다음 세션에서 확인 필요.
- `planqa-backend`에 벤더링된 사본(`qa_engine/review_agent/`)에는 이 notify 훅이 아직 없음 —
  실서비스에 반영하려면 그쪽 ADR 0001의 기존 재동기화 절차를 별도로 밟아야 함.

## 2026-08-09 — Re-synced TIER_CATEGORIES from feature/review-agent (GitHub 이슈 #6/#7)

`feature/review-agent`에서 이 폴더를 `dev`로 복사해온 뒤, 그 브랜치에 `tiers.py`의
`TIER_CATEGORIES`(위계별 룰 카테고리 매핑)가 8/5 룰북 개편 이전 값으로 굳어있던 버그를 고친
커밋(`c04825f fix: correct TIER_CATEGORIES to match rulebook §2`, pforu)이 새로 올라왔는데
`dev`엔 반영이 안 돼 있었음 — GitHub 이슈 #6(이 레포)/#7(`planqa-backend` 벤더링 사본, 별도
레포라 여기선 손 안 댐)로 리포트됨.

### Done

- `tiers.py`의 `TIER_CATEGORIES`를 `feature/review-agent`의 고쳐진 값 그대로 재동기화
  (문서 6→7개, 논리단위 5→8개(전체), 문단 2→7개, 문장 2→5개 카테고리 — 이전엔 문단 위계가
  7개 중 2개만 체크하고 있었음). `rules_for_tier()`는 이 dict에서 순수하게 파생되므로 다른
  코드 변경 불필요.
- `test_tiers.py`에 `test_tier_categories_matches_rulebook_section_2` 이식 (upstream이
  같은 커밋에서 추가한 회귀 테스트).
- 87/87 테스트 통과 (기존 86 + 신규 1).

### Notes

- 이슈 #6 본문이 "`feature/review-agent`에 `ABSENCE_CHECK_RULE_IDS`까지 포함된 버전이
  있다"고 언급했는데, 실제 `feature/review-agent`(fix 커밋 `c04825f` 포함, 그 이후 커밋까지
  확인)엔 `ABSENCE_CHECK_RULE_IDS`가 존재하지 않음 — grep으로 0건 확인. §1의 "부재 확인형
  (LG-01/TC-02는 항상 문서 위계에서만 체크)" 예외는 upstream에도 아직 구현 안 된 상태.
  이번엔 실제로 존재하는 `TIER_CATEGORIES` 수정만 재동기화하고, 이 예외 로직은 새로
  설계해야 하는 별개 작업이라 손 안 댐 — 이슈에 코멘트로 남겨둠.
- upstream 기록 경고 그대로: 이 수정 이후로 review-agent를 실제로 돌리면(특히 문단/문장
  위계) 과거 어떤 벤치마크 숫자보다 이슈가 더 많이 나올 것 — 버그가 있어서가 아니라 이제
  진짜로 검토해야 할 카테고리를 다 검토하기 때문.

### Next

- §1 "부재 확인형" 예외(LG-01/TC-02 항상 문서 위계 전용)는 upstream에도 없는 별개 설계
  작업 — 다음에 review-agent 팀이 다룰 것.
- `planqa-backend`의 벤더링 사본(이슈 #7)은 별도 레포라 여기서 안 고침.

## 2026-08-10 — category_screen의 4개 위계 병렬 실행 (셀3 방향과 별개, 순수 속도 개선)

Haiku 스크리닝/Sonnet 정밀판정으로 라이브 검증했을 때 문서 1건에 호출당 ~80초, 4개 위계 x
스크리닝+정밀판정 순차 실행이라 최대 12분까지 걸렸음 — 사용자 요청으로 병렬화.

### Done

- `category_screen.review_document()`: Document/Logical Unit/Paragraph/Sentence 4개 위계는
  이미 계산된 `global_context`에만 의존하고 서로 독립적이므로, `ThreadPoolExecutor`로
  동시 실행하도록 재작성. baseline(`pipeline.py`, 제안5)은 손 안 댐 — ablation 비교 기준점
  고정 유지.
- **스레드 안전성 문제 발견 및 해결**: `instrumentation.record_call()`은 `len(llm.usage)`
  전/후 diff로 각 호출의 `CallStats`를 귀속시키는데, 4개 위계가 같은 `screen_llm`/
  `confirm_llm` 인스턴스를 동시에 호출하면 이 diff가 레이스 컨디션에 걸림(한 위계의 호출이
  다른 위계 것으로 잘못 귀속되거나 누락될 수 있음). 잠금(lock)으로 그 부분만 감싸는 방식은
  네트워크 호출 자체가 잠금 밖에 있어야 병렬화 의미가 있는데, `llm.usage`에 append하는
  시점은 `complete_json` 내부라 잠금으로 정확히 분리할 수 없음 — 결국 위계마다 독립된
  client 인스턴스가 필요하다고 결론.
- `LLMClient`(공통 인프라, baseline 전용 아님)에 `clone(*, tier=None) -> LLMClient` 메서드
  추가 — 기본 구현은 `type(self)(model=self.model, temperature=self._temperature)`로 각
  백엔드(Gemini/Ollama/Anthropic)가 env에서 credential을 새로 읽는 방식 그대로 재사용.
  `review_document`는 위계별로 `screen_llm.clone(tier=level)`/`confirm_llm.clone(tier=level)`
  로 독립 클라이언트를 만들고(메인 스레드에서 순차적으로, 스레드풀 시작 전), 각 위계의
  스레드가 끝나면 그 클론의 `.usage`를 원본 client 객체에 다시 merge — `cli.py`의
  run-stats가 `screen_llm.usage`/`confirm_llm.usage`를 직접 읽으므로 이 merge가 없으면
  최종 통계가 과소 집계됨.
- **테스트 인프라도 같이 손볼 수밖에 없었음**: 기존 `ScriptedLLM` 기반 6개 테스트는
  "호출 순서 == 위계 순서"를 전제로 응답 리스트를 인덱스로 스크립트했는데, 진짜 동시
  실행에서는 어느 위계가 먼저 호출을 마치는지 보장이 없어 이 전제가 깨짐(스레드
  스케줄링에 따라 flaky해질 위험). `ScriptedLLM`에 `tier_responses`(TIER_ORDER 정렬
  리스트)와 `clone(tier=)` 지원을 추가해 위계 정체성 기반으로 라우팅하도록 재설계, 6개
  테스트를 위계-키 방식으로 재작성 (`test_review_document_isolates_a_single_tier_failure`의
  "첫 호출이 실패" 가정도 "Document 위계 호출이 실패"로 tier-aware하게 수정).
- 109/109 테스트 통과, `test_category_screen.py` 단독 5회 반복 실행으로 flaky 여부 확인
  (전부 그린).
- 라이브 검증(DOC-001, category_screen, Haiku 스크리닝/Sonnet 정밀판정, Anthropic 백엔드):
  2회 실행 50.4초/58.4초 (직전 세션의 동일 설정 순차 실행 대비 큰 폭 단축). `review.json`의
  `stats` 확인 — `screen.call_count=4`, `confirm.call_count=5`(context 1 + 위계 4),
  `by_tier`에 4개 위계 각각 정확히 2콜(스크리닝+정밀판정)로 집계됨 — usage merge-back이
  정확히 동작함을 실측으로 확인. 첫 실행에서 Sentence 위계가 JSON 파싱 실패로 1건 빠졌지만
  기존에도 있던 위계별 격리(`tier_errors`) 덕에 나머지 3개 위계 결과(12건)는 정상 반환 —
  재실행 시 실패 없이 14건 반환되어 동시성 버그가 아니라 기존에도 있던 모델 응답 flaky함
  이었음을 확인.

### Next

- `pipeline.py`(baseline)는 이번에 손 안 댐 — 필요하면 별도로 논의.
- 셀3(카테고리별 독립 호출 병렬 실행) 선행 작업 재개 여부는 여전히 미답변으로 남아있음.


## 2026-08-10 (계속) — 2차 데모(`sync/review-agent-demo-2`): `bundled_screen_hybrid`로 구조 교체

### Done

- `feature/review-agent` 브랜치(별도 저장소, 레포 루트의 `review-agent/`)에서 구조/모델
  조합 실험(판정 단계 수·청킹 방식·세분화×퓨샷 콘텐츠)을 마친 결과, `bundled_screen_hybrid`
  (2단계 screen=Gemini flash-lite→confirm=Claude Sonnet, 콜통합, 룰텍스트+퓨샷 예시)가
  최종 채택 구조로 확정됐다. `category_screen`(1차 데모 구조)을 대체.
- **`feature/review-agent`에서 이 브랜치엔 없던 엔진 개선을 이식**(둘 다 import 경로만
  `planqa_review.{schema,rulebook}` → `planqa_schemas.{schema,rulebook}`로 교체):
  `document.py`(`resolve_reported_level`/`_LEVEL_COARSENESS` — 위계 상향만 신뢰),
  `tiers.py`(`ABSENCE_CHECK_RULE_IDS`), `instrumentation.py`(`isolate_client`/`merge_usage`),
  `llm/base.py`(JSON 복구 정규식 — 이스케이프/트레일링 콤마로 인한 콜 실패 방지),
  `llm/anthropic.py`(`cache_prefix` 지원 + 빈 응답 재시도), `llm/gemini.py`
  (`DEFAULT_MODEL`을 `gemini-2.5-flash`→`gemini-flash-lite-latest`로 — 전자는 신규
  사용자 404 확인됨), `dedupe.py`/`verifier.py`/`pipeline.py`/`diff_report.py`(import만).
- **PR 전 보완 2건**(`bundled_screen_hybrid.py`에 반영, 근거는 `feature/review-agent`의
  `docs/share_planning_2026-08-10.md` + 이후 실험 결과):
  1. GA/부재확인 문서 pass 프롬프트에 "먼저 목표/KPI 문장을 모으고, 별도로 제약/역량
     문장을 모아서 대조하라"는 단계적 지시 추가(screen/confirm 둘 다) — 시야는 있는데
     추론 깊이가 부족해서 놓친 사례(GA-01) 대응.
  2. `_paragraph_and_document_rules`에서 GA뿐 아니라 **LG·LF 카테고리 전체**를 문서 전체
     pass로 이동 — 이 두 카테고리는 정의상(`_RELATIONAL_CATEGORIES`) 두 위치 간 관계
     오류인데 문단 단위로 쪼개져 있어 애초에 먼 섹션끼리 비교할 시야가 없었음(LG-05 사례).
     golden 데이터셋에서 LG-05/GA-01 둘 다 Level="Document"로 라벨링돼있어 이 배치가
     golden 기대와도 일치함을 확인.
  3. 파일럿 재검증(API 비용)은 스킵 — 로컬 유닛테스트만으로 확인.
- **구조/파일 정리**: `structures/`는 `bundled_screen_hybrid.py`+`fewshot_bank.py`만
  남기고 `category_screen.py`를 제거, `structures/__init__.py`도 이 구조 하나만 등록.
  `cli.py`의 `experiment` 서브커맨드(및 그게 필요로 하던 `benchmark.py`/`experiment.py`/
  `scoring.py`)를 제거 — ablation 도구는 `feature/review-agent`에 남기고, 이 데모는 실사용
  경로(`review` 서브커맨드)만 노출. `notify_eval_service` 연동은 그대로 유지.
  이제 안 쓰는 `openpyxl` 의존성도 `pyproject.toml`에서 제거.
- 114개 테스트 전체 통과(신규 venv, `PYTHONPATH`로 `planqa_schemas` 연결).

### Next

- **push/PR 보류 — 사용자 명시적 승인 대기 중.** 계획 승인과 PR 승인은 별개로 확인받기로
  합의함.
- eval-service의 실시간 채점도 기본값이 단일 LLM 판정(`EVAL_SERVICE_ENSEMBLE` 미설정)이라
  `tools/eval-agent`에 올린 이슈와 같은 신뢰도 문제가 있음 — 이 PR 범위 밖(다른 서비스)
  이라 손 안 댐, 별도로 공유할 만한 내용.
- 알려진 한계(문서화만, 이번엔 안 고침): AE-03 과탐지 잔존 위험, 위계 과대확장 미검증 —
  프로덕션에서 eval-service로 관찰 권장.

## 2026-08-10 — bundled_screen_hybrid의 2개 pass 병렬화

PR #21 머지 직후, `bundled_screen_hybrid.review_document()`가 Paragraph/Document 2개
pass를 순차 실행하고 있던 걸 발견(category_screen.py 삭제로 지난번 병렬화 작업도 같이
사라짐) — 사용자 요청으로 병렬화.

### Done

- `_run_pass`를 새로 뽑아서 Paragraph/Document 2개 pass를 `ThreadPoolExecutor`로 동시
  실행. 팀원이 이미 만들어둔 `instrumentation.isolate_client`/`merge_usage`(cell3.py용으로
  선제적으로 준비돼 있었으나 아직 아무 데도 안 쓰이고 있었음)를 그대로 활용.
- **`isolate_client`에 진짜 스레드 안전성 버그 발견**: 기존 구현은 `copy.copy(llm)`만
  쓰는데, `ScriptedLLM`(테스트 더블)엔 커스텀 `__copy__`가 없어서 얕은 복사가 `_responses`
  iterator를 그대로 공유 — 두 pass가 같은 iterator에서 경쟁하면 GA-01처럼 Document
  전용으로 설계된 룰의 스크리닝 응답이 Paragraph pass로 잘못 갈 수 있음. 8회 반복 실행은
  전부 통과했지만(GIL+무지연 fake 호출이라 순서가 거의 항상 보존됨), 이건 안전 보장이
  아니라 우연 — category_screen.py 때와 같은 함정.
- `isolate_client(llm, *, key=None)`에 선택적 `key` 파라미터 추가 — 실제 백엔드는
  무시(기존 `copy.copy()` 그대로), `llm.isolate(key)`가 정의돼 있으면 그걸 우선 호출.
  `bundled_screen_hybrid._run_pass`는 `key=level`로 호출.
- `ScriptedLLM`(conftest.py)에 `keyed_responses: dict[Any, list[Any]]` + `isolate(key)`
  추가(예전 category_screen 전용이었던 `tier_responses`/`clone(tier=)`를 범용 dict 기반으로
  일반화 — `TIER_ORDER` 의존성 제거, 어떤 키든 사용 가능). 6개 테스트를 `Level.PARAGRAPH`/
  `Level.DOCUMENT` 키 기반으로 재작성.
- 120/120 테스트 통과, `test_bundled_screen_hybrid.py` 15회 반복 실행으로 flaky 여부 확인.
- 라이브 검증(DOC-001, Haiku 양쪽 다): 55.4초 — `by_stage` 합산 103.6초가 벽시계 55.4초로
  압축됨, 실측 약 1.9배 단축.

### Next

- 여전히 category_screen 때와 마찬가지로, 확장 가능한 concurrency 인프라(isolate_client
  + key)는 이제 review-agent 공통 자산 — 다음에 pass/tier가 3개 이상인 구조가 나오면
  바로 재사용 가능.

## 2026-08-10 (마무리) — main 승격 전 코드 리뷰, 진짜 버그 2건 + 강화 2건

dev→main 승격 전 요청받은 코드 리뷰. 5건 중 4건 조치(GIL 관련 1건은 현재 배포 환경에서
실제 위험 없어 문서화만).

### Done

- **진짜 버그**: `GeminiClient._current`(다중 키 라운드로빈 인덱스)가 평범한 int라
  `isolate_client`의 `copy.copy()`가 값으로 복사 — 동시 실행되는 두 pass가 각자 독립된
  라운드로빈 인덱스를 갖게 돼서, 한쪽 pass가 429로 배운 "이 키는 방금 막힘" 정보가
  다른 pass나 원본 client에 전혀 전달 안 됨(`merge_usage`는 `.usage`만 병합, 이 상태는
  안 건드림). `_current`를 공유 mutable cell(`[0]`)+`threading.Lock`으로 변경 —
  `copy.copy()`가 자연스럽게 레퍼런스를 공유하므로 모든 isolated 복사본과 원본이 진짜로
  같은 라운드로빈 상태를 본다. 직접 실행으로 공유 확인(`isolate_client`로 만든 두 복사본이
  같은 `_current` 객체 식별성 공유, 한쪽에서 회전하면 원본·다른 복사본에도 즉시 반영).
  신규 `test_llm_gemini.py`(이 백엔드 첫 테스트 파일) 2개로 회귀 고정.
- **진짜 버그**: `bundled_screen_hybrid._run_pass`에서 `isolate_client()` 호출이
  `try` 블록 **밖**에 있어서, 실패 시 `review_document()` 전체가 크래시(그 pass만
  tier_error로 격리되는 게 아니라). `isolate_client()` 호출을 `try` 안으로 이동,
  `finally`에서 `isolated_screen`/`isolated_confirm`이 `None`이 아닐 때만 `merge_usage`.
- **강화**: `ScriptedLLM.isolate()`가 `keyed_responses` 없이 key만 받으면 조용히 `self`를
  반환해서 concurrent race를 재도입할 위험 — `ValueError`로 명확히 실패하도록 변경.
  신규 테스트로 `result.tier_errors`에 메시지가 잡히는지 확인(isolate_client 실패도
  다른 pass 실패와 동일하게 tier_error로 격리되므로, 예외가 밖으로 안 나가는 게 맞는
  동작 — 테스트도 그에 맞춰 작성).
- **강화(경미)**: active pass가 1개뿐일 때 `ThreadPoolExecutor` 생성 자체를 스킵하고
  `_run_pass`를 직접 호출 — 병렬화할 게 없을 때 스레드풀 오버헤드 제거.
- GIL 원자성 가정(`merge_usage`)은 pre-existing이고 표준 CPython 배포 환경에선 실제
  위험 없어서 손 안 댐 — free-threaded 빌드 전환 시에만 재검토 필요.
- 123/123 review-agent 테스트 통과(120 + 3 신규), `test_bundled_screen_hybrid.py`/
  `test_llm_gemini.py` 10회 반복으로 flaky 여부 확인. eval-agent 84, eval-service 19
  영향 없음 — 총 226/226.

## 2026-08-11 — 카테고리 오분류(GA↔TC, TC↔MI) 프롬프트 보강 (이슈 #26)

sunnic-backend 알파테스트 실사용 피드백(이슈 #26, 사용자 본인이 작성)에서 4가지 문제가
보고됨 — 이번엔 그 중 프롬프트만으로 고칠 수 있는 처음 두 개(카테고리 경계 혼동)만 대응.

### Done

- **원인 진단**: `_hybrid_block`은 룰별 `rule_id (category_label): rule.text`만 렌더링하고
  카테고리 자체의 "한줄정의"(`RuleDef`에 애초에 없는 필드)는 안 보여줌 — GA("상위 목표와
  세부 내용의 정합성")와 TC("동일 개념을 다른 표기로 사용")의 카테고리 정의 없이 "두 문장이
  다르다"는 표면 패턴만 보면, 모델이 내용 충돌(GA)과 표기 불일치(TC)를 헷갈리기 쉬움.
  TC↔MI는 `global_context`가 목적/제약/KPI 요약이지 용어집이 아니라서, 이전에 나온 용어의
  재표현을 "새 개념"으로 오인해 MI로 새는 것으로 추정.
- `_CATEGORY_BOUNDARY_NOTES` 신설 — GA vs TC(주장 자체가 다르면 GA, 표현만 다르면 TC),
  TC vs MI(용어집이 아니므로 "요약에 없음"이 "진짜 새 개념"의 증거가 아님, 재표현 가능성
  있으면 TC 우선) 두 단락. `_SCREEN_HYBRID_SYSTEM`(rule_id 최초 배정 지점)과
  `_CONFIRM_HYBRID_SYSTEM`(screen이 잘못 배정한 rule_id를 최소한 violated=false로
  걸러내는 이중 방어) 양쪽에 삽입 — 프롬프트 텍스트만 수정(이슈 코멘트에서 요청한 "재벤더링
  비용 최소" 방식), 시그니처/모듈명/LLMClient 계약 변경 없음.
- 123/123 테스트 통과 — 프롬프트 텍스트 변경이라 기존 테스트 커버리지엔 영향 없음.
  사용자 요청으로 라이브 검증은 생략(재현 문서가 없어 정밀 비교 불가, 비용 대비 확신도
  낮음) — 다음 재벤더링/실사용 때 관찰.

### Notes

- 이슈 #26의 나머지 두 사례는 이번에 손 안 댐:
  - 사례3(재현율 저조, GA×2/MI×1/TM×1 전부 미탐지) — 재현 입력이 없어 정밀 진단 불가.
    카테고리 경계 보강이 간접적으로 도움될 수도 있으나 확인 안 됨.
  - 사례4(같은 문서 재검토 시 비결정성 — 1차에 잡힌 AE 위반이 2차에 안 잡힘) — 이미
    `temperature=0.0` 기본값인데도 발생한 거라면 API 제공자 자체의 완전결정성 한계이거나
    문서의 다른 부분 변경이 같은 청크의 후보 배치/주의를 바꿨을 가능성 — 근본 해결하려면
    `--judge-ensemble`류 다중 샘플 합의 같은 더 큰 구조 변경이 필요해 보임, 이번 스코프 밖.

### Next

- 사례3/4는 재현 가능한 입력이 확보되면 다시 볼 것.
- 더 근본적인 대안(카테고리별 "한줄정의"를 `RuleDef`에 파싱해서 넣기)은 `packages/
  planqa-schemas`(eval-agent와 공유)까지 건드리는 더 큰 변경이라 이번엔 보류 — 이번
  프롬프트 보강으로도 부족하면 다음 후보.

## 2026-08-11 (계속) — related_original_text 필드 추가 (이슈 #29)

sunnic 알파테스트 피드백: 관계형 카테고리(LG/LF/GA)의 두 번째 위치(`related_location`)가
라벨 문자열뿐이라 프론트에서 그 위치 문구를 편집 제안할 수 없다는 요청. 이슈 #26 코멘트의
비용 분류로는 "중간"(순수 프롬프트도 시그니처 변경도 아닌, 필드 하나 추가) 케이스.

### Done

- `packages/planqa-schemas`(eval-agent와 공유)의 `Issue`에 `related_original_text: str |
  None = None` 추가 — `related_location`과 같은 자리·같은 조건(LG/LF/GA일 때만 채워짐).
  `slots=True` frozen dataclass에 기본값 있는 필드 추가라 순수 additive, planqa-schemas
  8/8·eval-agent 84/84 그대로 통과(eval-agent는애초에 `related_location`도 안 읽음 —
  review-agent 전용 프레젠테이션 필드).
- `_CONFIRM_HYBRID_SYSTEM`: related_location을 요청하는 자리에 "그리고 original_text와
  같은 방식으로 그 위치의 정확한 인용문도(`related_original_text`) 함께 달라"는 지시 추가,
  JSON 스키마에도 필드 추가.
- `_confirm_pass`: `related_location`과 같은 조건문 안에서 `related_original_text`도 같이
  파싱해서 `Issue` 생성자에 전달.
- `diff_report.py`: `issue_dicts`(JSON 출력)와 마크다운 렌더링(`- 관련 위치 원문: ...`)
  양쪽에 반영 — review.json에 실제로 노출되도록.
- 신규 테스트 2개: 관계형 카테고리에서 실제로 채워지는지, 비관계형 카테고리(MI)에서는
  모델이 채우려 해도 무시되고 둘 다 None인지(defensive, 기존 related_location 테스트
  패턴 그대로 확장).
- 라이브 검증(DOC-001, Haiku 양쪽): LG-05/LF-04 두 건에서 `related_original_text`가
  실제로 채워지는 것 확인 (예: "P2 | GA 스크립트 삽입 및 이벤트 트래킹 설정 | 개발+기획").
- 227/227 테스트 통과(review-agent 124 + eval-agent 84 + eval-service 19).

## 2026-08-28 — 부재확인형 확장 포인트 (planqa-backend 팀 룰 3단계 분류 지원)

planqa-backend가 팀 룰을 문단형/관계형/부재확인형 3가지로 자동 분류해서 QA에 적용하려는데,
관계형은 기존 `category in {LG,LF,GA}` 판정을 그대로 재사용(팀 룰 category를 내부적으로
"GA" 등으로 세팅)하면 되지만, 부재확인형은 `ABSENCE_CHECK_RULE_IDS`가 `{"LG-01", "TC-02"}`
딱 2개 rule_id만 인식하는 폐쇄 집합이라 재사용이 불가능했음 — 확장 포인트 추가.

### Done

- `_paragraph_and_document_rules(rulebook, extra_absence_check_rule_ids=frozenset())` —
  호출자가 넘긴 rule_id도 `ABSENCE_CHECK_RULE_IDS`에 합쳐서 판정(`|` 합집합). 기본값이 빈
  frozenset이라 기존 호출부(review_document 안쪽 자기 자신 포함) 전부 영향 없음.
- `review_document(..., *, extra_absence_check_rule_ids: frozenset[str] = frozenset())` —
  키워드 전용 + 기본값, 위 함수까지 그대로 전달.
- 신규 테스트: 원래 문단형인 MI-01을 `extra_absence_check_rule_ids={"MI-01"}`로 넘기면 실제로
  Document 위계로 디스패치되는지 확인.
- 125/125 review-agent 테스트 통과(기존 124 + 신규 1), planqa-schemas 8/8·eval-agent 84/84
  회귀 없음.

### Next

- planqa-backend 쪽에서 팀 룰 분류(LLM 호출) 결과 중 "부재확인형"으로 판정된 rule_id들을 모아
  이 파라미터로 넘기는 실제 배선 작업.