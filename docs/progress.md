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

- Get a real `GEMINI_API_KEY` (or install Ollama + pull a Qwen model) to actually run
  `planqa-eval gate` once real review-agent output exists.
- Real review-agent output JSON sample — validate/adjust `parsers/review_json.py` against it
  once available.
