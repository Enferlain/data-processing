## 1. Persistence and contracts

- [x] 1.1 Add a numbered migration for managed roots and locations, versioned asset fingerprints,
  adoption runs, per-item attempts/outcomes, provenance links, constraints, and query indexes while
  preserving existing asset and occurrence IDs.
- [x] 1.2 Backfill each existing asset storage path only as an ambiguous asset-level legacy
  assertion, without reading files, inventing occurrence provenance, changing imported hash values,
  or marking it as a managed CAS copy; report ambiguous and unassociated counts.
- [x] 1.3 Add validated records and writer/query contracts for storage kinds, root identities,
  occurrence-source references, fingerprints, run states, item outcomes, detected media metadata,
  limits, and bounded diagnostics; extend subsequent `x-likes` imports to retain every occurrence's
  local path even without a SHA-256.
- [x] 1.4 Add fresh-schema, v3-upgrade, rollback, constraint, foreign-key, and backfill tests proving
  existing imports, discovery records, assets, and occurrence links remain unchanged.

## 2. Safe file inspection and CAS primitives

- [x] 2.1 Implement handle-relative, no-follow traversal for both explicit roots with fail-closed
  platform capability checks, disjoint-root enforcement, opened-descriptor validation, source
  stability checks, and rejection of absolute paths, traversal, symlinks, substituted components,
  and non-regular files.
- [x] 2.2 Implement hard byte/pixel/frame limits, streaming SHA-256/MD5 and size calculation,
  legacy exact-hash comparison before decoding, and versioned MIME/dimension/raster-pHash inspection;
  retain valid non-raster content as exact-only assets.
- [x] 2.3 Implement SHA-256-only CAS paths, handle-relative non-symlink directory creation, unique
  in-root staging, durable flush, atomic no-overwrite publication, existing-target descriptor
  verification, and best-effort cleanup limited to the current run's controlled failures.
- [x] 2.4 Add synthetic file tests for supported raster formats, exact-only unsupported media,
  malformed/over-limit images, changing sources, component-swap races, overlapping roots,
  destination symlinks, duplicate bytes, corrupt target collisions, MIME reclassification, and
  algorithm provenance.

## 3. Adoption planning and execution

- [x] 3.1 Implement a read-only adoption planner that selects eligible legacy source references,
  reports planned counts and bytes when known, applies bounded filters, uses a no-migration
  read-only SQLite connection, refuses older schemas with backup/migration guidance, and creates no
  catalog, journal, or filesystem state.
- [x] 3.2 Implement per-item adoption orchestration in short transactions: validate, stage/hash,
  compare legacy exact hashes, inspect, publish or reuse, then persist managed location,
  fingerprints, occurrence provenance, and outcome.
- [x] 3.3 Persist resumable run lifecycle and deterministic item identities so interruption and
  repeated execution preserve completed work without duplicate assets, files, locations, links, or
  success records; hold an OS-released exclusive managed-root lock for the run, fail closed without
  equivalent locking, and never reclaim another or crashed run's staging files automatically.
- [x] 3.4 Implement isolated outcomes for missing, unsafe, unreadable, changed, over-limit,
  hash-mismatched, inspection-failed, storage-integrity-failed, and successfully adopted exact-only
  items while continuing other requested work and leaving every source untouched.
- [x] 3.5 Add offline, idempotency, interruption, partial-failure, legacy-hash disagreement,
  simultaneous-adopter locking, crash/staging residue, multi-occurrence deduplication,
  duplicate-SHA/different-path provenance, missing-source-after-adoption, source immutability, and
  orphan-file reconciliation tests.

## 4. Inspection and command interface

- [x] 4.1 Add `catalog assets plan`, `adopt`, `list`, and `show` commands with explicit source/media
  roots, bounded selection, stable exit codes, path redaction, and human/JSON result contracts.
- [x] 4.2 Add a read-only `catalog assets verify` command that reports valid, missing, corrupt, and
  orphaned managed files plus stale staging entries without repairing or deleting anything, opens
  SQLite without migration/WAL/journal creation, refuses older schemas unchanged, and uses
  handle-relative no-follow traversal with symlink/component-substitution tests.
- [x] 4.3 Add exact-byte duplicate, run-history, and failed-item queries while keeping perceptual
  fingerprints visible only as versioned metadata and creating no similarity or identity candidate.
- [x] 4.4 Add CLI golden/contract tests, denial-of-all-sockets tests, private-path redaction tests,
  and documentation covering backups, disk-space planning, reruns, verification, and recovery.

## 5. Integration verification

- [x] 5.1 Verify upgraded and subsequent `x-likes` imports distinguish ambiguous legacy asset paths
  from occurrence-level paths, preserve duplicate-SHA rows with different paths and paths lacking
  SHA-256, and adopt copied local files into a disposable media root while the source database/tree
  remains byte-for-byte unchanged.
- [x] 5.2 Run formatting, lint, the full Python 3.13 suite, package build/install CLI smoke tests,
  strict OpenSpec validation, database integrity checks, and `git diff --check`.
- [x] 5.3 Obtain an implementation review focused on filesystem safety, interruption windows,
  migration compatibility, path privacy, idempotency, and the explicit boundary before downloads
  and similarity matching; address actionable findings and rerun affected gates.
