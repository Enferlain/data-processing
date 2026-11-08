# Design

## Context

Discovery today: one `DiscoveryOrchestrator.start()` per invocation binds one
session to one subject (seed post/account/file), plans (source, method) steps
offline, executes them sequentially (local always, providers only `--live`)
under a session request/time budget, and reports. Provider lookups already run
through `CandidateLookupService` with per-adapter pacing, typed outcomes,
paused/resumable runs, and full request persistence. `discovery_steps` rows
carry planned/skipped/excluded → complete/failed, but no query-evidence
identity, no timing, no cross-session memory: every run redoes everything, and
nothing can answer "was this searched, when, is it fresh".

See proposal.md for motivation; stage 2 (search optimization, index targets)
and stage 3 (providers) are out of scope but must extend cleanly.

## Goals / Non-Goals

Goals: operator control (subjects, targets, methods, trails/active, recheck),
explainable planning, durable per-key freshness, deferred-not-failed budget
boundaries, dry-run, multi-subject runs with shared budgets and progress,
offline state inspection — all by extending the existing orchestrator,
session/step persistence, and lookup machinery.

Non-Goals: concurrent/parallel execution (persisted queue states make it
additive later; the multi-provider write-contention problem is tracked by
`data-processing-p1t`); new search targets (local/imported indexes,
reverse-image services); incremental index refresh; resuming paused lookup runs
inside discovery (attempts simply don't count as fresh, so later runs retry);
distributed anything.

## Decisions

### D1 — Attempt ledger as a new append-only table, not derived from steps

`discovery_steps` are session-scoped, deleted on replan, and lack version,
timing, and evidence identity. Freshness needs a stable cross-session ledger.

Table `discovery_search_attempts` (migration `0031`): nullable subject FKs
(`subject_post_id`/`subject_account_id`/`subject_file_id`, CHECK exactly one),
`source_kind` + `source` (the search-target identity: `local`/`catalog` today,
`index`/`remote-db`/`search-service` later — plain text, no provider FK),
`method`, `strategy_version`, `query_digest`, `status`
(running|complete|failed), `outcome`, `result_count`, `scope`, `requests_used`,
`discovery_session_id`/`discovery_step_id`/`candidate_lookup_run_id` links,
`started_at`/`finished_at`. Append-only history; freshness reads the latest
row per (subject, source_kind, source, method, query_digest) and compares
`strategy_version` in the verdict, so version drift is explainable
("attempted under lookup-v0") rather than an invisible miss.

Alternatives: deriving freshness from steps (fragile: replan deletes; no
version/timing); a single `last_searched` column (explicitly rejected — cannot
express per-target/method/evidence independence).

### D2 — Search state key = subject × target × method × version × evidence

- Subject: the session's seed identity (post/account/file id).
- Target: `source_kind` + `source` (catalog, provider platform key, future
  index names).
- Method: existing method strings (`local_md5`, lookup strategy values,
  `fetch_post`); open vocabulary for stage 2.
- Version: per-method constants — lookup strategies use
  `LOOKUP_STRATEGY_VERSION`, `fetch_post` uses `fetch-v1`, local catalog
  methods use `local-v1`. Bumping a constant invalidates old attempts.
- Evidence: sha256 over the sorted query-material digests the step searches.
  Generation-0 provider steps cover all materials of a strategy for the seed,
  so their digest is composite; follow-up steps are per-material (existing
  behavior). Changed material ⇒ different digest ⇒ replanned even under
  `unsearched`. Zero-result successes are fresh (they completed their scope).

`discovery_steps` gains `query_digest` (and gen-0 strategy steps now populate
`target` with the same digest, so cross-generation duplicate collapses keep
working). Local step evidence is derived from the exact values each local
executor searches (hash fingerprints / source URLs / canonical URL) via
helpers shared with the executors, not a second query convention.

### D3 — Policy as one value object; planner decides, executor obeys

`discovery/policy.py`: frozen `SearchPolicy` (included sources, methods,
`search_mode` trails|active, `recheck` unsearched|stale|force,
`stale_after_seconds`, plus echo fields) with CLI parsing/validation (unknown
names rejected; `--include-source` and `--exclude-source` mutually exclusive;
`--stale-after` only with `--recheck stale`) and a pure
`freshness_verdict(policy, attempt_row, method_version, now)` returning
(fresh, reason). Active methods today = `artist_*` strategies; supplying
`--search-term` implies active mode so account-seed invocations behave exactly
as before.

`discovery/planning.py` (extracted from `orchestration.plan`): resolves
materials once and produces `PlannedSearch` decisions — planned, skipped
(capability or fresh prior attempt named), excluded (missing material, or
policy: source not included / method filtered / active disabled) — each with
query digest and method version. `orchestration.plan()` persists them;
`--search-state` renders the same decisions plus ledger history without
creating a session. Every decision is explainable from the row itself.

### D4 — Queue states: deferred ≠ failed; running is visible

- Step not started due to budget: status `deferred`, outcome
  `budget_exhausted` (vocabulary already used across the repo), no attempt row
  — a later run replans it because only successful attempts are fresh.
- Step started: status `running` + a `running` attempt row before execution,
  terminal state written in the same commit that finishes the step — a crash
  leaves honest in-flight state that later runs retry.
- Partial provider work (mid-lookup budget boundary) keeps the existing
  lookup-run `paused` semantics: step ends `failed`/`budget_exhausted` with
  the paused run linked; it is not fresh, so reruns retry. Session summary
  status gains `partial` (no `planned` steps but `deferred` ones remain).
- `discovery_sessions` gains `requests_used` (updated with each step finish)
  and `policy_json` (the effective policy that produced the decisions).

### D5 — Multi-subject runs as a loop over sessions, not a new engine

`discovery/run.py`: `DiscoveryRunService` iterates explicit subject inputs in
order, each through the existing `DiscoveryOrchestrator.start()` under one
shared request budget and deadline (each session gets the remaining budget),
skipping already-complete work via the same ledger freshness. Progress: a
per-subject line via callback (CLI prints to stderr so `--json` stdout stays
clean) and an aggregate report (per-status step counts across subjects,
per-subject session summaries, requests used/budget). Deterministic ordering:
input order, then step order. Sequential execution reuses per-adapter pacing;
no new limit system.

### D6 — Bare-file seeds become idempotent by content

`materialize_file` currently inserts a new seed row per session, so the same
file re-discovered is a new subject and freshness would never match. Make it
reuse an existing row with identical `(verified_md5, verified_sha256)`
(non-unique index + lookup; existing catalogs may hold duplicates), mirroring
URL-seed idempotency ("URL input materializes once"). First materialization
keeps its provenance fields.

## Risks / Trade-offs

- [Default `unsearched` changes repeat-run behavior vs pre-change always-
  re-execute] → Intended feature; `--recheck force` restores old behavior;
  changelog and docs state it; local steps follow the same rule (a stale
  catalog view is refreshed with `--recheck stale`/`force`).
- [Coarse gen-0 freshness (composite digest replans the whole strategy step
  when any material changes)] → Fewer, larger provider queries preserved
  (existing report shape); follow-up generations stay per-material.
- [Sequential execution means "concurrency controls" are policy/progress only]
  → Explicit non-goal; persisted queue states are the contract concurrency
  will consume; `p1t` owns the write-contention work.
- [Running attempts from crashed processes linger] → They are simply not
  fresh; inspection shows them as in-flight history. No reaper in this change.
- [`--search-state` re-plans to enumerate decisions] → Planning is offline and
  pure catalog reads; no session or attempt is written.

## Migration Plan

`0031_discovery_search_policy.sql`: creates `discovery_search_attempts` +
indexes, adds `query_digest` to `discovery_steps`, `requests_used` +
`policy_json` to `discovery_sessions`, and a non-unique index on
`discovery_file_seeds(verified_md5, verified_sha256)`. All additive; rollback
is the standard pre-migration catalog backup. Existing sessions/steps keep
their meaning; old steps have NULL digests and simply look unsearched.

## Open Questions

None blocking. Stage 2 will decide how index targets register their
capabilities; the ledger's `source_kind`/`source`/`method` text vocabulary
already admits them.
