## Proposal

### What

Covering index `observation_revisions(observation_id, observation_revision_id
DESC)` plus the documented as-of revision query it serves, and a regression
test pinning the already-enforced append-only triggers on
`raw_observations` and `observation_revisions`.

### Why

Bead `data-processing-i94` (2ai implementation guidance, from the bitemporal
provenance research triage) asked for two things. The enforcement half —
BEFORE UPDATE/DELETE abort triggers on both tables — already shipped with
the kernel-storage enforcement migration (verified live:
`raw_observations_immutable`, `raw_observations_no_delete`,
`observation_revisions_immutable`, `observation_revisions_no_delete`), so
this change pins it with tests instead of re-adding it. The query half is
genuinely missing: as-of playback (latest revision of an observation at or
before a cutoff) currently has no supporting index on the 3,147-row and
growing revision table. The cutoff is the revision id, not the bead's
`import_run_id` bounds: revision ids are monotone with import runs, and the
`import_run_id <= ?` shape resolves on the table's UNIQUE autoindex plus a
temp b-tree sort — failing the bead's own single-seek acceptance (verified
live).

### Scope

- Migration 0039: one playback index, `IF NOT EXISTS`, additive.
- As-of query documented in the kernel docs with its EXPLAIN contract
  (single indexed seek, no scan).
- Tests: index present on fresh catalogs; EXPLAIN QUERY PLAN shows the
  indexed seek; UPDATE/DELETE on both tables raise.
- Out of scope: any as-of projection/export surface (the research doc's
  wider program), schema changes to the revision table itself.
