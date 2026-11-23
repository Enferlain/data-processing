# Proposal

## What

Bead `data-processing-7jx`: admit a `series` object kind into
`platform_references` and retain pixiv series membership as typed evidence.

- Migration `0041` widens the `object_kind` CHECK via the house table-rebuild
  pattern (0003/0038 idiom): rebuild preserving every row id, recreate the
  lookup index, engine-gated `foreign_key_check`.
- `records/common.py OBJECT_KINDS` widens with `"series"` so the records
  layer, discovery persistence, and metadata writers accept it.
- Series identity rules (evidence-only): a series reference is a stable
  provider series id (pixiv `/artworks/series/<id>`), carried like
  `source_url` external references — never a candidate target (existing
  guard triggers already reject non-account/post targets), never seed
  material, `resolved_*` stays NULL (the account/post guards are untouched).
- Recognition: `links.py` recognizes `www.pixiv.net/artworks/series/<id>`
  as a `series`/`stable_id` reference; link resolution is intentionally not
  extended (no fetch operation exists for series).
- Pixiv adapter: artwork detail's `series` key (App API field, already in
  the fixture's vocabulary) normalizes into a `series` external reference on
  the post — mirroring the danbooru `pixiv_id` bridge shape.

## Why

Series membership is a direct work-grouping signal (pixiv series are
curated multi-work collections), but it had no persistence home:
`object_kind` admitted only account/post/artist/media_asset, and t08's typed
relationship model closed without adding a series kind. cyp's pixiv series
slice and any future e621-set parity are blocked on exactly this widening.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `external-link-discovery`: new requirement admitting the series object
  kind as typed, evidence-only references with the pixiv series URL grammar.
- `pixiv-metadata-adapter`: new requirement retaining artwork series
  membership as an external series reference.

## Impact

- Code: migration `0041`, `records/common.py`, `links.py`,
  `adapters/pixiv/transport.py`, pixiv fixture (+ one series-nonnull case,
  manifest-documented per that suite's reference-corroborated precedent),
  tests.
- No change for existing kinds: guards, uniques, and index stay as they are;
  candidate/seed surfaces are untouched by design.
