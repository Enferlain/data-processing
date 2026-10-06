## Why

Gelbooru is the only adapted provider with zero lookup capability (the adapter declares empty
`LookupCapabilities` and the CLI excludes it), even though its credentialed DAPI supports
`md5:`, `source:`, `id:`, and `parent:` search operators server-side (Grabber Gelbooru 0.2
site model). Requirements 1 and 2 of docs/plans/raw_requirements.md are therefore entirely
blocked for gelbooru. The audit also lists retained-raw-but-unnormalized gelbooru fields:
`parent_id` (relationships, requirement 3), `title`, and typed tag categories via the
`fields=tag_info` details parameter (`[{tag, type, count}]` with `tag`→general and
`metadata`→meta per Grabber's mapping).

Favorites dispute resolved from references: Grabber's JSON path refuses generic favorites
search, while gallery-dl successfully enumerates favorites through DAPI JSON with
`s=favorite&id=<user>` — favorites are reachable via DAPI, just not through generic tag
syntax. Recorded in the metadata audit; no favorites surface is added here.

## What Changes

- `GelbooruInstance` declares three bounded lookup strategies — `source_post_url`,
  `declared_md5`, `verified_md5` — with page (`pid`) pagination, and exposes the
  provider-neutral `lookup_plan_context` like the Danbooru-family instances. No
  `external_post_id` (gelbooru has no foreign-ID metatag or field), no artist strategies
  (DAPI exposes no artist-record endpoint).
- `GelbooruAdapter` gains `fetch_lookup`/`normalize_lookup`: exact query tokens rendered as
  DAPI `tags=source:<url>` / `tags=md5:<hash>` (hashes re-validated as 32-hex; source tokens
  reject wildcards, whitespace, and control characters), credentialed like every other DAPI
  request, digest-only request identities, pid-based page continuation bounded by the shared
  limits, and lookup results reusing the full post normalizer with the same evidence keys the
  interpreter already consumes (`source`, `declared_md5`, uploader, availability). The HTML
  transport stays lookup-free.
- Single-post DAPI fetches request `fields=tag_info`; when the response carries typed tag
  info, tags normalize under the neutral categories (`tag`→general, `metadata`→meta, other
  documented type names passthrough, anything else stays `unknown`) instead of flat
  `unknown`. Listings keep their unfiltered scope and flat tags.
- Post normalization gains `title` (into the post projection) and `parent_id` as a
  directional `parent_of` post relation, mirroring the Danbooru-family adapter; `has_children`
  stays raw (derivable from relations).
- CLI lookup commands accept `--provider gelbooru`.

## Impact

- Capabilities: `gelbooru-metadata-adapter` (one ADDED requirement, one MODIFIED).
- Code: `adapters/gelbooru/config.py`, `adapters/gelbooru/adapter.py`, `cli.py`; fixtures
  under `tests/fixtures/metadata_adapters/`; new `tests/test_gelbooru_lookup.py` plus
  extensions to the adapter and sync suites.
- No schema migration: relations, title, and tags persist through existing writer paths;
  candidate interpretation is already provider-neutral.
