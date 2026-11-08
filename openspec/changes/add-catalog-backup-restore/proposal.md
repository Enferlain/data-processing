# Proposal

## Why

The catalog is a single SQLite file plus content-addressed media roots, and
every workflow doc already starts with "back up the catalog" — but the tool
ships no backup primitive, no way to verify a backup, and no restore path.
Roadmap P0.5 (bead `data-processing-dbq`) asks for consistent backup/restore
with integrity verification before the catalog-mutating stage-2 work (imported
indexes, incremental refresh) begins.

## What Changes

- **`catalog backup <catalog> [--dest DIR] [--keep N]`** — online, consistent
  snapshot of the catalog via SQLite `VACUUM INTO` (safe while other
  processes, e.g. the labeling server, are writing), into a timestamped file
  plus a JSON manifest (schema version, row counts, managed-root registry with
  location counts and byte totals, and the backup file's SHA-256). Default
  destination is a sibling `<catalog-stem>-backups/` directory; `--keep N`
  prunes oldest backups beyond N after the new backup verifies.
- **`catalog restore <backup> --to PATH [--force] [--verify] [--media-root DIR]`**
  — verifies the manifest digest and schema version, then restores the
  catalog to a new path (refusing to overwrite without `--force`).
  `--verify` additionally runs `integrity_check` + `foreign_key_check` on the
  restored file; each `--media-root DIR` re-verifies the media tree against
  the restored catalog through the existing asset verifier (restore =
  re-verify fingerprints).
- **Doctor section** — `catalog doctor` reports backup state (default
  destination present, latest backup time, schema version, digest re-check)
  when the conventional backup directory exists; absence is reported
  neutrally, never as failure.
- Media bytes are deliberately not copied: roots are large, content-addressed,
  and operator-managed; the manifest records root identities and counts so a
  restored catalog can be checked against an existing tree.

No schema changes — backups and manifests are sidecar files.

## Capabilities

### New Capabilities

- `catalog-backup-restore`: consistent catalog snapshots with verifiable
  manifests, verified restore, and backup-state reporting.

### Modified Capabilities

(none — doctor output gains an additive section, no requirement changes)

## Impact

- New `src/media_catalog/backup.py` (backup/restore/doctor-section logic).
- `cli_commands/admin.py`: `backup` and `restore` commands.
- `database.doctor()` callers unchanged; the section is added in the admin
  doctor execute path.
- Tests: roundtrip, digest-tamper detection, overwrite refusal, retention
  pruning, doctor reporting, restore media verification.
- Docs + changelog.
