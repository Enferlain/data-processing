# Tasks

## 1. Persistence and projection

- [x] 1.1 Migration `0032_search_index_registration.sql`:
  `search_index_registrations` (unique target name — the identity, path is
  mutable — provider key, format, private path, revision mirror, timestamps)
  and `discovery_index_hits` (session, provider, post id, md5, sources json,
  snapshot revision) with indexes; records validation. Verify: schema tests.
- [x] 1.2 `media_catalog/search_index/projection.py`: lookup-v1 schema
  (posts/post_sources/post_artists/index_meta incl. artifact path+digest),
  atomic build+swap, open read-only, snapshot metadata access. Verify: unit
  roundtrip incl. rebuild-from-artifact equivalence and untouched artifact.
- [x] 1.3 e621 exporter (`importers/e621_export.py`): stream gzipped CSV,
  verify SHA-256 when supplied, map columns to lookup-v1 (md5, sources,
  artists from tag string, parent, dims, dates, deleted). Verify: importer
  tests with a small recorded CSV.gz fixture.

## 2. Discovery integration

- [x] 2.1 Planner: registered indexes as `index`-kind target rows (same
  methods/material digests as providers; missing-file targets excluded with
  reason), ordered catalog → indexes → providers; attempt version
  `lookup-v1.<revision>`. Verify: planner tests (ordering, policy filters,
  dry-run/search-state rows, path-move preserves target).
- [x] 2.2 Executor: offline index step execution (md5/url/id/artist-name
  lookups), zero-result scope with snapshot, `discovery_index_hits` leads
  rows, no request budget use. Verify: offline session test against a
  fixture projection.
- [x] 2.3 Fetch bridge: wave-A unions index hits with lookup hits; dedupe;
  fetch-only-creates-facts invariant. Verify: bridge test with fake fetch.
- [x] 2.4 Teach-on-result at the shared post-commit boundary
  (`NormalizedPageWriter` hook) with failure containment; covers fetch,
  metadata sync, candidate lookup, and discovery with no per-entry-point
  wiring. Verify: each entry point teaches; index write failure never fails
  the catalog write; fetch-then-offline-md5-hit test.

## 3. CLI, docs, gates

- [x] 3.1 `catalog index register|list|import` commands (maintenance,
  separate from discovery); index targets visible in `discover --dry-run`
  and `--search-state`. Verify: CLI tests incl. registration validation and
  path-move preserving identity.
- [x] 3.2 Docs (`docs/tools/media-catalog.md` index section +
  design-note cross-link) and CHANGELOG. Verify: review.
- [x] 3.3 Full gates: `uv run pytest`, `ruff check .`, `ruff format`
  (changed), `ty check src`, `openspec validate`. Verify: all green.

## 4. Gated follow-up (not part of the first vertical slice)

- [ ] 4.1 danbooru snapshot importer (`importers/danbooru_snapshot.py`):
  declared column map over the operator-supplied artifact, same projection
  contract as e621. Starts only once a concrete artifact exists; its layout
  is verified then and recorded in `index_meta.builder_version`. Verify:
  importer tests against the real artifact sample.
