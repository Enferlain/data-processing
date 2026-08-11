## Why

The catalog can now discover remote media metadata and safely adopt existing local files, but it cannot deliberately acquire selected remote media into managed storage. Adding a bounded, auditable download path closes that gap without turning metadata synchronization into an implicit crawler.

## What Changes

- Add explicit planning and execution for downloading selected media occurrences or variants; metadata synchronization remains metadata-only.
- Persist download runs, items, attempts, continuation state, outcomes, and redacted failure evidence so interrupted work can be inspected and safely resumed.
- Apply provider-aware authorization, header, allowed-host, redirect, retry, and partial-transfer policies without persisting credentials or leaking secrets into reports.
- Stream remote bytes into bounded staging, validate resumptions, calculate exact hashes, inspect supported media, quarantine failures, and publish verified content through the existing content-addressed storage contract.
- Compare provider-declared hashes and metadata with locally verified values while preserving both claims and their provenance.
- Link successfully acquired assets to their source occurrences idempotently and expose planning, execution, retry, and inspection commands.
- Keep gallery-dl outside the canonical storage path: it may later supply extraction results or files through an optional bridge, but every acquired file must pass the same catalog-owned verification and CAS publication contract.
- Defer automatic variant selection, broad artist crawling, perceptual matching, work grouping, and similarity-based conclusions.

## Capabilities

### New Capabilities

- `remote-media-acquisition`: Explicit, bounded, resumable, provider-aware acquisition of selected remote media into verified content-addressed storage with durable operational records.

### Modified Capabilities

None.

## Impact

- Adds catalog schema and writer/query contracts for remote acquisition runs, items, attempts, resumable transfer state, and quarantine outcomes.
- Adds a download orchestration service, provider media-request policies, an HTTP transfer implementation, and CLI commands.
- Extends the existing asset staging and verification boundary to accept bounded remote streams without weakening descriptor-relative CAS safety.
- Uses the existing `httpx`, Pillow, imagehash, managed-asset-storage, media occurrence, asset, fingerprint, and occurrence-to-asset facilities.
- Introduces network activity only through explicit acquisition commands; existing import, discovery, metadata-sync, adoption, and read-only workflows retain their current behavior.
