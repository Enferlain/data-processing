## Why

The provenance-kernel spec's storage-enforced audit-immutability requirement binds ahead of
enforcement for several surfaces: source reports, provenance events, the review and evidence
ledger, `remote_requests`, `adoption_attempts`, and `post_tag_observations` are append-only by
writer convention today, and `remote_runs` inputs are immutable only for the origin columns.
The spec names storage enforcement as tracked follow-up work (Bead `data-processing-ts5`); this
change closes those gaps so the kernel's strongest guarantees are schema guarantees.

## What Changes

- One additive migration (0012) adds storage-level enforcement, shaped by a two-part writer
  audit (UPDATE/DELETE statements and `INSERT ... ON CONFLICT DO UPDATE` upserts, which fire
  UPDATE triggers):
  - **no-update and no-delete** for insert-only tables: `raw_observations`,
    `post_tag_observations`, `observation_revisions`, `account_candidate_decisions`,
    `post_candidate_decisions`;
  - **no-delete only** for rows with legitimate current-field updates: `observations` (re-import
    refreshes the event's current projection while revisions retain history),
    `adoption_attempts` (re-recorded outcomes), `account_match_candidates` and
    `post_match_candidates` (review state and score), `match_evidence` (rematerialized digests),
    and the two candidate-evidence join tables (evidence linkage survives);
  - **conditional immutability for `remote_requests`**: every column immutable after insert
    except attaching `raw_observation_id` from NULL — the writer's legitimate two-step for the
    circular reference with `raw_observations.remote_request_id` — plus no-delete;
  - **immutable inputs for `remote_runs`** matching the 0007/0006 house pattern: platform,
    instance, operation, target, adapter/schema versions, budgets, `started_at`, and
    `resumed_from_run_id` cannot change once the run begins; state, counters, outcome, retry,
    diagnostic, and finish time keep advancing freely.
- No data changes, no table rebuilds, and no code changes are expected — the audited write paths
  already conform.
- The provenance-kernel spec's audit-immutability requirement is updated: its enumeration covers
  the newly protected surfaces with their exact enforcement strength, its follow-up-work caveat
  is removed, and it gains scenarios for rejected review/evidence deletion, accepted legitimate
  current-field and run/request updates, and the new-table rule.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `provenance-kernel`: the "Storage-enforced audit immutability" requirement is rewritten with
  the full protected enumeration and enforcement strengths; the follow-up caveat is removed and the Purpose's writer-convention caveat is replaced by
  the named weaker strengths. No other requirement changes; `remote-metadata-sync` already matches the run-input behavior this
  enforces.

## Impact

- New migration `src/media_catalog/migrations/0012_kernel_storage_enforcement.sql` with twenty
  triggers.
- New focused tests attempting each blocked mutation (house idiom:
  `pytest.raises(sqlite3.IntegrityError, match=...)`) and exercising the legitimate paths
  (remote-run state advance, remote-request raw-observation attach, provenance-event re-import
  refresh, candidate review updates).
- Tracking: Bead `data-processing-ts5`.
