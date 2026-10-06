## Why

Requirement 1 of docs/plans/raw_requirements.md covers items "both recorded and non-recorded",
but a lookup seed must be an existing catalog entity, so items the operator holds outside any
synced source have no entry point. The decided design (2026-10-05, bead `data-processing-zos`,
catalog plan §12 "Non-recorded item entry") is a materialize-a-seed operation: an explicit
operator command that ingests the evidence bundle available at the time — innate image metadata
first (a local-bytes phase follows), supplied-alongside references second at declared or
operator-asserted status — and creates a provenance-recorded stub the whole existing pipeline
(plan, lookup, candidates, review, later real sync) already works on.

## What Changes

- New `catalog seed create` command and `SeedMaterializationService`: the operator supplies one
  or more URLs where the item was found (every URL must resolve to a stable post identity), an
  optional note, and an optional declared MD5. All URLs must be pairwise consistent (no two
  different stable ids for the same platform).
- The invocation is provenance-recorded as an `operator_seed` import run whose retained raw
  payload is the bundle itself; the stub post (availability `unknown`, the primary URL as its
  canonical URL, raw observation attached) carries every URL both as a `source_url` reference
  and as a typed `provider_id` reference, so `external_post_id` planning works from the stub
  exactly as from a synced post.
- Materialization is idempotent (re-running the same bundle reuses the import run and writes no
  duplicate rows), decides nothing (no candidates, no relations, no identity claims), and
  reports only counts and identifiers.
- The local-bytes phase (hashing a file the operator holds through the existing inspection
  machinery into verified asset facts) remains open on the bead; this change lands the entry
  point and reference intake.

## Impact

- Capabilities: `bounded-candidate-lookup` (one ADDED requirement — the seed-entry complement
  of its existing-seed requirement).
- Code: new `media_catalog/seeding/` service, `cli.py` `seed` command group; tests in
  `tests/test_seeding.py`.
- No schema migration: import runs, raw observations, posts, and external references all exist.
