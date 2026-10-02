## Why

The catalog already recognizes Gelbooru references and the real cross-platform test set depends on
five Gelbooru posts, but it cannot yet retain their provider metadata. Gelbooru now requires API
credentials for DAPI while its public HTML post pages remain accessible, so a first-class adapter
needs two explicit, independently versioned transports rather than an undocumented silent fallback.

## What Changes

- Add a native, metadata-only Gelbooru adapter with an explicit credentialed JSON-DAPI transport
  and an explicit anonymous HTML single-post transport.
- Capture small redacted fixtures for the five real acceptance posts plus unavailable,
  authentication, malformed, and tag-response cases before treating undocumented wire fields or
  numeric tag categories as stable contracts.
- Resolve Gelbooru API key and user ID from external environment references, inject them only at
  request time, and exclude credential-bearing URLs and values from durable identities, raw data,
  diagnostics, and normal output.
- Reuse the bounded remote-sync, raw-observation, normalized persistence, media browsing, and
  checkpoint contracts while retaining the selected transport and parser version as provenance.
- Normalize only fixture-proven post, source, uploader, rating, MD5, dimensions, tag, and returned
  media-variant facts; retain unknown native fields in raw observations and never derive media URLs.
- Add explicit CLI commands, offline fixture coverage, provider compatibility tests, documentation,
  and disabled-by-default live metadata checks.
- Keep candidate lookup, artist-library expansion, counts, aliases, pools, favorites, deleted-post
  streams, media acquisition, broad crawling, cross-database aliasing, similarity, and automatic
  identity/authorship/variation decisions out of this initial change.

## Capabilities

### New Capabilities

- `gelbooru-metadata-adapter`: Explicit credentialed-DAPI and anonymous single-post HTML metadata
  transports, normalization, policy, privacy, fixtures, and typed failures for Gelbooru.

### Modified Capabilities

- `remote-metadata-sync`: Admit an explicitly selected Gelbooru transport while preserving generic
  budgets, response-first raw retention, transactions, privacy, and compatible resume behavior.
- `media-catalog-core`: Preserve fixture-proven Gelbooru post, tag, uploader, source, and media facts
  through neutral records plus transport-versioned raw provenance without provider-specific tables.

## Impact

- Adds a dedicated Gelbooru adapter/configuration package, redacted fixtures, CLI routing, and
  provider tests.
- Reuses the current remote executor, writer, query, browser, and platform/reference identities;
  schema changes are permitted only for a demonstrated neutral persistence gap or platform metadata.
- Requires private external Gelbooru credentials for DAPI testing and an explicit personal-use or
  operator-authorization decision before enabling live automated API use; credentials are never
  committed or accepted as literal CLI arguments.
- Does not add runtime gallery-dl or Grabber dependencies. Their behavior is only a compatibility
  reference for fixture interpretation and HTML/DAPI edge cases.
