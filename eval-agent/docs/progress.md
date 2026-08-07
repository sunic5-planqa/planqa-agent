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

## 2026-08-07 — LLM-as-judge ensemble orchestration for Judge/triage scoring

Ported the orchestration pattern from `microsoft/llm-as-judge` (SuperJudge/Mediator: run
several sub-judges in parallel, combine results) and the calibration utilities from
`wenxuec/llm-judge` (`calibrate.py`'s `cohens_kappa`/`spearman`, `harness.py`'s
`compute_rubric_hash()`) to make the 4-axis rubric scoring and FP-candidate triage more
reliable than a single LLM call, per an internal team request.

### Done

- `ensemble.py` (new): `JudgeAssembly`, `run_ensemble()` (ThreadPoolExecutor version of
  `asyncio.gather` — deliberately drops only the failing member instead of failing the whole
  batch, since local models can time out/emit malformed JSON independently of each other),
  `majority_vote_categorical()`, `aggregate_numeric()`.
- `harness/calibration.py` (new): `cohens_kappa`/`spearman`/`is_numeric`/`compare_label_sets`,
  ported near-verbatim from `calibrate.py`. Used as an internal QC diagnostic (how much do the
  ensemble members agree with each other), not to validate against human labels.
- `judge.py`/`new_rule_triage.py`: `JudgeScore`/`TriageResult` gained `ambiguous: bool = False`.
  New `judge_match_ensemble()`/`triage_ensemble()` (+ batch wrappers) run every assembly member
  in parallel and combine; when they disagree past a threshold (score stdev > 1.0, or triage
  consensus < 2/3), `ambiguous=True` — and if an `arbiter` LLM is given, that one item alone
  gets re-scored by the arbiter and its verdict wins (Layer 3→4 escalation: cheap ensemble for
  everything, one strong-model call only for the genuinely disputed few).
- `pipeline.py`/`harness/full_eval.py`: `run_pipeline`/`run_full_evaluation` take an optional
  `judge_assembly` — when given, judge/triage go through the ensemble with the existing `llm`
  doubling as arbiter. `full_eval.py` only applies it to the subject prediction run, not the
  Review1-4 baseline loop (aggregator never reads judge scores, so ensembling baselines would
  be pure wasted cost).
- `harness/confidence_gate.py`: `run_confidence_gate()` takes the same optional `assembly` —
  swaps the gate's single `judge_match` call for `judge_match_ensemble`, so the existing
  human-blind-label gate can validate ensemble-scored judging too. Added `compute_rubric_hash()`
  (ported from `harness.py`) on `GateReport.judge_prompt_hash`, and each log entry now carries
  `ambiguous`.
- `cli.py`: `--judge-ensemble` (comma-separated `name:backend[:model]`) on both `gate` and
  `evaluate`; `--backend`'s LLM doubles as arbiter.
- Ensemble composition (all local Ollama, no API key/quota cost): `qwen2.5:1.5b` (already
  verified) + `exaone3.5:2.4b` (LG AI연구원, Korean-native — genuinely different training
  lineage from Qwen, matters for `service_tone_fit`'s Korean-tone judgment) + `gemma2:2b`
  (another distinct lineage). 3 is the practical floor for `majority_vote_categorical` to mean
  anything — with 2, "majority" degenerates to plain agree/disagree.
- 28 new tests (`test_ensemble.py`, `test_calibration.py`, ensemble cases added to
  `test_judge.py`/`test_new_rule_triage.py`, new `test_pipeline.py`/`test_confidence_gate.py`).
  75/75 passing.
- Live end-to-end check against the real `review_agent_sample_output.json` (bypassing
  `run_full_evaluation`'s Review1-4 baseline loop on purpose — that's all single-LLM Gemini
  calls unrelated to the ensemble change and would just burn quota): all 6 FP candidates for
  this sample hit real 3-way splits across the 3 local models (`ambiguous=True` for all 6) and
  got escalated to the Gemini arbiter — consistent with the 2026-08-05 session's note that a
  single Gemini call already found these particular DOC-001 AE-03/TC-02 candidates "mixed, not
  dismissive." `matched pairs: 0` / `verified_misses: 131` reproduces the already-documented
  single-doc coverage gap, not a regression.
- Pulled `feature/review-agent` (real `planqa-review` implementation, previously never run in
  this environment) into a throwaway worktree and actually ran it: `uv sync`, its own 84/84
  tests green, then a real `planqa-review review` call against DOC-001 with the live Gemini
  API — 30 issues found in 363s, valid `review.json`/`review.md`. Confirmed its output schema
  matches `parse_review_output()` field-for-field with no adapter needed (`{"issues": [...]}`
  wrapper, `issue_id`/`original_text`/`rationale`/`fix_direction` all present). Worktree removed
  after verification — nothing committed to `feature/review-agent`, per team rule.
- Quant eval (recall/precision) against that *real* DOC-001-only output: 0%/0% (TP=0, FN=131,
  FP=1) — this reproduces the exact same single-document-coverage artifact the 2026-08-05
  session already found with a synthetic sample (golden's real DOC-001 issue is LG-05; this
  review-agent run's DOC-001 predictions are all AE-03/TC-02, a different rule category, so
  Matcher correctly finds no overlap). Not a bug in either agent — just needs a multi-doc real
  run to get a meaningful recall/precision number.
- Live-confirmed the `judge_match_ensemble()` path itself (not just triage) with real matched
  pairs, fully local (Matcher + all 3 ensemble judges + would-be arbiter all Ollama, zero Gemini
  calls — see Notes below for why): ran against `data/sample_review_output.json` (20 predicted,
  18 real matches). Result: 18/18 pairs scored, 8 flagged `ambiguous=True` (3-way score
  stdev > 1.0), 10 converged confidently — a believable split, not every pair disagreeing and
  not every pair trivially agreeing.

### Notes

- A first attempt at this session's disk got a real, unrelated blocker: the machine's APFS
  Data volume was at 438MB free (of 228GB), which failed both `ollama pull`s with "no space
  left on device." Cleared ~7.8GB via `pip cache purge` + `brew cleanup -s --prune=all` +
  `npm cache clean --force` + `conda clean --all` before retrying — worth checking `df -h`
  before any large local-model pull on this machine going forward.
- Design detour worth remembering: the first pass at this feature over-rotated into "does the
  ensemble's consensus agree with human blind labels enough to replace them" (a `kappa`/
  `spearman`-gated `compare_against` mode on the confidence gate, with a dedicated
  human-vs-ensemble comparison function). That's a legitimate question but wasn't what was
  asked — the actual ask was "make the review agent's output get scored well," i.e. the
  ensemble should improve the *production* Judge/triage mechanism, not sit in a separate
  validation-only gate mode. Re-planned around that correction before implementing.
- Gemini was noticeably unstable late on 2026-08-07 (one `503 UNAVAILABLE "high demand"`, plus
  a Matcher call that stalled for 5+ minutes with no error and no retry-visible cause) —
  unrelated to this feature, but cost real time chasing it before switching the verification
  run's Matcher/arbiter to a local Ollama model instead, which resolved it immediately. Worth
  remembering `--backend ollama` as the fallback when Gemini is flaky, not just when quota is
  the concern.

### Next

- Real review-agent output across all 40 docs still the biggest open item — now that
  `feature/review-agent` is confirmed to actually run, this is a real "run it 40 times" task,
  not a blocked one. A multi-doc real run would also give a non-degenerate recall/precision
  number (this session's real run only covered DOC-001, which has no golden overlap).

## 2026-08-08 — Removed the 2-1 human-blind-label confidence gate

Now that the LLM-as-judge ensemble's `ambiguous` flag + arbiter escalation establishes trust
in the automated Judge inline (previous entry), the separate human-blind-label gate that used
to serve that role is redundant — removed per explicit request, not silently deprecated.

### Done

- Deleted `harness/confidence_gate.py` entirely: `HumanBlindLabel`, `GateThresholds`,
  `GateReport`, `run_confidence_gate()`, `save_human_label_template()`/`load_human_labels()`,
  `stratified_sample()`, `compute_rubric_hash()`. Deleted `tests/test_confidence_gate.py`.
- `harness/full_eval.py`: dropped `GateNotPassedError`/`check_gate_passed()` and the
  `gate_report_path`/`force` params — `run_full_evaluation()` now always runs, no prior gate
  report required.
- `cli.py`: removed the `gate` subcommand entirely (`cmd_gate`, `_latest_gate_report`,
  `--human-labels`/`--sample-size`/`--gate-report`/`--force`). `evaluate` is now the only
  subcommand; `--judge-ensemble` unchanged.
- Updated `README.md`'s setup/run sections and `docs/adr/0001-...md` (appended an Update note
  rather than rewriting history, per that doc's own established pattern) to drop gate
  references.
- **Left untouched, deliberately**: `aggregator.compare_to_human_baseline()` / the Review1-4
  loop in `run_full_evaluation()`. That's a different "human" concept — benchmarking the
  review agent's recall/precision against 4 human reviewers on the same golden set — not the
  blind-label judge-validation mechanism this session removed. Flagged this scoping call back
  to the user rather than assuming it should go too.
- 73/73 tests green (75 − the 2 confidence-gate-specific tests that no longer exist), CLI
  `--help` sanity-checked with the `gate` subcommand gone.

### Next

- If `compare_to_human_baseline`/Review1-4 should also go, that's a separate follow-up —
  intentionally not assumed here.

## 2026-08-08 — Surface review-agent's cost stats in eval-agent's report

review-agent already tracks time/token cost per run in real detail (`run_stats.py`/
`instrumentation.py`: call counts, elapsed seconds, tokens, broken down by stage/tier/rule,
plus `rulebook_hash`) and writes it into `review.json` under `"stats"` — its own `RunStats`
docstring says this is meant to be compared "alongside recall/precision from the eval agent."
eval-agent was silently dropping that key. Decision: keep the actual measurement in
review-agent (only it has ground truth on its own call counts — eval-agent only ever sees the
final output file) and have eval-agent's reporter just pass the data through next to its own
quality numbers, rather than re-deriving anything. Dedicated cost/quality *ablation*
experiments (comparing screen/verify model choices, temperature, profile) stay in
review-agent's own `experiment`/`benchmark.py` — that's already built for exactly that and
eval-agent doesn't need a second copy of it.

### Done

- `parsers/review_json.py`: `parse_review_stats(json_path) -> dict | None` reads
  `review.json`'s `"stats"` key verbatim (`None` if absent or the file is a bare array).
- `reporter.py`: `to_json_dict`/`to_markdown`/`write_report` take an optional `review_stats`
  param. JSON gets a `review_agent_stats` key (raw pass-through, no reshaping — it's
  review-agent's schema, not eval-agent's). Markdown gets a "## Review Agent Run Cost" section
  (profile/backend/models/rulebook_hash/total_wall_seconds + a per-stage calls/elapsed/tokens
  table) right after the summary, omitted entirely when `review_stats` is `None`.
- `cli.py`'s `cmd_evaluate` reads `parse_review_stats(args.predictions)` from the same file
  already used for `parse_review_output` and threads it into `write_report`.
- New `tests/test_review_json.py` (3 tests) and `tests/test_reporter.py` (4 tests) — 80/80
  passing overall.

### Next

- Once a real multi-doc review-agent run exists, sanity-check the markdown table renders
  correctly against the *actual* `by_stage` shape (this session validated against the
  structure confirmed in review-agent's `diff_report.py`, not a live file — the earlier
  worktree that had one was already cleaned up).
