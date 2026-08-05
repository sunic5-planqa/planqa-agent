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

## 2026-08-05 — Confirmed data refresh (rulebook revision + expanded golden set)

Team confirmed the data in `~/Downloads/SuniC 10팀/` as the new source of truth, replacing the
2026-08-02 snapshot.

### Done

- **Rulebook**: 40→41 rules. Notable content changes: exception-target rule set moved from
  `{LG-04, TC-02, AE-01, GA-03}` to `{LG-03, TC-02, AE-01, GA-03}` (LG rules renumbered/merged);
  review calls went from 3 to 4 (문단 위계 gets its own call now); RD/GA tables dropped their
  per-rule fixed "위계" column entirely. None of this needed a code change beyond one parser fix
  below — confirms the "derive everything from the file, never hardcode" design held up under a
  real revision, not just a hypothetical one.
- **Golden dataset**: replaced `qa_dataset_2026-08-02.xlsx` with `qa_dataset_2026-08-05.xlsx`
  (19→131 issues, 17→38 unique documents of 41 total; Review1-4 also grew 28/28/49/73→
  56/59/79/73; Review5/6 still empty). Updated `cli.py`'s `DEFAULT_XLSX` and the test fixture to
  match.
- **Source documents**: added DOC-021 through DOC-040 (20 new files; three of them — DOC-036/
  037/038/039/040 — were `.txt` in the source drop, normalized to `.md` for consistency).
  DOC-001 through DOC-020 content is byte-identical to what we already had, confirmed by diff
  before touching anything.
- **Parser bug found and fixed**: `RD-01`'s exception text in the new rulebook contains a literal
  embedded blank line (a Notion paste artifact), which broke `rulebook.py`'s one-row-per-line
  assumption and silently dropped the rule entirely (`rulebook.rule("RD-01")` returned `None`).
  Added `_repair_wrapped_table_rows()`: merges a table line that opens with `|` but doesn't
  close with `|` forward into subsequent lines until one does, before row-matching runs. Verified
  it doesn't false-positive on adjacent non-table content (e.g. the new "TC 내부 규칙" bullet
  right after the TC table). Regression test added.
- Updated `tests/test_rulebook.py`'s three assertions that were pinned to old-rulebook specifics
  (old exception-rule set, a specific rule's exact "-"-exception, and RD/GA fixed levels — the
  latter rewritten to assert *no* rule has a fixed level now, since that column is gone) — these
  were fixture-accuracy failures, not regressions; the parser was already reading the new file
  correctly except for the RD-01 bug above.
- All 47 tests pass against the new fixtures.

### Known gap

- **DOC-000 has no usable source text.** `01_Raw_Documents/DOC000_제목.docx` — the only file for
  it — is a genuinely empty Word document (confirmed by inspecting `word/document.xml` directly:
  one empty paragraph, no body text). DOC-000 accounts for **76 of 131 golden issues (58%)**, so
  this is a real gap, not a rounding error. `load_source_text()` already returns `None`
  gracefully for it (no crash; `has_valid_reference_exception()` correctly treats missing source
  as "not excused" rather than guessing) but any DOC-000 exception-condition check is running
  without real document context until the actual source text is found.
- Explicitly did **not** pull in `01_Raw_Documents/보미_raw_datasets/` or `승현_raw_datasets/` —
  both reuse the DOC-001..012/030-043 ID range for entirely different documents than the main
  set, and the current golden dataset's doc_ids don't reference them. Revisit if the golden
  dataset ever expands to cite those IDs.

### Next

- Find DOC-000's real source text (ask the team where the original — probably 은성's practice
  document referenced by the `DOC-000-ES-*` issue IDs in Review1 — actually lives) and add it to
  `data/source_documents/`.
- Real review-agent output JSON sample — still the biggest open item, unchanged from before.

## 2026-08-05 — First real review-agent output sample, end-to-end against it

Got a real sample (`review.json`, 6 issues, DOC-001 only) — the biggest open item from every
prior session's Next list.

### Done

- Confirmed the assumed schema from ADR 0001 against real data: field names matched exactly,
  including `issue_id`, plus `original_text`/`rationale`/`fix_direction` which the ADR hadn't
  committed to but the golden/review-sheet parsers already expected. Updated
  `parsers/review_json.py` to capture those three (Judge reads `fix_direction`; it was silently
  `None` for every real prediction before this). ADR 0001 updated to Accepted with this
  confirmation logged.
- Added `data/review_agent_sample_output.json` (the real sample, copied in) alongside the
  existing synthetic `data/sample_review_output.json` — the synthetic one still covers more
  pipeline paths (multi-doc misses, the exception check, batching) since the real sample so far
  is single-document.
- Ran the full pipeline against the real sample with Gemini, golden dataset re-read fresh (no
  crashes, no schema surprises): **0% recall/precision** — but this is a coverage artifact, not
  a quality signal. The sample only has predictions for DOC-001; golden's actual DOC-001 issue
  is `LG-05` ("KPI vs 기술 제약", Document level), while the review agent's 6 DOC-001
  predictions were all `AE-03`/`TC-02` (모호한 표현 / 약어 미정의) in unrelated
  sections — different rule category entirely, so Matcher correctly finds zero overlap (the
  prefilter buckets by category; LG never shares a bucket with AE/TC). The other 130 golden
  rows across other documents were never going to be recalled since the sample doesn't predict
  anything for those documents either.
- New-rule triage on the 6 unmatched predictions was mixed, not dismissive: 4× `human_review`
  and 1× `new_rule_candidate` for the AE-03 findings (LLM judged them as plausibly real issues,
  just not confidently classifiable as false or as a rulebook gap), 1× `false_positive` for one
  AE-03, 1× `new_rule_candidate` for the TC-02 (abbreviation-undefined) finding. None were
  dismissed as pure noise — worth reading the actual reasoning in `outputs/eval/
  real_review_agent_test/report.md` rather than the raw 0% headline number.

### Next

- This 0%/0% run is not evidence the review agent is bad — it's evidence the sample is a
  single-document smoke test. Re-run once the review agent has processed more documents (or all
  40) to get a real recall/precision signal, and use *that* run for the 2-1 gate's stratified
  sample instead of the synthetic file.
- The DOC-001 rule-category mismatch (golden wants LG-05, agent found AE-03/TC-02) is worth a
  quick manual look — is DOC-001's actual LG-05 issue a genuine miss by the review agent, or is
  the golden dataset itself stale for DOC-001 relative to the current rulebook revision?
- DOC-000 source text still missing (unchanged from 2026-08-05 rulebook-refresh entry above).
