- Title: uv workspace monorepo (services/tools/packages) + async eval-service via SQLite outbox
- Status: Accepted
- Date: 2026-08-09

- Context: `review-agent`/`eval-agent` each lived as fully independent top-level `uv` projects
  on their own feature branches (`feature/review-agent`, `feature/eval-agent`); `main`/`dev`
  had nothing but a README. Both branches independently, byte-for-byte (aside from the import
  path) duplicated `Issue`/`RuleBook`/`parse_rulebook` — the two projects' own docs both
  stated "we don't share code with the other" as a deliberate convention. Separately, we now
  want to grade `review-agent`'s *live, real-production* output (already deployed inside
  `planqa-backend`'s vendored copy, `POST /documents/{id}/qa-jobs`, itself an async
  `BackgroundTasks` job — see `sunic5-planqa/planqa`'s ADR 0001) — but `eval-agent`'s Judge
  logic is golden-set-referenced (`tools/eval-agent`'s `judge_match()` compares an issue
  against a golden `rationale`/`fix_direction`) and can't grade a document with no golden
  counterpart. `eval-agent` also has zero reason to ever be deployed — it's a CI-time,
  golden-comparison-only tool.

- Options:
  1. Keep `review-agent`/`eval-agent` as separate repos/branches indefinitely; build the
     live-grading capability as a new stage bolted directly onto `review-agent`'s own
     pipeline (`review-agent`'s own progress log independently proposed almost exactly this,
     "제안6 Generator-Critic" — a critique stage layered onto whichever pipeline structure
     wins, deliberately queued *after* four structural experiments).
  2. Same monorepo, but make the live-grading service call `review-agent`'s response path
     *synchronously* (grade before responding to the user).
  3. Consolidate into one `uv` workspace monorepo: `services/` (deployed: `review-agent`,
     new `eval-service`), `tools/` (CI-only: `eval-agent`), `packages/` (shared:
     `planqa-schemas`). `eval-service` is fire-and-forget from `review-agent`'s response
     path — an outbox (SQLite) + a separately-running polling worker, so `eval-service`'s
     own latency/availability can never affect what a user of `review-agent` sees.

- Decision: Option 3.
  - Not option 1: adding an in-process critique stage to `review-agent`'s pipeline would mean
    editing the vendored, "diffable copy" kept inside `planqa-backend` (see that repo's own
    ADR 0001, which explicitly values that diffability) — a structural pipeline change is a
    much bigger diff to keep in sync than "add one fire-and-forget POST call after the
    existing pipeline already returned a result," which is what this decision does instead.
    "제안6" is still worth doing eventually and isn't contradicted by this — it's a different,
    complementary idea (self-critique *during* generation) from what `eval-service` does
    (grading *after* generation, out-of-process).
  - Not option 2: `review-agent` already takes ~6 minutes for one document (measured); a
    synchronous grading call on top would add that latency directly to the user-facing
    response, and any `eval-service` outage/slowness would take `review-agent`'s responses
    down with it. `planqa-backend`'s QA job is already async (`BackgroundTasks` +
    `asyncio.to_thread`) precisely to avoid blocking the caller — a second, *synchronous* hop
    bolted onto that would undo the reason that pattern exists.
  - SQLite outbox over Redis/Celery/`arq`: no extra infra to run, durable across a worker
    restart (unlike an in-memory queue), and cheap enough to run on a free-tier host.
    `arq` (`python-arq/arq`) was considered and rejected for v1 specifically because its own
    README states it's in "maintenance only mode" (issue #510) — not something to build new
    infrastructure on top of by default. `queue.py`'s `EvalQueue` is a `Protocol` so a
    Redis-backed implementation can replace `SQLiteEvalQueue` later without touching
    `api.py`/`worker.py`.
  - `packages/planqa-schemas`: this is a **deliberate reversal** of `review-agent`'s and
    `eval-agent`'s prior "don't share code" convention. It's justified here specifically
    because `schema.py` and `rulebook.py` were confirmed (`diff`) to be identical except for
    the import line — real duplication, not superficial similarity — whereas e.g.
    `verifier.py` was *not* unified, because `review-agent`'s copy is a deliberate subset
    (drops `VerifiedMatch`/`VerifiedMiss`/golden-comparison functions that only make sense in
    `eval-agent`), not a duplicate. Sharing code across `services/`/`tools/` members is now an
    accepted pattern *when the code is genuinely identical*, not a blanket policy change.

- Consequences:
  - `eval-service`'s `judge.py` is a stub (`{"issue_count": N, "scores": []}`) — the real
    rubric logic is explicitly **not** `tools/eval-agent`'s `judge_match()` copy-pasted, since
    that function requires a golden `Issue` to compare against and live documents don't have
    one. Whoever picks up "real judge.py" next needs a reference-free design (e.g. does the
    finding's quoted span actually satisfy the rule text it cites, independent of any golden
    answer) — this is flagged here so it isn't mistaken for a simple import.
  - `review-agent`'s notify hook (`eval_service_notify.py`) is wired into `cmd_review` only,
    not into `pipeline.review_document()` itself or `cmd_experiment`/`benchmark.py` — ablation/
    benchmark runs would otherwise spam `eval-service` with synthetic, non-production traffic.
  - This is the **canonical** location for `review-agent` (`services/review-agent/`) going
    forward, but `planqa-backend`'s vendored copy (`backend/src/sunnic_backend/qa_engine/
    review_agent/`) does not auto-update from it — re-syncing the notify hook (or anything
    else) into the deployed copy is a separate, manual step per that repo's own ADR 0001, not
    covered by this change.
  - `main`/`dev` had no CI configured before this; `services/*` vs `tools/*` build/deploy
    separation is expressed in this structure (deployed vs CI-only) but no actual CI YAML was
    added in this change — enforcing it (e.g. deploy pipeline only watching `services/`) is
    follow-up work.
  - Running tests requires an explicit test path per package (`uv run --package planqa-eval
    pytest tools/eval-agent/tests`, not a bare `pytest` from the repo root) — multiple
    members have same-named test files (`test_pipeline.py` in both `review-agent` and
    `eval-agent`) and both rely on `from conftest import ...` (a pre-existing convention from
    when each was its own top-level project, left unchanged). `--import-mode=importlib`
    would fix whole-workspace collection but breaks that `conftest` import pattern — not
    worth changing established test code for. Root `README.md` documents the per-package
    form.
