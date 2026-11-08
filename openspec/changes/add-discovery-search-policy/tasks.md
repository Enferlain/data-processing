# Tasks

## 1. Persistence

- [x] 1.1 Migration `0031_discovery_search_policy.sql`: `discovery_search_attempts`
  table (subject FK triple with exactly-one CHECK, target/method/version/digest,
  status/outcome/result_count/scope/requests_used, session/step/run links,
  timing) + latest-per-key index; `discovery_steps.query_digest`;
  `discovery_sessions.requests_used` + `policy_json`;
  `discovery_file_seeds(verified_md5, verified_sha256)` index. Verify:
  `uv run pytest tests/test_catalog_database.py tests/test_discovery_schema.py`.
- [x] 1.2 Record validation + ledger module `discovery/attempts.py`
  history) with attempt status/outcome vocabulary in `records`. Verify: unit
  tests in `tests/test_discovery_search_policy.py`.
- [x] 1.3 Idempotent bare-file seeds: reuse an existing
  `discovery_file_seeds` row with identical verified hashes. Verify: repeat
  `discover --file` reports the same `seed_file_id`.

## 2. Policy and planning

- [x] 2.1 `discovery/policy.py`: `SearchPolicy`, CLI flag parsing/validation

  (include/exclude sources, methods, search mode, recheck mode, stale-after),
  method classification (trails vs active, per-method versions), pure
  `freshness_verdict`. Verify: unit tests for verdicts (fresh, stale, failed,
  version drift, force) and flag validation errors.
- [x] 2.2 `discovery/planning.py`: extract decision logic from
  `orchestration.plan` into `plan_searches()` producing explainable
  `PlannedSearch` rows with query digests, policy exclusions, and fresh skips
  from the ledger; `orchestration.plan` persists them. Verify: planner tests —
  policy exclusion reasons, fresh-skip naming the prior attempt, one
  provider/method success never satisfies another, changed evidence replans.
- [x] 2.3 Dry-run: `discover --dry-run` plans and reports without executing
  any step or writing attempts. Verify: dry-run test asserts all steps
  planned/skipped/excluded, zero attempts, no local execution.

## 3. Execution and runs

- [x] 3.1 Attempt recording + states in `orchestration.execute`: running →
  terminal attempts per executed step, `deferred` for budget-unstarted steps
  (no attempt), `requests_used` session updates, session summary `partial`.
  Verify: partial-failure and budget-deferral tests; zero-result attempt is
  complete/success with scope and fresh afterwards.
- [x] 3.2 `discovery/run.py` multi-subject `DiscoveryRunService`: sequential
  subjects under shared budgets, per-subject progress callback, aggregate
  report with per-status counts. Verify: multi-subject test — shared budget
  defers across subjects; rerun repeats no successful work.
- [x] 3.3 CLI surface in `cli_commands/discovery.py`: repeatable subject
  inputs, policy flags, `--dry-run`, `--search-state` inspection (decisions +
  ledger history + freshness verdicts, offline). Verify: CLI tests incl.
  unknown source/method rejection and `--search-state` output shape.

## 4. Verification and docs

- [x] 4.1 Behavior tests: freshness/force/stale, method and source
  independence, zero-result scope, partial failures, dry-run, persistence
  reopen (`tests/test_discovery_search_policy.py`), plus updated
  `tests/test_discovery_orchestration.py` expectations. Verify:
  `uv run pytest tests/test_discovery_search_policy.py tests/test_discovery_orchestration.py tests/test_bare_file_discovery.py tests/test_golden_discover.py`.
- [x] 4.2 Full gates: `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format` on changed files, `uv run ty check src`,
  `openspec validate add-discovery-search-policy`. Verify: all green.
- [x] 4.3 Docs + changelog: `CHANGELOG.md` entry (2026-11-08), user-facing
  docs for the new `discover` flags and default-skip behavior; duplication
  review against existing budget/pacing/session machinery. Verify: review
  pass, docs updated.
