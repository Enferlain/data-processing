# Design

## Decisions

- **Index exactly as the 2ai guidance specified**: `(observation_id,
  observation_revision_id DESC)` — the as-of query's equality column first,
  the playback ordering second, so `ORDER BY ... DESC LIMIT 1` stops at the
  first match. No extra columns: the query's SELECT list is the table's own
  row, and the seek's cost is the point, not index-only row coverage.
- **Enforcement is test-only here** — the triggers already exist (0013-era
  audit immutability); re-adding them would be noise, but the bead's
  acceptance wants them pinned, so the change's tests UPDATE and DELETE
  against both tables and assert the aborts.
- **EXPLAIN as a test**, not a doc claim alone: the test runs `EXPLAIN
  QUERY PLAN` and asserts `USING INDEX` on the playback index with no `SCAN` — SQLite's
  plan text is stable across versions for this shape, and if a future
  version words it differently the test fails loudly rather than the
  contract silently rotting.

## Risks

- Covering-index wording differences across SQLite versions could flake the
  EXPLAIN assertion; mitigated by matching the family of plan strings
  (accept `SEARCH ... USING COVERING INDEX`, reject any `SCAN`).

## Migration Plan

One additive `CREATE INDEX IF NOT EXISTS` (0039). Backup-test pins move
38→39. Rollback is the standard pre-migration backup.
