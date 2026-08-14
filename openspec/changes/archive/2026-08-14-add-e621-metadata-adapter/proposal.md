## Why

The catalog recognizes e621 references but cannot yet retrieve, normalize, search, enumerate, or
acquire e621 records through its first-class bounded workflows. e621 has a documented JSON API and
stable post, tag, alias, and artist contracts, making it the best next provider to extend the
review-to-library pipeline without depending on Gelbooru's unresolved credentialed schema.

## What Changes

- Add a native e621 metadata adapter for post detail, artist/tag attribution metadata, and bounded
  artist-tag post enumeration using documented ID-keyset pagination.
- Normalize e621's nested original, sample, preview, tag-category, source, relationship, rating,
  score, uploader, timestamp, and availability fields without conflating artist attribution with
  uploader accounts.
- Enforce e621's descriptive User-Agent, conservative request pacing, optional externally supplied
  Basic authentication, page-size ceiling, typed failures, and secret-free request identities.
- Extend bounded candidate lookup with source URL, embedded post ID, declared/verified MD5, exact
  artist name, and approved alias strategies backed by retained e621 observations.
- Extend artist-library expansion to stable e621 attribution targets while keeping arbitrary
  filtered counts unknown and using an exact tag count only when retained tag metadata proves it.
- Add an e621-specific media request policy so explicitly selected returned original, sample, and
  preview occurrences can use the existing verified acquisition and managed-storage pipeline.
- Add redacted contract fixtures and bounded injected-transport tests for normal, deleted,
  unavailable-media, malformed, authentication, rate-limit, pagination, resume, lookup, expansion,
  and acquisition behavior.
- Keep Gelbooru, favorites, pools/notes fan-out, bulk database exports, recursive discovery,
  similarity matching, automatic identity/authorship decisions, implicit detail hydration, and
  implicit downloads out of scope.

## Capabilities

### New Capabilities

- `e621-metadata-adapter`: Fetch and normalize e621 post and attribution metadata under the
  provider's documented API, pagination, request-policy, availability, and privacy contracts.

### Modified Capabilities

- `remote-metadata-sync`: Apply e621-specific User-Agent, authentication, rate, keyset-pagination,
  typed failure, raw-retention, and resume behavior through the shared synchronization contract.
- `bounded-candidate-lookup`: Add bounded e621 lookup strategies and attribution results without
  turning names, aliases, tags, uploaders, or hashes into automatic identity or authorship.
- `artist-library-expansion`: Allow explicit or confirmed stable e621 attribution targets to
  enumerate posts and use only retained exact-tag counts as estimates.
- `remote-media-acquisition`: Permit explicit acquisition of returned e621 media variants under a
  versioned e621 host, redirect, response, and credential policy.
- `media-catalog-core`: Retain e621 tag categories, aliases, attribution metadata, nested media
  facts, availability flags, and post relationships without changing existing provider records.

## Impact

- Adds an e621 adapter/configuration package, fixtures, CLI provider routes, and provider-specific
  acquisition policy under `media_catalog`.
- Extends existing neutral adapter, lookup, library-expansion, media-occurrence, record, writer, and
  query contracts; a numbered additive migration is required only for facts not representable by
  the current schema after a verified schema audit.
- Uses the existing `httpx`, remote synchronization, raw observation, checkpoint, review,
  acquisition, and CAS infrastructure. gallery-dl and tag-workspace remain read-only references and
  are not runtime dependencies.
- Default tests remain offline. Live e621 smoke tests are disabled by default, identify the client
  with a descriptive User-Agent, and use strict request/time limits without fetching media bytes.
