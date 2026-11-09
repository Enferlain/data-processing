# Local search indexes (lookup-v1 projections)

Discovery can search registered local indexes before touching the network: one disposable SQLite
lookup database per provider, built from raw provider artifacts, treated as search infrastructure
and never as truth. An index hit means "this provider probably has this post at this snapshot" —
only the normal fetch pipeline creates catalog records.

```bash
curl -O https://static1.e621.net/data/db_export/posts.csv.gz   # operator downloads the artifact
uv run catalog index import catalog-output/catalog.sqlite3 \
   --provider e621 --artifact posts.csv.gz --json
uv run catalog index list catalog-output/catalog.sqlite3 --json
```

`import` verifies the published SHA-256 when `--checksum` is given, streams the artifact with
bounded memory into `<catalog-stem>-indexes/<provider>/lookup.sqlite` (md5 / normalized source
URL / artist-tag indexes), records the snapshot identity (artifact path and digest, revision,
record counts, builder version) in the projection, and swaps it into place atomically. The raw
artifact is retained untouched beside the projection — the projection is always rebuildable from
it, never the reverse. `register` binds an existing projection to a target name (the identity —
moving the file and re-pointing the registration preserves search history and freshness);
`list` shows registrations and any file problems.

Registered indexes then appear in `catalog discover` as ordinary `index`-kind targets with the
same policy filters, freshness skips, and `--dry-run`/`--search-state` explanations as every
other target. Index steps run offline (no `--live`, no request budget) and are ordered before
provider steps: catalog, then indexes, then the network. A refreshed snapshot is a new strategy
version (`lookup-v1.<revision>`), so every subject's index searches replan after a refresh. In
live sessions, index hits feed the same bounded `fetch_post` follow-up generation as provider
lookup hits.

Every provider post the catalog persists — via `catalog fetch`, metadata sync, candidate lookup,
or discovery — teaches that provider's registered index at the shared post-commit boundary
(origin `api`, confirmation time). Index writes are failure-contained: they can never fail or
roll back a catalog write, and rolled-back transactions teach nothing. Gelbooru and Sankaku
indexes therefore grow into persistent caches of encountered knowledge without any bulk crawl.

The e621 daily database exports (posts, artists, tags; gzipped CSV with published SHA-256,
listed at `/db_exports.json`) are the first artifact source. A danbooru metadata importer and
per-provider refresh strategies (watermark/sync) are planned follow-ups; the design is
`docs/plans/search-indexing-design.md`.
