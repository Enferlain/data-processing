## Why

The hosted-source metadata audit (docs/plans/metadata-audit.md, Bead `data-processing-a3t`)
found the danbooru/aibooru adapter retains but never normalizes provider fields the
persistence layer already supports: post score/up/down/favorite counts and status flags
(`PostMetadataObservation`/`PostFlagObservation`), media-asset variant dimensions
(`variants_json`), and artist `group_name`/`is_banned`/created/updated (`AttributionRecord`).
Every gap is reprocess-able from retained raw, and the fields unlock requirement-3 adjacent
ordering and work-grouping metadata named in docs/plans/raw_requirements.md. The audit also
flagged per-post pool ids for verification: live danbooru post payloads (retained raw,
2026-10-05) carry no pool ids, so pool observations cannot come from post sync — pool
grouping needs the `/pools/{id}.json` collection surface, which stays out of scope here.

`tag_count_*` and `has_children`/`has_active_children`/`has_visible_children` stay
raw-retained deliberately: both are derivable from already-normalized data (post-tag
observations per category; parent/child relations), so emitting them would add no information.

## What Changes

- The danbooru-family post item emits engagement facts the shared page writer already
  persists: `score` (up/down/total from `up_score`/`down_score`/`score`), `fav_count`, and a
  `flags` mapping (`deleted`/`pending`/`flagged`/`banned` from `is_deleted`/`is_pending`/
  `is_flagged`/`is_banned`) landing as post metadata observations plus individual flag
  observations.
- The media occurrence's variant list gains per-variant dimensions: `width`/`height`/
  `file_ext`/`mime_type` from `media_asset.variants`, including the intermediate
  provider-native sizes (180x180, 360x360, 720x720) alongside original/sample/preview.
  Existing role-to-URL mappings keep their current sources; only dimensions and additional
  provider-native roles are added, so acquisition variant resolution is unchanged.
- The artist item emits `group_name`, `is_banned`, `created_at`, and `updated_at`, which the
  attribution writer already maps onto `AttributionRecord`.
- Fixtures gain the newly-evidenced fields (marked reference-corroborated in the fixture
  manifest where not directly observed), and adapter/sync tests pin the new emission and its
  persistence, including idempotent re-observation.
- Documented non-change: no pool emission from post payloads (verified absent); no
  tag-count or children emission (derivable); no new fetch operations.

## Impact

- Capabilities: `danbooru-family-metadata-adapter` (two requirements extended).
- Code: `src/media_catalog/adapters/danbooru/adapter.py`; fixtures under
  `tests/fixtures/metadata_adapters/`; tests in `tests/test_danbooru_adapter.py` and
  `tests/test_metadata_sync.py`.
- No schema migration: every new fact lands in existing columns through existing writer
  paths. Already-retained observations pick the facts up on the next re-observation (raw is
  retained; a dedicated reprocess path does not exist yet).
