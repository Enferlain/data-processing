## Why

The catalog can retain imported X seeds and managed local assets, but it cannot yet fetch the
upstream Pixiv and Danbooru metadata needed to discover artists, preserve better-quality media
occurrences, or build cross-platform matching evidence. The next useful vertical slice is a
bounded, resumable metadata-only adapter layer that preserves raw responses and never turns remote
enumeration into an implicit download or unbounded crawl.

## What Changes

- Add a provider-neutral remote metadata synchronization service with durable runs, page
  checkpoints, request identities, strict request/page/post/time budgets, typed provider failures,
  and transactional raw-plus-normalized persistence.
- Add an authenticated Pixiv metadata adapter for stable user IDs, profiles, artwork details,
  bounded user-artwork enumeration, multi-page media ordering, tags, and Ugoira metadata.
- Add a Danbooru-family metadata adapter for post and artist records, categorized tags, source
  links, uploader roles, parent/child relations, declared hashes, and keyset pagination; support
  AIBooru as a configured compatible instance with independent platform identity.
- Extend the neutral catalog model and writers to retain platform-linked raw observations,
  normalized provider tags and booru artist records, and occurrence metadata such as role, MIME
  type, and declared file size.
- Add redacted contract fixtures and disabled-by-default, tightly bounded live smoke tests.
- Keep media download, whole-account crawling, perceptual matching, automatic identity or creator
  confirmation, e621/Gelbooru adapters, and the gallery-dl subprocess bridge out of scope.

## Capabilities

### New Capabilities

- `remote-metadata-sync`: Bounded and resumable provider requests, raw-response provenance,
  credentials, checkpoints, failures, and offline fixture execution.
- `pixiv-metadata-adapter`: Normalize Pixiv user, artwork, page, tag, and Ugoira metadata while
  preserving stable IDs, ordering, availability, and raw responses.
- `danbooru-family-metadata-adapter`: Normalize Danbooru and AIBooru post, artist, uploader, tag,
  source, relation, pagination, and declared-hash metadata without conflating attribution roles.

### Modified Capabilities

- `media-catalog-core`: Retain platform-associated remote raw observations, normalized tags and
  booru artist attribution entities, and richer metadata-only media occurrence fields.

## Impact

- Adds numbered SQLite migrations, neutral adapter/run/checkpoint records, persistence services,
  provider clients, CLI commands, redacted fixtures, and contract tests under `media_catalog`.
- Extends `CatalogWriter` and catalog query output while preserving existing X import, discovery,
  asset storage, and read-only behavior.
- Uses the existing `httpx` dependency; gallery-dl remains a pinned external reference/oracle and
  is not imported or required at runtime.
- Live Pixiv access requires an externally supplied refresh token; Danbooru-family credentials are
  optional unless an instance or requested record requires them. Secrets are never stored in the
  catalog, command arguments, raw request identities, diagnostics, or structured output.
