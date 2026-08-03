# Progress Log

## 2026-08-02 — Project scaffold + full core pipeline (Parser through Reporter)

### Done

- `uv` project scaffold (`pyproject.toml`, `src/planqa_eval/`), deps: openpyxl, python-dotenv,
  httpx, google-genai, pytest.
- Parsers (`parsers/`): `golden.py` (re-reads `golden dataset` sheet fresh every call — never
  hardcodes the doc list, currently 17 docs / 19 rows of 41 total), `review_sheet.py`
  (discovers "Review*" sheets dynamically — Review5/6 are empty, handled without error),
  `review_json.py` (review-agent JSON → common schema, contract documented in
  `docs/adr/0001-review-agent-output-contract.md` since no real sample exists yet),
  `documents.py` (Documents sheet + `data/source_documents/*.md` loader).
- `rulebook.py`: parses `rulebook_v1.0.md` into `RuleDef`s — 8 categories, 42 rules, and the
  §3 reference-exception rule set (`LG-04, TC-02, AE-01, GA-03`), all derived from the file
  rather than hardcoded. Had to explicitly cut off the trailing "채워야 할 개수/담당자"
  authoring-tracking table, which reuses every Rule ID and was silently overwriting real rule
  definitions before the fix.
- Core pipeline: `prefilter.py` (buckets by doc+category), `llm/` (Gemini + Ollama/local-Qwen
  backends behind one `LLMClient` interface, picked via `PLANQA_LLM_BACKEND` — Claude
  deliberately left out of scope for now, only add it if the 2-1 gate fails on the cheap
  backend), `matcher.py` (N:M LLM matching per doc/category bucket), `verifier.py` (exact
  Rule ID/Level check + exception-condition re-check for the 4 reference-exception rules),
  `judge.py` (4-axis 1-5 rubric), `new_rule_triage.py` (FP-candidate → false_positive /
  new_rule_candidate / human_review), `aggregator.py` (recall/precision by category and
  level, human-baseline comparison, new-rule counts kept separate from precision),
  `reporter.py` (JSON + Markdown, per-document detail).
- Harnesses: `harness/confidence_gate.py` (2-1: stratified sample by Level×category×
  exception-eligibility, human-blind-label template generation, pass/fail against the
  90%/80%/100% thresholds) and `harness/full_eval.py` (2-2: refuses to run without a passing
  gate report unless `--force`). CLI: `planqa-eval gate` / `planqa-eval evaluate`.
- 35 tests passing (`uv run pytest`), covering rulebook parsing, all parsers, prefilter,
  matcher, verifier (including the DOC-006 AE-01 case — the rulebook's own counter-example of
  a citation that must NOT count as an exception), and aggregator counting rules.
- ADR: `docs/adr/0001-review-agent-output-contract.md`.

### Notes

- Verifier's reference-exception check (`has_valid_reference_exception`) is a deterministic
  heuristic (citation + flagged phrase must share a markdown paragraph block), not an LLM
  call, per the spec's "Verifier (코드)" constraint. It's validated against the one real case
  currently in the golden dataset (DOC-006 AE-01) but the other three exception rules
  (LG-04/TC-02/GA-03) have zero golden rows yet — revisit if/when real cases appear and the
  heuristic gets something wrong.
- Nothing has actually been run against a live LLM yet — no `GEMINI_API_KEY`/Ollama installed
  on this machine. Code is structurally verified with a scripted fake `LLMClient` in tests.

### Next

- Real review-agent output JSON sample — validate/adjust `parsers/review_json.py` against it
  once available.

## 2026-08-02 — Real Gemini API validation, multi-key rotation, README

### Done

- Added `data/sample_review_output.json`: a stand-in review-agent output built from the golden
  dataset (since no real review agent exists yet), deliberately seeded with one omitted issue
  (DOC-006 AE-01 — to exercise the exception-condition re-check on a real run), one wrong-Level
  prediction (DOC-003 AE-03: Sentence→Paragraph), and two issues with no golden counterpart (to
  exercise new-rule triage).
- Ran the full pipeline against it with the real Gemini API (`run_pipeline` end-to-end, not the
  fake `LLMClient`): recall/precision 89.5% (18/19), DOC-006 AE-01 correctly resolved to
  `excused=False` (matches the rulebook's own counter-example and the unit test), the seeded
  Level mismatch was caught, and the two seeded extra issues got sensible LLM triage verdicts
  (`new_rule_candidate` and `false_positive` respectively).
- Hit two real free-tier constraints along the way and fixed the first:
  - `gemini-2.0-flash` had **zero** free-tier quota on this account/key — switched
    `llm/gemini.py`'s `DEFAULT_MODEL` to `gemini-2.5-flash`, which has an actual (if small)
    free tier.
  - `gemini-2.5-flash` free tier is rate-limited (as low as 5 requests/minute, and as low as
    20 requests/day on some model/key combos) — a single pipeline run easily exceeds this since
    Matcher/Judge/triage each fire their own LLM call. Added 429 retry-with-backoff (honors the
    API's `retryDelay` when present) plus **multi-key round-robin**: `GEMINI_API_KEYS`
    (comma-separated) cycles through several keys/projects before falling back to sleep-and-
    retry, multiplying the effective daily quota. `GEMINI_API_KEY` (single) still works.
- Wrote `README.md` (setup, `.env` config, how to run `gate`/`evaluate`, current status) — there
  was previously just a title line.
- Added `tests/test_gemini_client.py` for the new `_load_api_keys` precedence/parsing logic.
- Batched `judge_matches()` and `triage_fp_candidates()` into one LLM call per run instead of
  one per matched pair / FP candidate (Matcher was already batched N:M per document×category
  bucket, so left as-is — current data has ~1 category per doc, so bucket-merging wouldn't cut
  call count anyway). Each batch call is indexed (`{"index": i, ...}`); if the model drops an
  index from its response, only that one item falls back to the original single-item call
  rather than failing the whole batch. Re-ran the same sample end-to-end afterward: same
  DOC-006 AE-01 exception result, same recall, finished well under the previous run's time
  (no longer needed to background it) — confirms the call-count reduction is real.

### Notes

- The daily-quota constraint is severe enough that even modest pipeline runs (a few dozen
  issues) can burn through a single free key's daily budget. Multi-key rotation is a workaround,
  not a fix — if this becomes a recurring blocker, revisit Ollama (no quota at all, per
  memory: planqa-model-selection-policy) or enabling billing on the Gemini project.

### Next

- Real review-agent output JSON sample — validate/adjust `parsers/review_json.py` against it
  once available.
- Fill in a real 2-1 gate human-label file and confirm the gate actually passes/fails
  meaningfully (only tested with fake `LLMClient` scripted agreement so far).

## 2026-08-02 — Verified the Ollama/Qwen backend end-to-end

### Done

- Installed Ollama (`brew install ollama`, `brew services start ollama`) and pulled
  `qwen2.5:1.5b` (~1GB) to actually exercise `llm/ollama.py`, which had only ever been
  structurally reviewed, never run.
- Ran the same `data/sample_review_output.json` pipeline against it: recall/precision 84.2%
  (18/19 matched), no quota issues at all (fully local).
- Real finding, not a bug: DOC-006 has two golden issues (AE-01, AE-03) at the same location
  ("2-1~2-4 전반"), a genuine 2:1 matching problem for that bucket. Gemini matched them
  correctly (missed AE-01). `qwen2.5:1.5b` matched them the other way around (missed AE-03
  instead) — a real quality difference between backends on an ambiguous case, exactly what
  the 2-1 confidence gate exists to catch (memory: planqa-model-selection-policy).
- Changed `llm/ollama.py`'s `DEFAULT_MODEL` from `qwen2.5:7b` (never actually pulled/tested)
  to `qwen2.5:1.5b` (the one actually verified), per user's choice to standardize on the
  smaller model rather than also downloading the untested 4.7GB 7b variant.
- Updated `README.md` with the Ollama install/pull steps and the Ollama results.

### Next

- Real review-agent output JSON sample — validate/adjust `parsers/review_json.py` against it
  once available.
- Fill in a real 2-1 gate human-label file and confirm the gate actually passes/fails
  meaningfully (only tested with fake `LLMClient` scripted agreement so far).
- If Qwen is ever considered for real (non-testing) use, the DOC-006-style ambiguous-match
  weakness found here means it should not be trusted without first passing the 2-1 gate on a
  stratified sample that includes multi-issue-per-location cases like this one.
