# Tasks

## 1. Persistence and projection

- [ ] 1.1 Migration `0032_search_index_registration.sql`:
  `search_index_registrations` (unique target name, provider key, format,
  private path, revision mirror, timestamps) and `discovery_index_hits`
  (session, provider, post id, md5, sources json, snapshot revision) with
  indexes; records validation. Verify: schema tests.
- [ ] 1.2 `media_catalog/search_index/projection.py`: lookup-v1 schema
  (posts/post_sources/post_artists/index_meta), atomic build+swap, open
  read-only, snapshot metadata access. Verify: unit roundtrip incl.
  rebuild-from-artifact equivalence.
- [ ] 1.3 e621 exporter (`importers/e621_export.py`): stream gzipped CSV,
  verify SHA-256 when supplied, map columns to lookup-v1 (md5, sources,
  artists from tag string, parent, dims, dates, deleted). Fixture-driven.
  Verify: importer tests with a small recorded CSV.gz fixture.
- [ ] 1.4 danbooru snapshot importer (`importers/danbooru_snapshot.py`):
  declared column map, same projection contract. Verify: importer tests.

## 2. Discovery integration

- [ ] 2.1 Planner: registered indexes as `index`-kind target rows (same
  methods/material digests as providers; missing-file targets excluded with
  reason), ordered catalog → indexes → providers; attempt version
  `lookup-v1@<revision>`. Verify: planner tests (ordering, policy filters,
  dry-run/search-state rows).
- [ ] 2.2 Executor: offline index step execution (md5/url/id/artist-name
  lookups), zero-result scope with snapshot, `discovery_index_hits` leads
  rows, no request budget use. Verify: offline session test against a
  fixture projection.
- [ ] 2.3 Fetch bridge: wave-A unions index hits with lookup hits; dedupe;
  fetch-only-creates-facts invariant. Verify: bridge test with fake fetch.
- [ ] 2.4 Teach-on-result hook on fetch/lookup completion with failure
  containment. Verify: fetch-then-offline-md5-hit test.

## 3. CLI, docs, gates

- [ ] 3.1 `catalog index register|list|import` commands (maintenance,
  separate from discovery); index targets visible in `discover --dry-run`
  and `--search-state`. Verify: CLI tests incl. registration validation.
- [ ] 3.2 Docs (`docs/tools/media-catalog.md` index section +
  design-note cross-link) and CHANGELOG. Verify: review.
- [ ] 3.3 Full gates: `uv run pytest`, `ruff check .`, `ruff format`
  (changed), `ty check src`, `openspec validate`. Verify: all green.
