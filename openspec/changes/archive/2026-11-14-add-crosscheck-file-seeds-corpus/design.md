# Design

## Context

`run_crosscheck` (src/media_catalog/crosscheck.py) already branches on subject
kind: `post` subjects get `_post_materials`, anything else gets
`_file_materials` from `media_catalog.candidate_lookup.planning`, which returns
exactly one material — `VERIFIED_MD5` from `discovery_file_seeds.verified_md5`
with provenance `discovery_file_seed:<id>` — plus a stable revision digest over
the seed row. `crosscheck_items.seed_kind` has accepted `'file'` since 0034 and
`_reusable_run` already selects `seed_file_id` for non-post subjects. Nothing
new is needed in the lookup path; this change only makes file seeds selectable
as a corpus.

## Decisions

- **Corpus name `file-seeds`**, kebab-case beside `hash-material`/`downloaded`.
- **Canonical subjects: `min(discovery_file_seed_id) GROUP BY verified_md5,
  verified_sha256`.** Mirrors `find_file_seed_id`, which defines the canonical
  seed for a hash pair as the lowest id; the 0031 hash index is deliberately
  non-unique, so catalogs may hold duplicate rows for one file and
  crosschecking both would double-count items and double-spend requests.
  Folder ingest is idempotent, so the grabber batch is already duplicate-free —
  the grouping protects catalogs with pre-existing duplicates.
- **Migration 0035 rebuilds `crosscheck_batches`** to widen the `corpus` CHECK
  to include `file-seeds` (SQLite cannot alter a CHECK in place). Follows the
  0031 CHECK-widening convention: create `_rebuilt`, copy rows with explicit
  ids, drop, rename. The migration runner disables foreign keys for the script
  (database.py), so the drop is safe while `crosscheck_items` references the
  table; the name is unchanged afterwards, so no FK clause rewrites are needed.
  Explicit-id inserts keep the AUTOINCREMENT sequence correct. Replay-safe:
  the rebuilt table is `IF NOT EXISTS` and repopulated from the live table.
  `crosscheck_items` is untouched — its CHECK already allows `'file'`.
- **Honest skips, no special cases.** File seeds have no source-URL or
  status-id material, so providers that support those strategies record
  `skipped/no-query-material` (artist strategies are skipped silently as for
  posts, since they always need a search term). The metadata-only note stays
  post-specific: a file seed always carries its one md5 material.

## Risks

- 24k subjects × providers is a long batch; nothing new — budgets, resume, and
  run reuse are the existing controls and the batch key isolates the corpus.
- Widening a CHECK is backward-compatible for readers but a 0035 database
  opened by older code writing `file-seeds` batches would violate the old
  CHECK; single-operator catalog, acceptable (same as every migration).

## Migration Plan

One additive-in-effect migration (0035). Rollback is the standard pre-migration
catalog backup; the rebuild preserves all batch and item rows.
