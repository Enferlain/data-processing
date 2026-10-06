# Tasks

## 1. Capability declaration and planning

- [x] 1.1 `GelbooruInstance` carries `lookup_capabilities` (source_post_url, declared_md5,
      verified_md5; page pagination) and a `lookup_plan_context` property
- [x] 1.2 `GelbooruAdapter.lookup_capabilities` reflects the instance declaration

## 2. Lookup execution

- [x] 2.1 `fetch_lookup` renders exact credentialed DAPI queries (`tags=source:<url>` /
      `tags=md5:<hash>`), digest-only request identities, pid continuation, and fails
      closed on undeclared strategies, wildcards/whitespace in source tokens, non-hex
      hashes, and missing credentials before any request
- [x] 2.2 `normalize_lookup` reuses the post parser and normalizer, produces evidence-shaped
      results (`source`, `declared_md5`, uploader, availability, provenance), and advances
      pid only on full pages
- [x] 2.3 Lookup envelopes never leak query material or credentials into identities or repr

## 3. Post normalization extensions

- [x] 3.1 Single-post DAPI requests carry `fields=tag_info`; typed tag info normalizes under
      neutral categories (`tag`→general, `metadata`→meta; undocumented types stay unknown)
      while listings keep flat unknown tags
- [x] 3.2 `title` lands in the post item; `parent_id` lands as a directional `parent_of`
      relation; malformed shapes fail closed

## 4. CLI and docs

- [x] 4.1 Lookup `--provider` choices include gelbooru (plan path stays offline/credential-free)
- [x] 4.2 Catalog guide documents gelbooru lookup usage and its evidence boundaries; the
      metadata audit records the favorites-dispute resolution and the new capability

## 5. Fixtures, tests, gates

- [x] 5.1 Fixtures cover the new request shapes (fields=tag_info) and lookup responses
- [x] 5.2 Adapter, lookup, and synchronization tests pin rendering, fail-closed behavior,
      normalization, persistence, and the pending-review boundary
- [x] 5.3 Full pytest/ruff/ty/openspec gates green; CHANGELOG entry
