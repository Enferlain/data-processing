# Tasks: index-backed artist_identifier

## 1. Projection: capabilities + artist tables

- [x] 1.1 `SnapshotInfo.capabilities` read from `index_meta` (`capabilities` key;
      absent key resolves to the post method set for back-compat).
- [x] 1.2 `IndexTarget.serves(method)`; `lookup()` rejects methods outside the
      target's capabilities with the existing ValueError shape.
- [x] 1.3 `_lookup_plan("artist_identifier")`: canonicalized URL → artist entry rows
      (artist id, name, other names via GROUP_CONCAT, matched URL, active flag).

## 2. Importer: e621 artists export

- [x] 2.1 `importers/e621_artists_export.py`: stream the gzipped CSV, parse
      `other_names` (postgres array) and `active_urls`/`inactive_urls`
      (whitespace-separated), canonicalize each URL, build `artist_entries` /
      `artist_names` / `artist_urls` in a lookup-v1 projection with capabilities
      `artist_identifier`, artifact path+digest in `index_meta`, scope-aware
      revision, atomic swap, checksum verification, absent-column reporting.

## 3. Catalog + planner + executor

- [x] 3.1 Migration `0033_artist_identifier_leads.sql`: `discovery_artist_leads`
      table (session, provider, artist native id, name, other names, matched URL,
      active, snapshot revision, recorded_at); schema version 33.
- [x] 3.2 Planner: `artist_identifier` in `INDEX_METHODS`; per-target capability
      gating (unserved methods excluded with a capability reason); probe material
      from the shared `artist_identifier_values` collector (account profile URLs,
      x/twitter status→profile derivation, source URLs verbatim).
- [x] 3.3 Executor: `_index_lookup_values` serves `artist_identifier` via the
      shared collector; `_run_index_step` records artist hits as
      `discovery_artist_leads` rows and contains sqlite failures to the step.

## 4. CLI

- [x] 4.1 `catalog index import --export {posts,artists}` (default posts; artists
      default target name `<provider>-artists`, default path under
      `<catalog-stem>-indexes/<provider>-artists/`); `--download` fetches the named
      export. `register` requires an explicit `--name` for non-post projections.

## 5. Verification

- [x] 5.1 Unit tests: artists import (fixture pinned to the real 12-column header),
      capability gating, artist lead recording, zero-result freshness invalidation,
      absent-column reporting, review-fix regressions (teach-skip, numeric-id
      guard, duplicate-id replacement, register refusal).
- [x] 5.2 Real-data validation: real artists export downloaded + imported
      (129,421 entries, 16 s, integrity ok); X seed resolves
      `greengird11e` → e621 artist `greengirdle` offline; 256 seed probes in
      6.6 ms; scheme-repair + quoted/unquoted array parsing fixed against the
      real artifact and posts projection re-imported.
- [x] 5.3 Docs (`docs/tools/local-search-indexes.md`), design note §3 update,
      CHANGELOG.
