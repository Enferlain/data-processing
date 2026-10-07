## Why

The metadata audit's pixiv gap list: engagement totals (`total_bookmarks`,
`total_comments`, `total_view`) are retained raw but never normalized, though the shared
persistence layer already accepts favorite and comment counts as post metadata observations —
the same catch-up the Danbooru family just landed. Requirement-relevant ordering and quality
signals follow. The audit's remaining pixiv items (series membership, related-works
enumeration, tools/AI classification) need persistence homes or new operations that this
change deliberately does not rush: `total_view` and the classification fields have no columns,
series membership has no representable object kind (`platform_references.object_kind` covers
account/post/artist/media_asset only — the same constraint that defers e621 sets), and a
related-works operation needs a new `AdapterOperation` value whose `remote_runs`/
`remote_requests` CHECK constraints require deliberate table rebuilds.

## What Changes

- The pixiv artwork detail item emits `fav_count` (from `total_bookmarks`) and `comment_count`
  (from `total_comments`); the shared page writer persists them as post metadata observations,
  reprocess-able from retained raw.
- Fixtures gain the totals (reference-corroborated from the App API field inventory) with the
  provenance recorded in the fixture manifest.
- Documented non-change: `total_view`, `tools`, `illust_ai_type`, `illust_book_style`, and
  `sanity_level` stay raw-retained; series membership and the `/v2/illust/related` surface stay
  open on bead `data-processing-cyp` pending the typed relationship model (t08) and the
  operation-vocabulary migration respectively.

## Impact

- Capabilities: `pixiv-metadata-adapter` (one MODIFIED requirement).
- Code: `src/media_catalog/adapters/pixiv/transport.py`; fixture and test updates.
- No schema migration.
