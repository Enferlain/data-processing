## Why

Migration 0018 made anchorless raw-observation identity content addressing over `(object_kind,
native_id, payload)` — but that key conflates *sources*: the real catalog holds two danbooru vs
aibooru candidate-lookup groups where both instances returned byte-identical bodies, so the second
source's observation silently folds into the first writer's row (Bead `data-processing-7o0`, the
review finding from the 40x pass). An observation is "this source reported these bytes"; the
source belongs in the identity.

## What Changes

- Migration 0019 replaces 0018's two partial unique indexes with platform-scoped ones:
  `(platform_id, object_kind, native_id, raw_payload_id)` and `(platform_id, object_kind,
  raw_payload_id)`, same anchorless WHERE clauses. Sharing becomes intra-source only — retries and
  re-probes against the *same* source share one observation by design; different sources never do.
- `store_raw` anchorless conflict targets and the resolve-back SELECT gain `platform_id`; anchorless
  retention now **requires a declared source platform** (both anchorless flows — candidate-lookup
  retention and library probes — always declare one).
- The sharing is blessed by decision, not accident: policy comments at the two anchorless call
  sites state that identical bytes from the same source resolve to one observation referenced by
  any number of requests/probes, each keeping its own outcome and timestamps.
- `scripts/repair_anchorless_observations.py` (dry-run by default): dedups pre-0018 anchorless
  duplicates under the 0018 (stricter) definition so the migration chain passes — the
  0018-comment trigger surgery (drop immutability triggers, keep the earliest row per group,
  dynamically re-point any referencing rows, recreate triggers from stored SQL), with same-platform
  and cross-platform folds reported separately and `PRAGMA foreign_key_check` verification.
- Tests: two platforms with identical bytes land two observations with their own attribution;
  same-platform re-intake resolves to one row; the repair script's plan/apply on fixture catalogs
  (unreferenced fold, referenced fold needing re-point, cross-platform group left intact under the
  new identity); upgrade of a repaired copy through 0019.

## Capabilities

- **New Capabilities:** none.
- **Modified Capabilities:**
  - `provenance-kernel` — new requirement: source-report observation identity (anchored rows keyed
    by their anchor; anchorless rows content-addressed *per source*, requiring a declared source).

## Impact

- `src/media_catalog/migrations/0019_source_scoped_anchorless_identity.sql`,
  `src/media_catalog/persistence/remote.py` (conflict targets, platform requirement),
  `src/media_catalog/candidate_lookup/service.py` + `src/media_catalog/library/probes.py` (policy
  comments), `scripts/repair_anchorless_observations.py` (new), `tests/test_catalog_writer.py` +
  `tests/test_repair_anchorless.py` (new), `CHANGELOG.md`.
- Repair is operator-run on the real catalog (out-of-band by design); the migration itself remains
  fail-loud on unrepaired duplicates.
