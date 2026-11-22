# Proposal

## What

Bead `data-processing-9ds`: register `booru.sharkgone.com` — the operator's
personal Danbooru-software booru (~185 posts, rehosted X/Discord content
with artist tags) — as a new Danbooru-family instance, stage 3 of the
family's cross-search surface.

- `SHARKGONE = DanbooruInstance(platform_key="sharkgone", base_url
  "https://booru.sharkgone.com", schema "sharkgone-json-v1", env-only
  credentials SHARKGONE_LOGIN/SHARKGONE_API_KEY)`; the four non-artist post
  lookup strategies only (`/artists.json` returns 0 entries, so artist
  strategies are omitted), no enumeration registration, default 1.0s pacing
  floor.
- Registration at every family seam: `adapter_factory`, `crosscheck
  PROVIDERS`, discovery `LOOKUP_PROVIDERS`, lookup CLI choices and plan
  fallback, offline replay, library provider set, reprocess providers, link
  recognizer (host table + `/posts/<id>` grammar), link resolution resolvers
  and resolved-platforms, kernel `SOURCE_OPERATIONS`, replay-safe platform
  row migration `0040`, and a per-instance doctor surface.
- Captured anonymous fixtures (`sharkgone.json`: listing, md5 hit, md5
  miss) pin the contract; mirrored per-instance test file.

## Why

Niche discovery source: it holds artist-tagged rehosts whose source URLs
point at X/Discord originals — md5 cross-search there can link corpus files
to their original posts, and it is a live danbooru-shaped API the family
adapter already speaks. Anonymous access verified working; the instance is
NOT a danbooru mirror and carries no failover semantics.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `danbooru-family-metadata-adapter`: new requirement covering the
  sharkgone instance's registration, capability set, and instance-specific
  constraints (no artist strategies, no failover, env-only credentials).

## Impact

- Code: `adapters/danbooru/{config,__init__}.py`, `adapter_factory.py`,
  `crosscheck.py`, `discovery/planning.py`, `cli_commands/{lookup,support,
  library,maintenance}.py`, `links.py`, `link_resolution.py`,
  `records/common.py`, `doctor.py`, migration `0040`, fixture
  `sharkgone.json`, `tests/test_sharkgone_adapter.py`.
- No behavior change for existing instances; no data migrations beyond the
  platform row.
