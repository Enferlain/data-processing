## Proposal

Bootstrap a `danbooru` lookup-v1 posts index from the community snapshot
`nyanko-devs/danbooru2026` `metadata/posts-snapshot.parquet` (4.1 GB,
11,740,666 rows, verified schema includes `tag_string_artist` and `pixiv_id`),
imported by a new parquet importer. One-time bootstrap semantics per
`docs/plans/booru_investigation.md`: the snapshot seeds the projection; live
provider lookups and teach-on-result maintain encountered knowledge; no
incremental refresh in this slice.

## Why

The real-data cross-check proved complementarity (14/40 e621-miss subjects
resolved on Danbooru/Gelbooru live) but costs live requests every time. A
local danbooru index makes those hits offline and permanent, and the operator's
grabber corpus (24,160 md5 seeds, 12.9% e621 hit rate) gives an immediate
measurement population. `tag_string_artist` even restores the artist-tag
lookup methods e621's export cannot serve.

## What Changes

- `catalog index import --provider danbooru --artifact posts-snapshot.parquet`:
  parquet row-group streaming importer (pyarrow) → lookup-v1 posts projection
  (md5 / normalized source URLs / artist tags / provider id), default target
  `danbooru`, its own snapshot revision scope-encoded like the e621 importer,
  artifact retained untouched, `columns_absent` reporting.
- Danbooru source strings reuse the proven URL extraction (whitespace/embedded
  split, scheme repair, www-fold, x-status normalization); timestamps convert
  to ISO text; `is_deleted`/`is_banned` fold into the deleted flag.
- No new catalog schema; the projection is a disposable index file like the
  e621 ones. Danbooru projections serve the post methods INCLUDING the
  artist-name methods (per-target capabilities record them).

## Out of Scope

- Incremental API refresh / watermarks (investigation doc's later lifecycle).
- `pixiv_id` foreign-id lookups through the index (schema-ready follow-up:
  a `post_foreign_ids` side table + `external_post_id` foreign path).
- Danbooru artists-export `artist_identifier` (no URL-bearing local artifact).
