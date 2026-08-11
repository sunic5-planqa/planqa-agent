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

## 2026-08-08 — Harden judge_matches/triage_fp_candidates against unparseable batch JSON

A real local run (`--backend ollama qwen2.5:1.5b`, `evaluate` against
`data/sample_review_output.json`) crashed the whole run: Review1's 56-issue judge batch came
back as invalid JSON from qwen2.5:1.5b (small models can truncate/garble a large batched
response), and `llm.complete_json()`'s `json.JSONDecodeError` propagated straight up —
`judge_matches()`'s existing "missing index falls back to a single call" logic never got a
chance to run, since that only handles a *parseable* response with a *missing* index, not a
response that fails to parse at all.

### Done

- `judge_matches()` / `triage_fp_candidates()`: the initial batch `complete_json()` call is
  now wrapped in `try/except ValueError` (`json.JSONDecodeError` is a `ValueError` subclass —
  no new import needed). On failure, `response = None`, which flows into the existing
  `by_index = {}` → every item falls back to an individual call, exactly like a partially
  malformed response already did. No new failure-handling branch, just widened what triggers
  the one that existed.
- `tests/conftest.py`: added `BrokenBatchLLM` (raises `JSONDecodeError` on the first call,
  scripted responses after) alongside `ScriptedLLM`, plus one test per function
  (`test_judge.py`/`test_new_rule_triage.py`) asserting 1 failed batch call + N individual
  fallback calls still produces correct results.
- Verified against the actual failure, not just the unit tests: re-ran `run_pipeline` on
  exactly Review1 (56 issues) with `qwen2.5:1.5b` directly (not through the full `evaluate`
  command, which also runs the other 3 reviewers + the subject prediction — unnecessary cost
  for confirming this specific fix) — completed with 25 judge scores + 31 triage results, no
  crash, where it crashed outright before this fix.
- 82/82 tests green.

### Notes

- Running the *full* `evaluate` locally (all 4 Review1-4 baselines + subject, all through
  qwen) is genuinely slow — not just "local is slower than cloud" but the fallback itself
  trading a single batch call for up to N individual calls whenever a batch fails to parse.
  For any future "does X still work" check, prefer calling `run_pipeline` directly against
  just the reviewer/dataset that matters, the way this session's verification script did,
  rather than going through the full `evaluate` CLI path.

## 2026-08-09 — Moved into the planqa-agent uv workspace monorepo

This folder moved from its own `feature/eval-agent` branch to `tools/eval-agent/` inside a
new `uv` workspace monorepo (`docs/adr/0001-monorepo-workspace-and-async-eval-service.md` at
the repo root has the full reasoning) — `tools/` = CI-only, never deployed, as opposed to the
new `services/eval-service` (deployed, grades review-agent's *live* output asynchronously,
golden-free).

### Done

- `schema.py`/`rulebook.py` deleted from this package — diffed against review-agent's copies
  and they were identical apart from the import line, so both moved to a new shared
  `packages/planqa-schemas` workspace member. All internal imports updated
  (`planqa_eval.schema`/`planqa_eval.rulebook` → `planqa_schemas.schema`/`planqa_schemas.rulebook`).
  `test_rulebook.py`'s 8 tests moved with it.
- 74/74 tests green (82 − the 8 that moved to `planqa-schemas`, which itself has its own
  8/8 green).
- Confirmed via `uv sync --all-packages` + `uv run --package planqa-eval pytest` that this
  package still resolves/runs correctly as a workspace member, independent of `services/*`.

### Next

- No behavior/business-logic change here — this was a pure structural move. Next real work
  item is still what it was before: a real multi-doc review-agent run for a non-degenerate
  recall/precision number.

## 2026-08-10 — `--with-baseline` flag, quota-fixed default model, looser matcher

Ran `evaluate` for real against a live `review-agent` DOC-001 output (`category_screen`,
Claude Haiku both stages, 21 issues) for the first time this session. Found and fixed real
problems along the way rather than just reading the numbers.

### Done

- **`evaluate` always ran the Review1-6 human-baseline loop unconditionally** — several times
  the cost/time of scoring `predicted` alone, and what actually burned through every rotated
  `GEMINI_API_KEYS` key's daily quota on the first attempt (429, `gemini-2.5-flash`, "limit:
  20"). `run_full_evaluation` now takes `include_baseline: bool = False` and returns
  `comparison: BaselineComparison | None`, short-circuiting before `parse_review_sheets` is
  even called when off. `write_report`/`to_json_dict` already accepted `baseline=None`, so
  no reporting-layer change needed. New `--with-baseline` CLI flag (opt-in) for when the
  comparison actually is wanted. 2 new tests in `test_full_eval.py` (default skips and never
  touches `parse_review_sheets`; `--with-baseline`-equivalent path still produces a real
  `BaselineComparison`).
- **`GeminiClient`'s `DEFAULT_MODEL` was the same quota-exhausted `gemini-2.5-flash`** that
  review-agent (2026-08-05) and `services/eval-service` (this session, PR #13) already found
  and fixed — just not propagated here yet. Switched to `gemini-flash-lite-latest`.
- Golden-set score for that DOC-001 run: **0 matches / 1 miss / 21 fp_candidates** (the one
  DOC-001 golden row, `LG-05` "3장 KPI vs 4장 기술 제약", is a cross-section contradiction
  review-agent's 21 findings genuinely don't cover — not a false negative from matcher
  strictness). All 21 unmatched findings triaged `false_positive` — but several of triage's
  own `reasoning` strings said things like *"a valid logic gap"* / *"correctly flagged"*
  while still picking `false_positive`, a real reasoning/verdict inconsistency in the triage
  judge worth a closer look later (not touched this session — scoped to the matcher only
  per instruction).
- **Loosened `matcher.py`'s matching prompt** — it previously required "same location/span
  AND same kind of problem" (a strict AND); now explicitly says location/span is a signal,
  not a hard requirement, and to err toward matching on substantive overlap rather than
  losing a real catch to a location/wording technicality. Re-ran the same DOC-001 report
  after this change: still 0 matches — confirmed this is a genuine miss (the golden issue's
  actual content isn't among the 21 predicted issues), not something the old prompt was
  wrongly gatekeeping, so no false improvement was fabricated here. The change is still a
  real, tested behavior improvement for cases where it *is* a wording/location technicality.
- 76/76 tests green throughout (74 + 2 new).

### Next

- The triage reasoning/verdict inconsistency above (reasoning says "valid" but verdict says
  `false_positive`) is a real triage-judge reliability question — consider `--judge-ensemble`
  for triage specifically, or tightening `_TRIAGE_SYSTEM` to force the verdict to actually
  follow from the stated reasoning, next time this comes up.
- Still no non-degenerate multi-doc recall/precision number — DOC-001 alone has only 1
  golden row, too sparse to say much either way about review-agent's real accuracy.

## 2026-08-10 (later) — 20-doc benchmark run: golden scoping + a real triage taxonomy gap

First non-degenerate multi-document run: `category_screen` (Claude Haiku both stages) across
the full `BENCHMARK_DOC_IDS` (DOC-001–020, 20 docs, 295 issues total), scored against golden.
Two more real fixes came out of actually looking at the numbers instead of trusting them.

### Done

- **Golden-set scoping**: `run_full_evaluation` now filters `golden` down to only the
  `doc_id`s present in `predicted` (`_scope_to_predicted_docs`, falls back to the full set
  when `predicted` is empty, since then there's no signal for which docs were intended).
  Without this, `evaluate` scored the subject run against golden rows for every document in
  the whole dataset, including the ~20+ never given to review-agent at all — every one of
  those rows was an automatic false negative unrelated to anything this run actually did.
  Baseline-comparison runs (`--with-baseline`) use the same scoped golden, so the subject
  and each human reviewer are compared over identical document sets. 2 new tests.
- **Real finding, not a metric bug — but led to one**: first pass on the 20-doc benchmark
  scored recall=15.8%, **precision=1.0%** (TP=3, FN=16, FP=292). Read a random sample of 20
  of the 292 `false_positive` triage verdicts (no LLM calls, just reading the already-
  computed `reasoning` strings) — **all 20** described the flagged issue as correctly
  fitting/matching an existing rule category, e.g. *"The issue points out a missing
  intermediate logical connection... fitting Logic Gap."* — yet were still verdict
  `false_positive`. This wasn't the earlier reasoning/verdict-inconsistency bug recurring at
  scale; it's a **structural gap in the 3-way triage taxonomy**: `new_rule_candidate` only
  covers "doesn't fit any existing category" (a rulebook gap), and `false_positive` only
  covers "not a real problem" — neither one describes "correctly uses an existing rule for a
  real problem, golden just never happened to label this specific instance" (golden-set
  incompleteness), so the model had nowhere to put that case but `false_positive`.
- Added a 4th verdict, **`valid_but_unlabeled`**, to `new_rule_triage.py`'s `Verdict`
  Literal/`_TRIAGE_CRITERIA`/both system prompts, and to `aggregator.py` (excluded from
  precision the same way `new_rule_candidate` already was, tracked as its own
  `AggregateReport.valid_unlabeled_count`). Surfaced in `reporter.py`'s JSON/markdown
  summary. 2 new tests (`test_aggregator.py`, `test_new_rule_triage.py`).
- Re-scored the same 20-doc predictions after the fix (no re-run of review-agent, just
  re-triage): **precision 1.0% → 42.9%** (FP 292 → 4, `valid_unlabeled_count`: 288). Recall
  stayed exactly 15.8% — expected, triage only affects unmatched-candidate classification,
  never the golden-match/miss count itself.
- 80/80 tests green throughout (78 + 2).

### Notes

- This was explicitly *not* "loosen the metric until the number looks better" — the fix is
  a real taxonomy gap that was mislabeling golden-set incompleteness as agent error, found
  by reading actual `reasoning` text before changing anything, and it left recall (the other
  half of the "is this metric trustworthy" question) completely untouched on purpose.
- Session cost-conscious throughout — this whole investigation reused one review-agent run
  (295 issues, computed once) and re-triaged the same file against Gemini flash-lite twice,
  no repeated re-runs.

### Next

- Recall is still only 15.8% (3/19) and genuinely unverified — the 16 missed golden rows
  need an actual read (available locally in `report.json`'s `misses`, no LLM calls needed)
  to say whether they're real misses or something else systematic.
- `new_rule_candidate_count` was 0 across all 292 candidates this run — worth checking
  whether the taxonomy still has room for genuine rulebook gaps now that
  `valid_but_unlabeled` exists, or whether triage now over-applies the new category.

## 2026-08-10 (later still) — 4th real finding: strict recall/precision double-penalize tier mismatches

Read all 7 matched pairs + 12 genuine misses from the same 20-doc report by hand (free, no
LLM calls) to answer "should we add a metric, or can recall be raised" with evidence instead
of guessing.

### Done

- **Found**: 4 of the 20-doc run's 7 matched pairs had the *correct rule_id* but the
  *wrong Level* (tier) — `verified.fully_correct` requires both, so each of those 4 was
  simultaneously scored as a miss for golden's category/level AND a false positive for
  predicted's category/level, on top of not counting as a TP. Same-substance catches were
  being penalized twice for one tier-tagging slip.
- Added `AggregateReport.overall_relaxed` (rule_id match alone is enough — a wrong-tier
  match no longer double-penalizes) and `AggregateReport.tier_accuracy` (of rule_id matches,
  the fraction that also got Level right) — `aggregate()` computes both in the same pass as
  the existing strict counts, no behavior change to `overall`/`by_category`/`by_level`.
  Surfaced in `reporter.py`'s JSON (`overall_relaxed`, `tier_accuracy`) and markdown (a
  second summary row + a stat line). 2 new tests.
- Re-scored the 20-doc predictions (still the same 295-issue file, no re-run of anything):
  **strict recall 15.8% → relaxed 36.8%**, **strict precision 42.9% → relaxed 100%**,
  **tier_accuracy 42.9%** (3 of the 7 rule_id matches also got the tier right). This means:
  review-agent finds the *right problem* noticeably more often than strict scoring showed,
  but tags it at the *right hierarchy level* only about 4 times in 10 — a real, specific,
  actionable weak spot (categorization granularity) distinct from "doesn't find the issue at
  all", which strict recall/precision alone conflated into one low number.
- Also read the 12 genuine (no-match-at-all) misses: 5 of 12 are Document-tier
  relational/cross-section rules (LG-05, MI-05×1, GA-05×1, GA-01×2 — "A vs B"/"A↔B" style
  locations) — a pattern, not noise, suggesting review-agent's Document-tier relational
  detection specifically is the weaker spot, worth a real prompt/structure look later (not a
  metric issue — flagged as a genuine engineering lead, not chased further this session).
- 82/82 tests green (80 + 2).

### Notes

- Answered the "recall폐기?/새 지표 필요?" question this session opened with real evidence
  gathered along the way: don't discard strict recall/precision (still the right tool for
  golden-set-referenced accuracy), but the *tier* axis needed its own metric instead of
  being folded into one strict pass/fail — same "additive metric, not a lowered bar"
  principle as `valid_but_unlabeled`.
- `BaselineComparison`/`compare_to_human_baseline` were **not** extended with the relaxed
  view this session — still strict-only. Follow-up if a relaxed subject-vs-human comparison
  is ever needed.

### Next

- The Document-tier relational-detection weak spot above is review-agent's own next lead,
  not eval-agent's — separate session/owner call.
- Consider whether `--judge-ensemble`-verified triage would meaningfully change
  `valid_unlabeled_count`/`new_rule_candidate_count` now that the 4-way taxonomy exists, if
  a low-stakes moment to spend the extra API calls comes up.

## 2026-08-10 (final) — near_miss_candidates: surface, don't auto-credit, ambiguous misses

User asked to loosen further ("더 설계해서 완화해봐"). Checked by hand (no LLM calls) whether
any of the 12 genuine misses had a same-category unmatched predicted issue nearby the
matcher might have missed — result was mixed, which shaped the design.

### Done

- **Evidence first**: cross-referenced all 12 misses against the 295-issue predictions file
  locally. Found real near-misses (DOC-003: same rule_id AE-03, same "적절히" vagueness,
  just table-row vs. whole-section granularity) *and* real non-matches at the exact same
  location (DOC-015: golden MI-05 wants "품절 후기 예외 처리 미정의", the same-location
  predicted MI-02 is actually about "노출 처리 단위 불명확" — a genuinely different problem).
  Loosening the matcher further would have fixed DOC-003 but silently fabricated a wrong
  match for DOC-015 — decided against it.
- Instead added `near_miss_candidates` to each miss entry in `reporter.py`'s per-document
  breakdown (JSON and markdown): for a golden miss, any unmatched predicted issue in the
  same document + same rule category (deterministic, `category_of`, no LLM call) is listed
  alongside it — visible, not silently matched, **not counted toward recall**. New
  `summary.near_miss_count` (JSON) / summary line (markdown). Purely additive — no existing
  field or counting rule touched. 2 new tests (`test_reporter.py`).
- Re-ran against the same 20-doc predictions (still no re-run of review-agent, still no new
  API calls needed for this specific check): **8 of the 12 misses** now show at least one
  near-miss candidate (DOC-003, DOC-006, DOC-001, DOC-012, DOC-016, DOC-015, DOC-018,
  DOC-017) — recall stayed exactly 15.8%, confirming nothing was silently counted.
- 84/84 tests green (82 + 2).

### Notes

- This is the fourth round this session of the same discipline: look at real reasoning/data
  before changing a number, prefer "surface the ambiguity" over "auto-resolve it in the
  agent's favor" whenever the evidence is mixed (as it was here, unlike `valid_but_unlabeled`
  where the evidence was one-sided — 20/20 sampled reasonings agreed).
- `near_miss_candidates` is a reporting aid for a human (or a follow-up LLM judge call) to
  triage, not a scoring mechanism — deliberately no verdict/confidence attached yet.

### Next

- The 8 near-miss candidates are still unresolved — an actual LLM judgment (one call per
  candidate, similar shape to the existing FP triage) could turn some into real matches and
  leave others as confirmed non-matches, the same way `new_rule_triage.py` already does for
  the FP side. Not done this session (cost-conscious; this was kept to zero additional API
  calls end to end).
- Still open from earlier: Document-tier relational-detection weak spot (review-agent's own
  lead) and whether `--judge-ensemble` on triage changes the taxonomy counts.

## 2026-08-12 — `_CITATION` regex missed prose citations (found computing a slide number)

Zero-cost sanity check for a presentation figure ("예외조건 O건 중 O건 방어") surfaced a
real bug in `verifier.py`'s §3 reference-exception check, not a scoring-methodology issue.

### Done

- `has_valid_reference_exception()` ran against 4 real "예외조건 data" QA-dataset rows (the
  only 4 of 29 exception rows whose rule_id — AE-01/GA-03/LG-03/TC-02 — has a deterministic
  §3 check at all) and returned 0/4 "excused", even though all 4 clearly satisfy the
  rulebook's definition (문서명+섹션 참조 표기 in the same paragraph as the flagged text).
- Root cause: `_CITATION` only recognized the rulebook's own illustrative shorthand
  (`제목(DOC-XXX) 참고/참조`) — none of the 4 rows cite that way; they all use prose
  ("「제목」 2-4 '...'을 따른다" / "...에 해당하는 경우").
- Split into `_CITATION_DOC_CODE` (unchanged) + new `_CITATION_NATURAL`, OR'd via
  `_has_citation()`. Same fix applied to review-agent's trimmed copy of this file so the two
  don't drift.
- Added 2 regression tests for the prose-citation pattern; the existing DOC-006 counter-
  example test (citation in a *different* paragraph than the flagged text must NOT excuse)
  still passes unchanged — the fix only widens what counts as a citation, not the
  same-paragraph requirement that does the actual excusing.
- 86/86 eval-agent tests pass (84 existing + 2 new), 124/124 review-agent tests pass.
- Re-ran the 4 rows post-fix: 4/4 now correctly recognized as excused.

### Next

- The other 25 "예외조건 data" rows have no deterministic check (LLM-judgment-only
  exceptions) — testing those needs an actual review-agent run, i.e. API cost.
