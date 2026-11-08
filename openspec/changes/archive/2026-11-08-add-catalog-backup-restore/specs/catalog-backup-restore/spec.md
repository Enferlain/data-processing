# Spec Delta

## Purpose

Consistent, verifiable catalog backups and a checked restore path, so catalog
loss or corruption is recoverable and every mutation-heavy workflow starts
from a known-good snapshot.

## ADDED Requirements

### Requirement: backups are online, consistent, and self-describing

`catalog backup` SHALL produce a consistent snapshot of the catalog file via
SQLite `VACUUM INTO` — safe to run while other processes hold the catalog
open, including active WAL writers — into a timestamped backup file plus a
JSON manifest carrying the schema version, per-table row counts, the
managed-root registry (identity, label, managed location counts, byte
totals), and the backup file's SHA-256. The default destination SHALL be a
sibling `<catalog-stem>-backups/` directory. `--keep N` SHALL prune the
oldest complete backups beyond N only after the new backup is written and its
digest verifies; a pruned or failed backup SHALL never remove the newest
verified one.

#### Scenario: backup during active writes

- **WHEN** a second connection holds committed WAL frames open and
  `catalog backup` runs
- **THEN** the backup succeeds, opens cleanly, and reports the same schema
  version and row counts as the live catalog

#### Scenario: retention keeps the newest verified backup

- **WHEN** `--keep 1` runs twice successfully
- **THEN** only the newer backup and its manifest remain in the destination

### Requirement: restore verifies before and after

`catalog restore <backup> --to PATH` SHALL verify the manifest digest (when a
manifest exists) and the schema compatibility before writing, SHALL refuse to
overwrite an existing catalog unless `--force` is given, and SHALL leave the
source backup untouched. `--verify` SHALL run `integrity_check` and
`foreign_key_check` on the restored file. A digest mismatch or corrupted
backup SHALL fail restore with the mismatch named, before any target write.

#### Scenario: tampered backup is refused

- **WHEN** a backup file's bytes no longer match its manifest digest
- **THEN** restore fails naming the digest mismatch and writes no target file

#### Scenario: overwrite requires force

- **WHEN** the target path already holds a catalog and `--force` is absent
- **THEN** restore refuses and the existing target is unchanged

### Requirement: restore can re-verify the media tree

For each `--media-root DIR` given to restore, the restored catalog SHALL be
checked against that tree through the existing asset verification machinery:
root identity must match the catalog's registered root, and managed locations
must match their recorded content digests. Findings SHALL be reported without
mutating either the catalog or the tree.

#### Scenario: restored catalog verified against an intact media root

- **WHEN** restore runs with `--verify --media-root DIR` pointing at the tree
  the backup's catalog recorded
- **THEN** the verification reports the registered locations examined and no
  findings

### Requirement: doctor reports backup state without requiring it

`catalog doctor` SHALL include a backup section reporting, for the
conventional sibling backup directory: whether it exists, the latest backup's
timestamp, schema version, and whether its file still matches its recorded
digest. A missing backup directory SHALL be reported neutrally (never as a
doctor failure); a latest backup whose digest no longer matches SHALL be
reported as a failure with the mismatch named.

#### Scenario: fresh catalog without backups

- **WHEN** doctor runs on a catalog with no sibling backup directory
- **THEN** the backup section reports no backups and the doctor's overall
  verdict is unaffected

#### Scenario: latest backup digest drift is a failure

- **WHEN** the newest backup file is modified after it was taken
- **THEN** doctor reports the backup section as failed naming the digest
  mismatch
