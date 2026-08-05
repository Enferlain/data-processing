## 1. Package and CLI foundation

- [x] 1.1 Create the `media_catalog` package skeleton and retain the existing `x_likes` package unchanged.
- [x] 1.2 Add the `catalog` console entry point and implement the documented subcommand/`--json` argument structure.
- [x] 1.3 Add shared result and error formatting that keeps private paths and raw content out of default diagnostics.

## 2. Catalog database and migrations

- [x] 2.1 Implement packaged, numbered SQL migration discovery and transactional `PRAGMA user_version` upgrades, including future-version rejection.
- [x] 2.2 Add the initial platform, import-audit, raw-observation, account/snapshot, post/participant/relation, provenance, media-occurrence, and asset tables with constraints and indexes.
- [x] 2.3 Implement catalog connection lifecycle settings, transactions, schema reporting, SQLite/foreign-key integrity checks, and summary counts.
- [x] 2.4 Implement the runtime FTS5 probe plus rebuildable FTS search and parameterized `LIKE` fallback with the same result shape.
- [x] 2.5 Add migration/database tests for fresh creation, supported upgrade, future-version rejection, foreign keys, integrity, and same-native-ID cross-platform isolation.

## 3. Normalized persistence and queries

- [x] 3.1 Define immutable normalized input records and validate platform keys, native IDs, roles, event types, timestamps, media ordering, and hashes.
- [x] 3.2 Implement the catalog writer for raw payloads/observations, stable account/post upserts, append-only snapshots/events, participants/relations, media occurrences, and legacy asset links.
- [x] 3.3 Implement schema, doctor, stats, and search services with liked/bookmarked filtering and stable structured output.
- [x] 3.4 Add tests for temporal account metadata, missing profile fields, roleful authorship, raw round-tripping/deduplication, overlapping events, media/asset separation, and both search backends.
- [x] 3.5 Add network-denial tests proving catalog creation, inspection, search, and normalized writes remain offline.

## 4. Import-run framework and x-likes importer

- [x] 4.1 Implement streaming source digests, atomic import-run lifecycle, stable record/event keys, per-entity reconciliation counts, and bounded failure diagnostics.
- [x] 4.2 Open legacy `x_likes` databases read-only and validate the required tables/columns without changing the source.
- [x] 4.3 Map legacy accounts, posts, fetch/unavailable state, author roles, liked observations, raw JSON, media occurrences, verified hashes, and non-owning local paths into normalized records.
- [x] 4.4 Add synthetic legacy-database tests for enriched and partial rows, unavailable content, missing local files, exact repeat imports, overlapping updates, rollback, and source immutability.

## 5. xarchive bookmark importer

- [x] 5.1 Validate supported xarchive root/record shapes and parse posts, real author fields, folders, status, media order, quotes, replies, and raw bookmark objects without synthetic names.
- [x] 5.2 Persist xarchive records through the shared writer with bookmarked observations, account snapshots, media occurrences, post relations, raw payloads, and reconciliation counts.
- [x] 5.3 Add redacted or synthetic xarchive tests for missing author fields, multiple media, folders, quotes/replies, unavailable records, malformed schemas, exact repeats, and overlap with liked posts.

## 6. CLI integration, documentation, and verification

- [x] 6.1 Wire `catalog init`, `schema`, `doctor`, `stats`, `search`, and both `ingest` commands to the services and cover human/JSON output and exit codes with CLI tests.
- [x] 6.2 Add a catalog usage guide covering creation, both imports, reconciliation, event-filtered search/stats, privacy, backups, and the unchanged `x-likes` workflow.
- [x] 6.3 Run formatting, lint, the full Python 3.13 test suite, package build/install smoke tests, and OpenSpec strict validation.
- [x] 6.4 Run a local smoke import of the user-provided xarchive export into an ignored temporary catalog and verify reconciliation, integrity, idempotency, and liked/bookmarked queries without exposing private content.
