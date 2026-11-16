# provenance-kernel Delta

## ADDED requirements

### Requirement: As-of revision playback is an indexed seek

The catalog SHALL maintain a playback index on
`observation_revisions(observation_id, observation_revision_id DESC)` so the
as-of query — the latest revision of one observation at or before a cutoff,
`ORDER BY observation_revision_id DESC LIMIT 1` under a revision-id cutoff —
resolves as a single indexed seek without scanning or sorting the table. The
append-only enforcement on `raw_observations` and `observation_revisions`
(BEFORE UPDATE/DELETE abort triggers) SHALL stay in place and be
regression-tested.

#### Scenario: as-of query plan is one indexed seek

- **WHEN** `EXPLAIN QUERY PLAN` runs the as-of revision query on a migrated
  catalog
- **THEN** the plan searches the playback index and reports no table scan

#### Scenario: provenance tables stay insert-only

- **WHEN** an UPDATE or DELETE targets `raw_observations` or
  `observation_revisions`
- **THEN** the statement aborts with the immutability trigger's message
