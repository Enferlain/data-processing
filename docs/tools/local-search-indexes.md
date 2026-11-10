# Local search indexes (lookup-v1 projections)

Discovery can search registered local indexes before touching the network: one disposable SQLite
lookup database per provider, built from raw provider artifacts, treated as search infrastructure
and never as truth. An index hit means "this provider probably has this post at this snapshot" —
only the normal fetch pipeline creates catalog records.

```bash
uv run catalog index import catalog-output/catalog.sqlite3 \
   --provider e621 --download --json
uv run catalog index list catalog-output/catalog.sqlite3 --json
```

`--download` is the explicit network path: one request to e621's public db_exports listing,
one **complete** streamed artifact download (identifying User-Agent; the transfer is never
bounded by `--max-records`, which limits only how many rows are imported), SHA-256 verified
against the listing before the import reads it, retained under
`<catalog-stem>-indexes/e621/downloads/posts.csv.gz`. A matching existing artifact is
reused without a second download — so for e621, re-running `import --download` **is** the
refresh: a newer export is a new checksum, a new snapshot revision, and every subject's
index searches replan. Prefer `--artifact` with your own file when you already downloaded
it (optionally with `--checksum`).

`import` verifies the published SHA-256 when supplied (always, with `--download`), streams
the artifact with bounded memory into `<catalog-stem>-indexes/<provider>/lookup.sqlite`
(md5 / normalized source URL / artist-tag indexes), records the snapshot identity
(artifact path and digest, revision, scope, record counts, builder version) in the
projection, and swaps it into place atomically. Source-array elements that pack several
URLs (newline-separated or jammed together — 37% of source-bearing rows in the real
2026-11-09 export) are split into one lookup key per embedded URL. Optional columns absent
from the export are reported in `columns_absent` instead of silently degrading: the real
posts export has **no `tag_string_artist`** (artist tags are not separable in this
artifact), so artist rows come only from teach material until the artist exports land in a
later slice. The raw artifact is retained untouched — the projection is always rebuildable
from it, never the reverse. `register` binds an existing projection to a target name (the
identity — moving the file and re-pointing the registration preserves search history and
freshness); `list` shows registrations and any file problems.

Registered indexes then appear in `catalog discover` as ordinary `index`-kind targets with the
same policy filters, freshness skips, and `--dry-run`/`--search-state` explanations as every
other target. Index steps run offline (no `--live`, no request budget) and are ordered before
provider steps: catalog, then indexes, then the network. A refreshed snapshot is a new strategy
version (`lookup-v1.<revision>.g<generation>`) — the revision encodes the artifact digest,
builder, and actual import scope (`full`, or the bounded prefix when `--max-records` stopped
early, so a bounded shakeout and a full import are different snapshots), and the generation
counts teach mutations — so an expanded import, a refresh, or newly taught content replans
every affected subject. In
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
