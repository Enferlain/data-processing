# Design: catalog crosscheck

## Context

`CandidateLookupService` already plans/executes/resumes single-seed provider lookups
with retained `candidate_lookup_runs` (plan/material digests, request/page/result
counts, `retry_after`, `budget_boundary`) and `candidate_lookup_checkpoints`
(adapter continuations). The batch command is coordination, not a new lookup engine
(bead `data-processing-p1t` design note).

## Decisions

### D1 — Serialized writes by construction

The jh3 incident: four provider workers opened their own catalog connections and
3 of 4 died with `OperationalError` at startup. The batch command runs everything
in ONE process with ONE writable connection, executing provider lookups strictly
sequentially (subject-major, then provider). Adapter minimum intervals and
`retry_after` pacing apply as today. Network concurrency is deliberately deferred:
the invariant "one writer at a time" is the product requirement; throughput is a
later, measurable optimization.

### D2 — Corpus selection is explicit and named

The operator correction is law: the broad sweep over 3,191 metadata-only X bookmarks
took hours with weak queries. Default corpus = `hash-material` (subjects whose
material digest is non-empty: md5 or foreign-id evidence — the "focused 31" class,
now 106 md5 + foreign-id subjects). `downloaded` (posts with acquired assets),
`all` (explicit). Reporting always labels metadata-only items as such, per item.
### D3 — Runs are the dedup and freshness unit

A (subject × provider × strategy) is "done" when a `candidate_lookup_run` exists
with status `complete` for THAT platform and strategy, matching `seed_revision`,
`material_digest`, and current `strategy_version`/`adapter_version`. The dedup
identity is thus **material identity + provider + method + strategy version +
adapter version** — runs are per-platform rows, so two providers can never
suppress each other even where a strategy version string coincides. Reuse (skip)
is the default; `--recheck` modes mirror discovery policy (`unsearched` default,
`stale` via `--stale-after`, `force`). Paused/failed runs with checkpoints resume
via `CandidateLookupService.resume`; failed-without-checkpoint re-plans.

### D4 — Budgets stop at item boundaries; state is durable

`--max-requests` / `--max-minutes` are evaluated between items; the in-flight item's
runs complete or pause-with-checkpoint first. Batch state lives in `crosscheck_batches`
(one row per invocation chain, keyed by a stable `batch_key` derived from corpus +
provider set + recheck policy) and `crosscheck_items` (one row per subject × provider ×
strategy: state machine `pending → in_flight → checked|matched|skipped|failed`, with
`reason` for the terminal non-checked states and `run_id` provenance). Resume = new
invocation with the same `batch_key` re-uses item rows; completed items never re-run.

### D5 — Reporting is item-level with reasons

Summary: counts per state, per provider; per-item lines name skip reasons (fresh-run
reused, no-query-material, missing-credentials, rate-limited with retry_after,
provider-undeclared-strategy) and matched candidate counts. Matched candidates are
exactly what `CandidateLookupService` already records (provenance-preserving); the
command never writes relationship facts. JSON and human output follow repo
conventions (`--json`).

## Risks / trade-offs

- Sequential execution is slower than the (broken) concurrent sweep — accepted: a
  sweep that deadlocks 3 of 4 providers is slower in wall-clock reality.
- Reuse keyed on digests means a provider-side semantic bump invalidates the batch's
  skips — correct, and visible in reporting as re-executed counts.
