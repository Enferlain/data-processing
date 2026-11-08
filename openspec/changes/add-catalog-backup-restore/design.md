# Design

## Context

Catalog = one SQLite file (WAL-capable) + content-addressed managed roots.
Every asset row carries `verified_sha256`; `asset_locations` records
`(managed_root_id, relative_path, recorded_sha256, byte_size)`;
`AssetStorageVerifier` already re-verifies a tree against a catalog without
mutating either. `CatalogDatabase.doctor()` reports `integrity_check` +
`foreign_key_check`. No backup code exists (bead `data-processing-dbq`).

## Goals / Non-Goals

Goals: online consistent snapshots, self-verifying manifests, checked restore,
media-tree re-verification on restore, doctor visibility, retention pruning.

Non-Goals: copying media bytes (roots are large, content-addressed, and
operator-managed — the manifest records enough to check a tree); scheduled
runs (operator/cron); remote destinations; encrypted backups; catalog
migration during restore (restore is same-version by design).

## Decisions

### D1 — VACUUM INTO, not file copy or the backup API

`VACUUM INTO ?` produces a defragmented, transactionally consistent snapshot
on one connection while other connections (labeling server) keep writing —
exactly the property that made path-based read-only opens fail (bead 818).
The python `sqlite3.backup()` API needs a stable second connection; VACUUM
INTO is one statement and includes committed WAL frames. The command commits
any open transaction first (VACUUM cannot run inside one).

### D2 — Manifest as the trust anchor

`<name>.manifest.json` beside `<name>.sqlite3` records: created_at, source
catalog path basename, schema version, page_size, per-table row counts,
managed roots (id, identity, label, managed location count, byte total), and
`sha256` + `byte_size` of the backup file, computed after the write closes.
Restore and doctor trust the recorded digest; both re-hash the file. Row
counts give a human-checkable "what was in it" without opening the file.

### D3 — Restore is verify-first, never in place

Order: read manifest (if present) → verify digest → open read-only to check
schema version and `integrity_check` → refuse existing target unless
`--force` → copy (temp file + `os.replace` for atomicity) → optional
post-restore `--verify` checks + `--media-root` verifier runs. Any pre-target
failure leaves no target file. The backup file itself is never opened for
writing.

### D4 — Conventional destination, opt-in retention

Default dest `<catalog parent>/<stem>-backups/` keeps doctor discoverable
with zero configuration. `--keep N` prunes oldest *complete* pairs (file +
manifest) beyond N only after the new backup's digest verifies; the newest
verified pair is never pruned by retention. Pruning removes only files
matching our own timestamped naming pattern in that directory.

### D5 — Doctor: neutral absence, failing drift

Doctor adds a `backup` section by probing the conventional directory:
missing → `{"backups": "none"}` and no effect on `ok`; present → latest
pair's timestamp/version/digest re-check. Digest drift fails the section
(and the doctor's `ok`) because the operator's recovery path is silently
broken — the one thing this feature exists to prevent.

## Risks / Trade-offs

- [VACUUM INTO reads the whole DB; large catalogs take time and equal free
  disk] → Documented; it is online and bounded by catalog size; media never
  touches the copy.
- [Media verify on restore defaults to full scan under the verifier's
  existing bounds (128 MiB / 100k entries)] → Bounds are the same as the
  existing verify surface; spot-checking is deliberately not invented here.
- [Manifest digest covers the sqlite file only, not media] → By design: the
  media check is the verifier, run explicitly via `--media-root`.
- [Two writers racing `--keep` pruning] → Local-first tool; pruning only
  removes files matching our naming pattern and never the newest verified
  pair.

## Migration Plan

None — sidecar files only, no schema change. Rollback is deleting the backup
directory.

## Open Questions

None blocking. Remote/encrypted destinations can layer on the manifest
format later without changing it.
