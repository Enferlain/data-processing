# Proposal

## Why

Stage-1 discovery policy made searching controllable, but every subject still
hits live providers first: local knowledge ends at the catalog boundary, so
discovery recrawls what a public dataset or yesterday's results already
answer. Roadmap P0.2 (local and external database discovery) and the stage-2
design note (`docs/plans/search-indexing-design.md`, bead
`data-processing-an1`) call for reusable local indexes that are search
infrastructure — never truth, never copied into the primary catalog.
- **Index registration** (migration `0032`): `search_index_registrations`
  binds a provider-scoped lookup database to a discovery target name, with
  snapshot revision and private path (`managed_roots.private_path`
  precedent). The target name — not the path — is the identity: moving the
  file and updating the registration preserves search history and freshness.
- **`lookup-v1` projection** (`media_catalog/search_index/`): our own SQLite
  format (posts/post_sources/post_artists/index_meta with md5/url/artist
  indexes) built from raw provider artifacts — importer for e621's official
  daily gzipped-CSV DB exports (SHA-256 verified). Raw artifacts are
  retained untouched beside the projection (their path and digest recorded
  in `index_meta`); the projection is derived and rebuildable. The danbooru
  snapshot importer is a follow-up task gated on the operator supplying a
  concrete artifact — e621 alone is the first complete vertical slice.
- **Discovery integration**: index targets appear as `index`-kind target
  rows in the existing planner/report/ledger — same policy filters, same
  freshness skips, same `--dry-run`/`--search-state` explanations. Index
  steps execute offline (no `--live`, no request budget), ordered before
  provider steps. Attempt versions are `lookup-v1.<snapshot_revision>`, so a
  refreshed snapshot replans every subject's index searches.
- **Hit bridge**: index hits land in a `discovery_index_hits` side table as
  leads; live sessions feed them into the existing wave-A `fetch_post`
  generation so only the normal fetch pipeline creates catalog facts. A
  zero-result index search records its snapshot and scope.
- **Teach-on-result at the shared post-commit boundary**: every path that
  persists a provider post — `catalog fetch`, direct metadata sync,
  candidate lookup, and discovery — writes through the normalized-page
  persistence layer; its post-commit hook upserts (post id, md5, sources,
  artist tags) into the provider's registered index (`origin='api'`).
  Failure-contained: index writes are logged at most as a diagnostic note
  and can never fail or roll back a catalog write; a no-op when no index is
  registered.
- **Maintenance CLI, separate from discovery**: `catalog index register`,
  `catalog index list`, `catalog index import` (offline build from a
  downloaded artifact). Refresh/download strategies stay later slices.

No external dataset rows enter `posts`/`observations`/`assets`.

## Capabilities

### New Capabilities

- `local-search-indexes`: registered provider lookup databases as offline
  discovery targets, with snapshot-scoped freshness, lead-only hit semantics,
  and the teach-on-result cache.

### Modified Capabilities

- `discovery-search-policy`: planner/execution requirements extended to the
  index target kind (offline execution, snapshot revision in freshness
  identity, tier ordering before providers).

## Impact

- Migration `0032` (registrations + hits tables); `media_catalog/search_index/`
  package (projection, importers, read interface); planning/execution/report
  integration in `discovery/`; teach hook in fetch/lookup completion paths;
  CLI (`cli_commands/` new `index` family); tests incl. import fixture data;
  docs + changelog. Full design: `docs/plans/search-indexing-design.md`.
