## Purpose

Provide trustworthy offline adoption of existing local media into immutable, deduplicated managed
storage while preserving source provenance and making every verification outcome inspectable.

## ADDED Requirements

### Requirement: Asset adoption is explicit and offline
The system SHALL adopt local files only through an explicit command supplied with a catalog, a
source root, and a managed media root, and SHALL perform no network request while planning,
adopting, inspecting, or verifying those assets.

#### Scenario: Plan adoption with network unavailable
- **WHEN** a user plans adoption for locally referenced media while socket creation is denied
- **THEN** the command reports eligible, skipped, and invalid references using only catalog and filesystem data

#### Scenario: Catalog has remote-only media
- **WHEN** a media occurrence has a remote URL but no eligible local file reference
- **THEN** adoption leaves it metadata-only and does not attempt to download it

#### Scenario: Read-only command encounters an older catalog
- **WHEN** planning or verification opens a catalog that requires migration
- **THEN** the command refuses with backup and migration guidance without changing the catalog, schema, journal files, or managed root

### Requirement: Source paths are bounded and sources remain unchanged
The system SHALL open candidate source files through the user-supplied source root using
handle-relative no-follow containment, SHALL reject absolute paths, traversal, non-regular files,
symbolic links, component substitution, or overlapping source and managed roots, and SHALL NOT
modify, move, rename, or delete a source file or source database. If the active platform cannot
provide equivalent containment guarantees, adoption SHALL fail closed before reading a source.

#### Scenario: Valid legacy relative path
- **WHEN** a recorded local path resolves to a regular file beneath the selected source root
- **THEN** the file is eligible for read-only inspection and adoption

#### Scenario: Recorded path escapes the source root
- **WHEN** a recorded path or symbolic link resolves outside the selected source root
- **THEN** the item is rejected as an unsafe path without reading or changing the external target

#### Scenario: Path component changes during adoption
- **WHEN** a source path component is replaced or redirected after eligibility checking
- **THEN** adoption does not follow the substituted component outside the opened source-root handle

#### Scenario: Source and managed roots overlap
- **WHEN** either selected root contains the other or both identify the same directory
- **THEN** adoption refuses to start without reading, staging, or publishing an item

#### Scenario: Adoption succeeds
- **WHEN** a source file is successfully adopted
- **THEN** the original file and legacy source database remain byte-for-byte unchanged

### Requirement: Verification is derived from the source bytes
The system SHALL stream each eligible source file within configured hard byte limits to calculate
SHA-256 and MD5, byte size, and detected media type; SHALL compare available legacy exact hashes
before decoding; SHALL inspect only a bounded pixel/frame envelope and calculate a perceptual
fingerprint with recorded algorithm and version for supported raster images; and SHALL distinguish
newly calculated values from imported legacy values.

#### Scenario: Supported raster image is inspected
- **WHEN** an eligible JPEG, PNG, WebP, GIF, or AVIF file is decoded successfully
- **THEN** the adoption result records exact hashes, byte size, detected MIME type, dimensions, and the supported perceptual-fingerprint algorithm and version

#### Scenario: Non-raster or unsupported media is otherwise valid
- **WHEN** an eligible file can be streamed but does not support raster perceptual fingerprinting
- **THEN** it is successfully adopted as exact-only content with detected or generic MIME metadata while the perceptual result is explicitly unavailable rather than fabricated

#### Scenario: Imported exact hash disagrees with the bytes
- **WHEN** a recalculated SHA-256 or MD5 disagrees with the corresponding legacy value
- **THEN** the system records the mismatch before raster decoding, does not publish the staged file, does not claim it verifies the legacy asset, and does not silently replace either value

#### Scenario: File exceeds an inspection limit
- **WHEN** a source exceeds the configured byte, decoded-pixel, or frame limit
- **THEN** the item records a stable limit-exceeded outcome, performs no perceptual calculation, and publishes no managed file

### Requirement: Managed files use immutable content-addressed storage
The system SHALL derive each managed relative path solely from the verified SHA-256, traverse and
create managed-root components without following symbolic links, stage writes under the selected
managed root, and publish completed bytes atomically without overwriting a different existing file.

#### Scenario: Adopt a new verified file
- **WHEN** verified bytes are not already present in managed storage
- **THEN** the system publishes one immutable file at the deterministic SHA-256-derived path and records that managed location

#### Scenario: Identical bytes occur more than once
- **WHEN** multiple media occurrences or source paths have the same verified SHA-256
- **THEN** they reference one managed asset and one managed file while retaining their distinct occurrence and source provenance

#### Scenario: Target path already contains different or corrupt bytes
- **WHEN** the deterministic managed path exists but does not verify as the expected content
- **THEN** adoption refuses to overwrite it and records a storage-integrity failure

#### Scenario: Managed directory or target is a symbolic link
- **WHEN** a staging, hash-prefix, or target component is a symbolic link or is substituted during publication
- **THEN** adoption fails closed without reading, creating, or replacing a file through that component

### Requirement: Adoption preserves source and occurrence provenance
The system SHALL retain the source reference used for adoption, the originating media occurrence,
the adoption run and verification result, and the managed location as distinct records rather than
replacing a legacy path with a managed path.

#### Scenario: One source file supports multiple occurrences
- **WHEN** multiple catalog occurrences refer to the same adopted source bytes
- **THEN** every occurrence remains queryable and linked to the shared asset with its own provenance

#### Scenario: Legacy source later disappears
- **WHEN** a previously adopted legacy file is no longer present
- **THEN** the managed asset remains available and the missing source is reported as historical source state

### Requirement: Adoption runs are resumable and idempotent
The system SHALL record run state and a durable per-item outcome, SHALL commit completed items in
bounded transactions, and SHALL allow an interrupted or repeated run to continue without duplicate
assets, locations, provenance links, or successful outcomes. Only one adopter SHALL hold a managed
root's exclusive ownership lock, which SHALL be released automatically by the operating system on
process exit; adoption SHALL fail closed where equivalent locking is unavailable.

#### Scenario: Process stops after several files
- **WHEN** adoption is interrupted after some items have committed
- **THEN** their managed files and catalog records remain valid and a later run can process the remaining items

#### Scenario: Repeat unchanged adoption
- **WHEN** adoption is repeated with the same catalog, roots, source references, and verified bytes
- **THEN** existing successful items are reported without copying files or creating duplicate records

#### Scenario: Another adopter owns the managed root
- **WHEN** an adoption process attempts to use a managed root whose exclusive lock is already held
- **THEN** it exits without reclaiming staging files or changing catalog or managed storage state

### Requirement: Failures remain bounded and queryable
The system SHALL isolate item-level failures, record stable error categories and bounded messages,
continue with other eligible items, and return a non-success summary when any requested item failed.

#### Scenario: Source file is missing or unreadable
- **WHEN** one eligible catalog reference cannot be opened
- **THEN** that item records a missing or unreadable outcome and other items continue

#### Scenario: Image decoding fails after exact hashing
- **WHEN** a purported raster file is fully read but cannot be decoded safely
- **THEN** the item records an inspection failure and is not published as a successfully verified managed image

### Requirement: Managed storage can be inspected and reconciled
The CLI SHALL provide human-readable and stable structured output for adoption plans, runs, assets,
exact-byte duplicates, failed items, and reconciliation of catalog records with managed files while
redacting private absolute paths from default output. Planning and verification SHALL use a
genuinely read-only, no-migration catalog connection and SHALL NOT create SQLite journal files.
Verification SHALL traverse the managed root handle-relative without following symbolic links and
SHALL fail closed rather than hash or enumerate through a substituted component.

#### Scenario: Verify managed storage
- **WHEN** a user requests managed-storage verification
- **THEN** the command reports missing, corrupt, orphaned, and valid managed files plus stale staging entries without modifying or reclaiming them

#### Scenario: Managed component changes during verification
- **WHEN** a managed path component is a symbolic link or is substituted while verification runs
- **THEN** verification reports an unsafe managed path without reading or enumerating through that component

#### Scenario: Script consumes an adoption result
- **WHEN** adoption or verification is requested as structured output
- **THEN** one stable document reports roots in redacted form, algorithm versions, counts, item outcomes, and run status

### Requirement: Adoption does not infer image relationships
The system SHALL retain perceptual fingerprints for later versioned comparison but SHALL NOT assign
similarity thresholds, create perceptual match candidates, classify transformations, select a
best-quality occurrence, or infer creator or account identity during adoption.

#### Scenario: Two adopted images have similar perceptual fingerprints
- **WHEN** adopted assets happen to have nearby perceptual fingerprint values
- **THEN** both fingerprints are stored without automatically relating the assets, posts, works, or accounts
