## Context

See `proposal.md` for motivation. The foundation schema already separates media occurrences from
assets and deduplicates asset rows by verified SHA-256. The `x-likes` importer can preserve legacy
SHA-256, MD5, pHash, file size, and path values, but it intentionally reads its source database only
and does not verify or copy the referenced bytes. Assets therefore need a managed-storage layer
without changing import behavior or treating a path recorded by another database as trusted input.

SQLite and a filesystem cannot share one atomic transaction. The design must tolerate a process
stopping after a file is published but before its catalog transaction commits, or after a catalog
item commits while later items remain unfinished. Private source roots and legacy filenames also
must not leak through normal structured or human output.

## Goals / Non-Goals

**Goals:**

- Make adoption read-only with respect to legacy sources and deterministic with respect to verified bytes.
- Give the catalog an explicit, relocatable managed media root and immutable SHA-256-addressed files.
- Preserve enough run, item, source, hash, and algorithm provenance to audit or repeat verification.
- Make interruption, duplicate bytes, corrupt targets, missing sources, and partial failure safe.
- Leave storage interfaces suitable for a later bounded downloader without implementing networking now.

**Non-Goals:**

- Fetching URLs, following redirects, refreshing signed URLs, credentials, or provider policies.
- Perceptual thresholds, crop-resistant comparison, alternate similarity metrics, work grouping,
  transformation labels, or quality ranking.
- Moving or deleting legacy files, rewriting the `x-likes` database, or automatically repairing failures.
- Video frame extraction, Ugoira conversion, or transcoding any source bytes.

## Decisions

### 1. Adoption takes explicit source and managed roots

The CLI accepts a catalog path, `--source-root`, and `--media-root`. Stored legacy paths are treated
as relative candidate paths beneath an opened source-root handle. On POSIX, walk every component
relative to directory file descriptors with no-follow/directory flags, open the final component
with no-follow semantics, and validate the opened descriptor as a regular file. Other platforms
must provide equivalent handle-relative containment or fail closed. A pathname `resolve()` check is
not a security boundary. Absolute paths, `..`, symlinks, substituted components, and non-regular
files are rejected. The two roots must be disjoint after handle-based identity checks. The managed
root contains `sha256/`, `staging/`, and a reserved `quarantine/` directory.

An explicit media root is preferable to a hidden database-side default because catalogs and large
media collections may live on different volumes. Persist a stable root identity and store managed
locations relative to it; default CLI output shows a public/redacted root label rather than the
private absolute path.

Alternative considered: infer both roots from the catalog and legacy database locations. This is
convenient but makes destructive path mistakes and accidental storage growth harder to notice.

### 2. Copy sources; never move them

Adoption opens source files read-only and creates a managed copy. Successful verification does not
remove the source or rewrite its path. A future explicitly destructive cleanup operation can be
specified separately after managed storage has been used and backed up in practice.

Alternative considered: offer `--move` immediately. It saves disk space but combines verification
with deletion risk and weakens rollback, so it is excluded.

### 3. SHA-256 addresses immutable bytes

Managed files use `sha256/<first-two>/<next-two>/<full-hash>` with no extension. MIME type remains
catalog metadata and can be reclassified without changing physical identity. SHA-256 is the
identity key; MD5 is retained for booru interoperability but never selects a managed path. Files
are never transformed before storage.

A unique staging file is created relative to an opened `staging` directory handle, streamed and
hashed, flushed, and then published without overwriting an existing target. Managed directory
components are opened or created handle-relative without following symlinks; targets must be
regular non-symlink files. If the target already exists, its size and SHA-256 are verified through
the opened handle before it is reused. A mismatching target is an integrity failure and remains
untouched. Implementations without equivalent no-follow publication primitives fail closed.

Alternative considered: preserve human-oriented account/post filenames. Those names are mutable,
can expose private metadata, and prevent byte-level deduplication.

### 4. Filesystem publication precedes the item database commit

Each item follows: securely open the source, stream to staging while hashing within a hard byte
limit, compare available legacy SHA-256/MD5 values, inspect the complete staged bytes within pixel
and frame limits, publish or reuse the final CAS path, then commit the
asset/location/provenance/outcome records in one short SQLite transaction. A cryptographic mismatch
or resource-limit failure is determined before perceptual hashing and prevents publication. If
publication succeeds but the transaction fails, reconciliation sees an orphaned CAS file; if the
process stops earlier, its uniquely named staging file remains visible for verification. Controlled
failure cleanup is best-effort and must never unlink a pathname after a non-atomic inode check:
POSIX has no conditional unlink-by-inode primitive, so the implementation deliberately retains a
verified staging hard-link when safe automatic removal cannot be proven. Successful publication
therefore may also leave staging residue, which verification reports for later explicit
reconciliation. When this run created the CAS target, that residue shares the target inode and adds
only a directory entry. When the target already existed, or failure occurred before publication,
the residue can retain a complete staged copy and requires corresponding disk headroom. This is a
deliberate fail-closed space trade-off. No later run automatically deletes residue. The service never
assumes a cross-filesystem/database transaction exists.

Alternative considered: commit the database before publishing. That creates catalog records which
claim availability while the managed file is absent, a worse normal failure mode.

### 5. Existing asset IDs and legacy assertions remain intact

Add normalized location, occurrence-source, fingerprint, adoption-run, and adoption-item records
rather than replacing the current asset and occurrence tables. A managed location attaches to the
asset whose SHA-256 was verified from the bytes. Exact and perceptual fingerprint records include
algorithm, version, source, calculation time, and verification status; fixed legacy columns remain
readable for compatibility during this change.

Existing catalogs have only one asset-level `storage_path`, so migration cannot reconstruct which
occurrence supplied that path or recover distinct paths already collapsed under one SHA-256. Backfill
it only as an explicitly ambiguous asset-level legacy assertion and never fan it out as invented
occurrence provenance. Report ambiguous and unassociated counts. Extend subsequent `x-likes`
imports so every media row with a local path persists an occurrence-source reference even when its
SHA-256 is absent; duplicate SHA-256 rows may then keep different paths while sharing an asset.

When a recalculated legacy SHA-256 or MD5 disagrees, the item is recorded as `hash_mismatch`, no
managed location is attached to the claimed legacy asset, and neither value is overwritten. The
source bytes are retained untouched. Accepting changed bytes as a different asset requires a later
explicit user action rather than an adoption flag that could conceal corruption.

Alternative considered: update the existing asset row to the new hash. That would rewrite the
identity of an object already referenced by occurrences and erase evidence of the disagreement.

### 6. Raster inspection is versioned but matching is deferred

SHA-256 and MD5 are streamed with the copy under a configurable hard-byte ceiling with a conservative
default. After legacy exact hashes agree, image inspection enforces configurable decoded-pixel and
frame limits and records detected MIME type, dimensions, and the currently supported imagehash
pHash algorithm and version. GIF inspects only its bounded primary frame; decompression-bomb and
limit failures receive stable outcomes. Content that is not a supported raster format is adopted
successfully as exact-only bytes with detected or `application/octet-stream` MIME metadata. Existing
legacy pHash remains distinct from the newly calculated fingerprint.

No distance threshold, candidate index, or relation is part of adoption. Later research can compare
pHash with other metrics, including approaches used by duplicate-finder tools, without migrating
unversioned values or changing CAS identity.

### 7. Runs provide durable progress and stable outcomes

An adoption run records catalog/root identities, algorithm versions, limits, start/end time, status,
and counts. Each selected occurrence/source pair has a deterministic key and one current outcome
such as `adopted`, `adopted_exact_only`, `existing`, `missing`, `unsafe_path`, `unreadable`,
`source_changed`, `limit_exceeded`, `hash_mismatch`, `inspection_failed`, or
`storage_integrity_failed`. Repeated runs may append attempts for audit, but successful assets,
locations, and occurrence links remain unique.

Planning performs path eligibility and count discovery without reading full file contents or
writing catalog/storage state. It opens the catalog using a genuinely read-only, no-migration
connection; if the schema is not current, it refuses with backup/migration guidance. Execution
acquires an operating-system advisory lock on a fixed lock file opened relative to the managed-root
handle and holds it for the complete run. The lock is released automatically on process exit;
platforms without an equivalent exclusive lock fail closed. A second adopter never reclaims the
owner's staging file. Execution commits per item so one bad file does not roll back prior successes.
Any failed requested item makes the run summary partial/failed while still reporting all successful
work.

### 8. Verification is read-only; repair is separate

`catalog assets verify` opens the catalog through one no-follow descriptor, checks that the main
file is stable and that no active WAL frames or pending rollback journal exist before and after a
bounded read, and deserializes that snapshot into a query-only in-memory SQLite connection. It
performs no migration, search initialization, URI/path SQLite open, or journal-sidecar creation;
active transaction sidecars and catalogs over the configured snapshot bound are refused with
guidance. It refuses an older schema unchanged. It
checks catalog-managed paths, exact hashes, and location links using the same handle-relative
no-follow managed-root traversal as adoption. Symlinked or substituted components are reported as
unsafe and are never followed while hashing or enumerating orphans. Verification changes neither
database nor filesystem, and reports missing and corrupt managed files plus orphaned CAS files and
stale staging entries. This change does not automatically delete, relink, reclaim, quarantine, or
repair them. A future repair command can build on the verified report with an explicit mutation
contract.

## Risks / Trade-offs

- [Adoption temporarily doubles disk use] → Copy by design, show planned file/byte totals, allow
  bounded selection, and leave cleanup to a later explicit operation.
- [Source changes while being read] → Compare pre/post stat data, hash the streamed bytes, and fail
  the item if descriptor metadata changes; handle-relative no-follow traversal prevents path
  substitution from escaping either root.
- [Filesystem publication and SQLite commit diverge] → Deterministic paths, per-item commits, and
  read-only reconciliation make either orphaned side detectable and rerunnable.
- [MIME detection or decoder bugs reject valid files] → Preserve bounded diagnostics and exact
  hashes in the item attempt, enforce byte/pixel/frame limits, do not publish a failed raster, and
  allow later algorithm-version reruns; exact-only non-raster content remains adoptable.
- [Legacy hashes were calculated with different tools] → Cryptographic values must still match
  exact bytes; perceptual values remain versioned observations and are not treated as mismatches.
- [Path disclosure through diagnostics] → Store required provenance privately but redact absolute
  roots and expose bounded basenames/relative public paths by default.
- [CAS files are edited externally] → Treat managed bytes as immutable and make verification report
  corruption; never overwrite a conflicting target during adoption.

## Migration Plan

1. Add the new tables, constraints, indexes, and additive asset metadata needed for locations,
   occurrence sources, fingerprints, adoption runs, and item outcomes; backfill current storage
   paths only as ambiguous asset-level legacy assertions without reading files, inventing
   occurrence provenance, or changing asset IDs.
2. Add records and writer/query contracts and extend later `x-likes` imports to retain every
   occurrence-level local path, including paths whose source row has no SHA-256.
3. Add inspection, CAS storage, adoption planning/execution, and verification services behind new
   commands.
4. Exercise adoption against a disposable catalog and copied synthetic source tree before using a
   user-selected catalog backup.

Database rollback uses the pre-migration catalog backup. Files already published in the managed
root remain valid immutable bytes and can be identified as orphans; rollback does not delete them.
Read-only plan/verify commands never perform this migration; a user must first run an acknowledged
mutating catalog operation after taking the backup.
