## Why

Provider-attached text — danbooru's artist commentary (the artist's own caption carried from the
source platform), gelbooru's overlay notes, and e621's positioned notes — is retained source
content and provenance that default sync never requests (Bead `data-processing-vus`, promoted
after live-page verification 2026-10-05). Enrichment must stay opt-in: it is per-post follow-up
work, not enumeration.

## What Changes

- Two opt-in operations join the closed vocabularies: `fetch_commentary` (danbooru family) and
  `fetch_notes` (gelbooru dapi, e621). Both target a single already-retained post by native id;
  neither is reachable from default sync paths.
- Migration 0017: `post_commentary_observations` (original/translated title + description, digest
  over the text facts) and `post_note_observations` (provider note id, body, position, e621
  version, digest over the note facts) — append-only, digest-deduplicated so unchanged
  re-observation is idempotent and text/version changes land as new observations. The same
  migration rebuilds the three remote-operation tables to extend the vocabulary (the 0010/0016
  idiom, verified lossless against real catalogs).
- Enrichment sync surface (`src/media_catalog/remote_sync/enrichment.py`) following the run
  contract the pool fetch established: run row commits before the fetch, every response retains
  its raw report (malformed included), provider-fault runs end `failed`, transport errors leave an
  auditable `local_persistence` run.
- CLI: `mcat metadata danbooru-commentary` / `aibooru-commentary` / `gelbooru-dapi-notes` /
  `e621-notes` `<catalog> <post-native-id>`.
- Fixtures: real captures for danbooru (post 12436862, artist caption with translation fields) and
  e621 (post 6623509, note with position and version); gelbooru fixture follows the modern
  dapi wrapper shape the repo's own parsers handle and is labeled synthetic until a credentialed
  live capture replaces it (follow-up bead).
- Spec deltas: danbooru-family, e621, and gelbooru metadata-adapter specs each gain their
  enrichment requirement.

## Capabilities

- **New Capabilities:** none.
- **Modified Capabilities:**
  - `danbooru-family-metadata-adapter` — bounded, opt-in artist-commentary collection.
  - `e621-metadata-adapter` — bounded, opt-in note collection with positions and versions.
  - `gelbooru-metadata-adapter` — bounded, opt-in dapi note collection.

## Impact

- `src/media_catalog/adapters/contracts.py` + `src/media_catalog/records/common.py` (vocabulary),
  `src/media_catalog/migrations/0017_commentary_notes.sql`, records + persistence + writer facade
  (two observation records and two writer methods), adapter request paths (danbooru, e621,
  gelbooru), `src/media_catalog/remote_sync/enrichment.py` (new), `src/media_catalog/cli.py`,
  `tests/test_commentary_and_notes.py` + fixtures, `tests/test_persistence_compatibility.py`
  digests (conscious update), `tests/test_adapter_contracts.py` operation list, `CHANGELOG.md`,
  `docs/tools/media-catalog.md`.
- No default-sync path changes: existing operations, normalizers, and enumerations are untouched.
