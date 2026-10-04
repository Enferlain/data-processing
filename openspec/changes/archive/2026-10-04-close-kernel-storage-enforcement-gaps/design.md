## Context

The kernel spec binds several audit surfaces ahead of storage enforcement, and Bead
`data-processing-ts5` tracks closing them. A two-part writer-audit over `src/` — UPDATE/DELETE
statements plus `INSERT ... ON CONFLICT DO UPDATE` upserts, which fire UPDATE triggers — found no
DELETE statements at all and exactly these legitimate mutation paths: `remote_requests`
attaches `raw_observation_id` after insert (circular reference with
`raw_observations.remote_request_id`); `remote_runs` advance status/counters/outcome mid-run;
`observations` re-import refreshes the event's current projection (history in
`observation_revisions`); `adoption_attempts` re-record outcomes via upsert; candidates update
review state and score; `match_evidence` updates rematerialized digests. See proposal.md for why.

## Goals / Non-Goals

**Goals:**

- Storage-level enforcement for every surface the kernel spec names, in one additive migration.
- Zero breakage of audited legitimate write paths, proven by tests that exercise those paths.

**Non-Goals:**

- No table rebuilds, data changes, or code changes; no purge/redaction workflow design (a future
  operator-initiated purge needs its own reviewed change that supersedes rows rather than
  deleting history — the no-delete triggers deliberately force that design); no
  epistemic-status columns (they land with the relationship model).

## Decisions

### Enforcement strength follows the writer-audit, table by table

Insert-only tables (`raw_observations` — upserts are `DO NOTHING`; `post_tag_observations`;
`observation_revisions`; both decision tables) get 0009-style unconditional no-update and
no-delete triggers. Tables whose current fields legitimately update (`observations`,
`adoption_attempts`, both candidate tables, `match_evidence`, the evidence join tables) get
no-delete only — deletion is the ledger-destroying operation the kernel forbids, while current
fields are the designed projection layer whose history lives in revisions and decisions.
Alternative rejected: blanket no-update everywhere (breaks re-import idempotency, retry
re-recording, review, and rematerialization paths the audit confirmed); column-scoped no-update
triggers on the current-field tables (adds enforcement complexity for no additional kernel
guarantee — the requirement forbids deletion and revision-in-place, not projection refresh).

### `remote_requests` gets a column-conditional trigger rather than a state machine

Every column is immutable after insert except `raw_observation_id` changing from NULL to a value.
The attach is inherent to the circular reference between requests and their retained source
reports, so it stays legal; any other change aborts. Alternative rejected: restructuring the
writer to write in one statement (gratuitous churn for a two-step that is already transactional);
a state column with terminal-immutability (the 0007 pattern) — rows are terminal at insert except
the attach, so a state machine adds a column for nothing.

### `remote_runs` gets the house immutable-inputs pattern

The 0007/0006 trigger shape: abort when any declared input (platform, instance, operation,
target, adapter/schema versions, the four budgets, `started_at`, `resumed_from_run_id`) changes;
origin columns remain covered by their existing 0008/0010 triggers. State, counters,
`budget_boundary`, `retry_after`, diagnostic, and `finished_at` advance freely — the audited
`finish_remote_run` path depends on that.

### One migration, messages that name their surface

Each trigger's abort message names its table ("source reports are append-only", "remote run
inputs are immutable", …) so rejections are diagnosable and test-assertable with the house
`pytest.raises(sqlite3.IntegrityError, match=...)` idiom. Alternative rejected: splitting across
multiple migrations — the surfaces form one requirement and one review unit.

## Risks / Trade-offs

- [An unaudited write path breaks at runtime] → The full test suite exercises every writer; the
  migration is additive and every gate must stay green. Any failure surfaces a path the audit
  missed, and the trigger gets rescoped deliberately rather than dropped.
- [No-delete triggers block a future purge/redaction feature] → Accepted and intentional: purge
  needs a reviewed design (tombstoning or row supersession) that this enforcement forces it to
  have. Recorded as a known consequence, not handled here.
- [Trigger count grows the schema surface] → Bounded: one or two triggers per table, all named
  after their surface, no logic beyond column comparison.

## Migration Plan

Migration 0012 only; `PRAGMA user_version` bump via the existing engine; fresh-create and
upgrade paths both covered by schema tests. Rollback is the previous schema version; no data is
transformed, so nothing to restore.

## Open Questions

- None deferred: the two-part writer-audit resolved the only design-shaping unknown (which
  tables mutate legitimately, including upsert paths).
