# Progress Log

## 2026-08-10 — First real end-to-end verification, two config gaps found and fixed

Full pipeline check (review-agent → eval-service enqueue → worker → judge) run live for the
first time since the monorepo restructure (see `docs/adr/0001-...`). Two real gaps found and
fixed rather than worked around:

### Done

- **`worker.py` had no `.env` loading at all** — unlike `services/review-agent`/
  `tools/eval-agent`'s `cli.py`, nothing called `load_dotenv()`, so the worker only ever
  worked via directly-exported shell env vars. Added `python-dotenv` to `pyproject.toml` and
  a `load_dotenv()` call at the top of `worker.py`'s `main()`, mirroring the other two
  packages exactly (upward search from the calling file's location finds
  `services/eval-service/.env` correctly when run via the real `planqa-eval-service-worker`
  console script — verified this specifically, since an ad-hoc `python -c` invocation does
  *not* get the same upward search and gave a false negative during testing).
- New `services/eval-service/.env` (gitignored): `GEMINI_API_KEY` (singular — this client is
  single-key, unlike review-agent/eval-agent's `GEMINI_API_KEYS` rotation), value reused from
  `services/review-agent/.env`'s existing `GEMINI_API_KEYS` (first key) rather than a new key
  — never printed to any tool output, copied via a Python script that only echoes length/
  prefix for verification.
- **`GeminiClient`'s `DEFAULT_MODEL` (`gemini-2.5-flash`) is quota-exhausted (429) on this
  key/project** — same finding review-agent's `docs/progress.md` already recorded on
  2026-08-05 for the non-`-lite` Gemini lineup, just not yet propagated to this newer
  service. It doesn't hard-fail fast, though: the `google-genai` SDK retries client-side
  before finally either raising (caught by `_tier1_batch_check`'s broad `except Exception`,
  degrading to `valid=True`/`uncertain`) or succeeding late — observed ~16s for one call
  where `gemini-flash-lite-latest` took ~2s. Not a hang, not a crash, but works against the
  documented design goal ("has to keep up with review-agent's own request rate"). Changed
  `DEFAULT_MODEL` to `"gemini-flash-lite-latest"`. No test pinned the old string.
- Live-verified the full chain with the fixes in place, using review-agent's `category_screen`
  structure against DOC-001 (Claude Haiku for both screen and confirm, reusing review-agent's
  existing `ANTHROPIC_API_KEY` — no new secret needed there):
  1. `planqa-review review --backend anthropic ... ` with `EVAL_SERVICE_URL` set → finished
     in 50.5s, 19 issues, 0 tier failures.
  2. Confirmed via direct SQLite inspection that `POST /evaluate-async` really persisted a
     `pending` row (not just a 202 response) — the notify hook's fire-and-forget design means
     a 202 alone doesn't prove the payload landed.
  3. Ran `planqa-eval-service-worker` via its real console-script entry point (no manual
     overrides) against that job — done in ≤2s, `GET /evaluate-async/{id}` returned real,
     sensible Korean verdicts (19 judged, 4 flagged), not the degraded fallback shape.
- Full suite still 19/19 after both fixes; review-agent (109) and eval-agent (74) unaffected
  (neither package was touched).

### Next

- `EVAL_SERVICE_BACKEND`/model selection is still all-or-nothing per deployment (one
  `GeminiClient` instance for tier-1, optionally one `assembly` for tier-2 escalation via
  `EVAL_SERVICE_ENSEMBLE`) — no live run of the ensemble/arbiter escalation path yet, only
  the tier-1-only path (no `assembly` configured). Worth a real run once there's a reason to
  exercise the escalation branch.
- Anthropic backend isn't wired into eval-service's `llm/factory.py` at all (Gemini-only by
  design, see its own comment) — review-agent's Haiku/Sonnet keys can't be reused for the
  *judge* side directly, only Gemini keys can. Not needed today; flagging in case someone
  reaches for review-agent's `ANTHROPIC_API_KEY` here later and wonders why it's not picked
  up.
