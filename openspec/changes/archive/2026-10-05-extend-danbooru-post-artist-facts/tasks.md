# Tasks

## 1. Adapter emission

- [x] 1.1 Post item emits `score` (up/down/total), `fav_count`, and `flags`
      (deleted/pending/flagged/banned) using the shared writer's post-facts vocabulary
- [x] 1.2 Media occurrence variants carry per-variant `width`/`height`/`file_ext`/
      `mime_type` from `media_asset.variants`, adding provider-native intermediate sizes
      without changing existing role-to-URL sources
- [x] 1.3 Artist item emits `group_name`, `is_banned`, `created_at`, `updated_at`
- [x] 1.4 Malformed shapes for the new fields fail closed as `malformed_response` without
      discarding retained raw

## 2. Fixtures and tests

- [x] 2.1 Danbooru/aibooru fixtures gain the newly-evidenced fields with provenance noted in
      the fixture manifest
- [x] 2.2 Adapter tests pin the new emission (post facts, variant dimensions, artist fields)
- [x] 2.3 Synchronization tests prove the facts persist through the shared page writer as
      post metadata/flag observations and enriched `variants_json`, idempotently

## 3. Spec and docs

- [x] 3.1 Delta spec modifies the two danbooru-family requirements; `openspec validate
      extend-danbooru-post-artist-facts --strict` passes
- [x] 3.2 Metadata audit matrix rows move from R to normalized where now emitted; pool
      verification result recorded
- [x] 3.3 CHANGELOG entry
