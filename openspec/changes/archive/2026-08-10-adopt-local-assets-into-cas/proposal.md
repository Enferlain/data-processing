## Why

The catalog can reference files downloaded by `x-likes`, but it currently trusts legacy hashes and
paths without re-reading the bytes or taking durable ownership of them. Before adding live platform
adapters or broader downloads, the catalog needs a safe offline path for adopting those files into
verified, deduplicated, content-addressed storage while preserving their original provenance.

## What Changes

- Add an explicit offline asset-adoption operation that reads locally referenced files, verifies
  their bytes and image metadata, and copies accepted files into a user-selected managed media root.
- Store managed assets under immutable SHA-256-derived paths using unique staging files and atomic
  placement, so repeated or interrupted adoption is safe and identical bytes share one asset.
- Recalculate SHA-256 and MD5 from the source bytes, inspect byte size, MIME type and raster
  dimensions, and calculate a versioned perceptual hash for supported raster images.
- Preserve the legacy source path and media-occurrence provenance separately from the managed CAS
  path; adoption never rewrites or deletes the source database or source file.
- Record missing files, unsafe paths, unreadable content, exact-only media, metadata failures, and
  disagreements between legacy and recalculated hashes as bounded, queryable outcomes rather than
  silently accepting or discarding them.
- Add human-readable and stable JSON commands to plan, run, inspect, and verify asset adoption,
  including exact-byte deduplication and catalog/storage reconciliation.
- Keep all similarity thresholds, perceptual-match candidate generation, transformation
  classification, live downloads, network adapters, crawling, and best-quality selection out of
  this change.

## Capabilities

### New Capabilities

- `managed-asset-storage`: Offline adoption, verification, content-addressed storage, provenance,
  diagnostics, inspection, and reconciliation for existing local media files.

### Modified Capabilities

- `x-seed-import`: Preserve each imported legacy media row's local file reference at occurrence
  level so later adoption does not invent provenance when duplicate bytes came from different paths.

## Impact

- Adds a numbered catalog migration for managed asset metadata, source-file provenance, adoption
  runs and per-file outcomes while retaining existing media-occurrence and asset identifiers.
- Adds focused asset inspection/storage/adoption services and `catalog assets` CLI operations.
- Extends asset persistence to retain MIME type, dimensions, hash algorithm/version information,
  and managed-versus-external storage state without changing existing import semantics.
- Uses the existing `hashlib`, Pillow, and `imagehash` dependencies; no new runtime dependency or
  HTTP client behavior is introduced.
- Requires filesystem tests for path containment, staging cleanup, atomic placement, deduplication,
  interrupted reruns, source preservation, hash disagreement, and database/filesystem reconciliation.
