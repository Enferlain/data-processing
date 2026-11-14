# Design: danbooru bootstrap index

## Context

`docs/plans/booru_investigation.md` established the bootstrap model: a
community snapshot seeds a disposable lookup-v1 projection; live lookups and
teach-on-result maintain encountered knowledge; incremental API refresh is a
later lifecycle. The chosen artifact is `nyanko-devs/danbooru2026`
`metadata/posts-snapshot.parquet` (4.1 GB, 11,740,666 rows; verified schema
superset including `tag_string_artist` and `pixiv_id`).

## Decisions

### D1 — Parquet via pyarrow, row-group streaming

The artifact format is parquet; pyarrow (runtime dependency, added) reads it
with bounded memory via `iter_batches`. Row conversion goes through
`.as_py()` scalars (pyarrow scalar `__index__` misbehaves on nulls — caught in
the real-artifact shakeout). Rate ≈ e621 CSV import territory; progress lines
reuse the existing 500k-row stderr cadence.

### D2 — Post-method capabilities INCLUDING artist names

Unlike the e621 posts export, the snapshot carries `tag_string_artist`, so the
danbooru projection declares the full post method set including
`artist_exact_name`/`artist_alias`/`artist_text` (per-target capabilities).
The artist-name lookups answer against `post_artists` rows imported from the
tag string.

### D3 — Same proven transforms

Danbooru `source` strings pass through the exact e621 pipeline (whitespace +
embedded-URL split, scheme repair, canonicalization) so probes match across
indexes; x-status normalization applies on ingest. `is_deleted OR is_banned`
folds into the deleted flag. Scope-aware revision and `columns_absent`
reporting mirror the e621 importer contract.

### D4 — Bootstrap-only semantics, explicit

The revision identifies the snapshot digest + builder + scope; nothing claims
currency. `--download` is NOT offered for danbooru (no provider listing
endpoint like e621's); the operator supplies the artifact path. Incremental
refresh (watermark + overlap, per the investigation doc) and `pixiv_id`
foreign-id lookups are recorded follow-ups, not scope.

## Risks / trade-offs

- Snapshot is mid-2026: misses fall through to live lookups exactly like e621
  bounded imports did — the freshness model already covers this.
- pyarrow adds a binary dependency — justified by the artifact format; no
  other reader path exists for parquet.
