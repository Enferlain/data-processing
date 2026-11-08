# Proposal

## Why

Discovery sessions today re-execute every applicable step on every run, accept
or exclude sources only by editing code, offer no recheck control, and keep no
cross-session record of what was already searched — so scaling discovery to
more subjects means repeating provider work and giving the operator no way to
ask "what has been searched, when, and is it still fresh?" Stage 1 of the
discovery/search roadmap (operator brief 2026-11-08) is precisely this control
and transparency layer; search optimization/indexing (stage 2) and additional
providers (stage 3) build on it.

## What Changes

- **Search policy object** — one explicit operator-facing policy (subject
  selection by explicit inputs, source include/exclude, method filter,
  trails-only vs active search, recheck mode `unsearched`/`stale`/`force` with
  a staleness age, existing request/time budgets) carried through planning and
  execution instead of scattered flags.
- **Durable search-attempt ledger** — append-only `discovery_search_attempts`
  rows keyed by subject × search target (kind + source) × method × strategy
  version × query-evidence digest, with timing, outcome, result count, and the
  searched scope; answers "was this ever searched, when, how, what happened,
  and is it fresh under today's policy" without re-deriving it from sessions.
- **Policy-aware planner** — the existing offline planner additionally records
  each step's query-evidence digest and consults the ledger: fresh successful
  attempts become `skipped` with the prior attempt named, policy-excluded
  targets/methods become `excluded` with the policy reason; the plan remains
  fully explainable.
- **Dry-run** — `--dry-run` reports the plan (including freshness decisions)
  without executing any step, local or remote.
- **Queue/execution states** — steps not started because the budget ran out
  become `deferred` (retryable) instead of `failed`; sessions track requests
  used; zero-result successful searches stay `complete` with their scope and
  never assert nonexistence.
- **Multi-subject runs** — `discover` accepts repeated subject inputs; subjects
  run sequentially under one shared budget with per-status progress counts in
  the report and per-subject completion lines in the human output. Execution
  stays sequential with existing per-adapter pacing; the persisted states make
  later concurrency additive.
- **Search-state inspection** — `--search-state` reports, per subject ×
  target × method, the latest attempt (when, outcome, version, evidence
  digest) and its freshness verdict under a supplied policy, without network.
- Migration `0031`: attempt ledger table, `query_digest`/`strategy_version` on
  `discovery_steps`, `requests_used` on `discovery_sessions`.

Not in this change (stage 2/3, deliberately deferred): local/imported/remote
index targets beyond the existing local catalog steps, incremental index
refresh, artist-identifier and reverse-image search methods, and new
providers. The policy/target/method vocabulary is data, not hardcoded
HTTP-provider assumptions, so those extend without schema redesign.

## Capabilities

### New Capabilities

- `discovery-search-policy`: operator control and transparency over what gets
  searched — policy object, freshness/recheck rules, the durable search-attempt
  ledger, queue/deferred states, dry-run planning, multi-subject run progress,
  and search-state inspection.

### Modified Capabilities

- `unified-discovery`: the planner requirement gains policy- and
  freshness-driven decisions (skip-with-reason on fresh attempts, exclusion by
  policy); execution gains deferred steps, per-step query-evidence digests,
  and dry-run sessions.

## Impact

- `src/media_catalog/discovery/`: new `policy.py`, `attempts.py`, `run.py`;
  `orchestration.py` extended (planner decisions, attempt recording) without
  absorbing the new responsibilities.
- `src/media_catalog/migrations/0031_discovery_search_policy.sql`; records
  validation for attempt rows.
- `src/media_catalog/cli_commands/discovery.py`: `discover` surface changes
  (repeatable subjects, `--include-source`/`--exclude-source`, `--method`,
  `--search-mode`, `--recheck`, `--stale-after`, `--dry-run`,
  `--search-state`).
- Tests: `tests/test_discovery_orchestration.py` and a new
  `tests/test_discovery_search_policy.py`; schema tests for migration 0031.
- No breaking CLI changes: single-subject invocations without policy flags
  behave as today except that previously successful searches are skipped as
  fresh by default (the feature's purpose); `--recheck force` restores the old
  always-execute behavior.
