## Why

The metadata audit's e621 gap list: description text is retained raw but only a presence bool is
normalized — yet live pages show e621 descriptions embed the artist's original source-post text
("From source:" + full caption), i.e. retained *source content*, not decoration; file duration
(video posts) never reaches the occurrence's duration column; and `sample.alternates` (transcoded
representations with fps/codec/size) never enrich the variant metadata. All reprocess-able from
retained raw. The audit also flagged the sets grouping surface for verification.

Verified live 2026-10-07 (post 6753521): `duration` is a top-level float in seconds;
`locked_tags` a top-level list (empty here); `description` a BBCode string; `sample.alternates`
is `{"has", "original": {fps, codec, size, width, height, url}, "variants": {}, "samples": {}}`.
The sets API exists only at `/post_sets.json` (not `/sets.json`, which 404s) and returns 403
for anonymous access — set membership requires the adapter's existing authenticated transport
and a grouping model that does not conflate sets with pools (kernel Phase D, bead
`data-processing-t08`), so sets stay out of this change by design.

## What Changes

- The e621 post item emits the description content as post text (`posts.text_content`),
  keeping the presence bool; a non-string description fails closed as malformed.
- The media occurrence carries `duration_ms` converted from the provider's top-level
  seconds float; negative or non-numeric durations fail closed.
- `sample.alternates` entries with URLs land in the occurrence's variant metadata under
  `alternate:*` names with dimensions, extension/MIME, fps, and codec — additional
  provider-native representations, with existing original/sample/preview roles untouched.
- Documented non-change: `locked_tags` and `change_seq` stay raw-retained (no persistence
  home, not derivable); sets membership awaits the authenticated `/post_sets.json` surface
  and the typed work-grouping model.

## Impact

- Capabilities: `e621-metadata-adapter` (one MODIFIED requirement).
- Code: `src/media_catalog/adapters/e621/adapter.py`; fixtures under
  `tests/fixtures/metadata_adapters/e621.json`; tests in the e621 adapter and sync suites.
- No schema migration: text, duration_ms, and variants_json all exist.
