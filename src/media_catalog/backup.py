"""Catalog backup and restore with integrity verification (bead dbq).

Backups are online, consistent SQLite snapshots (``VACUUM INTO``) paired
with a self-describing manifest whose recorded digest is the trust anchor
for restore and doctor.  Media bytes are never copied: managed roots are
content-addressed and operator-managed, and the manifest records enough of
their catalog state for the existing asset verifier to check a tree against
a restored catalog.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time as _time
from dataclasses import dataclass
from datetime import UTC, datetime
from os import replace as os_replace
from pathlib import Path
from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.output import public_path

MANIFEST_SUFFIX = ".manifest.json"
_BACKUP_NAME_PATTERN = re.compile(r"^\d{8}T\d{6}Z$")

_BACKUP_TABLES = (
    "platforms",
    "accounts",
    "account_snapshots",
    "posts",
    "media_occurrences",
    "assets",
    "asset_locations",
    "managed_roots",
    "discovery_sessions",
    "discovery_search_attempts",
    "relationships",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_backup_dir(catalog: Path) -> Path:
    """Conventional sibling destination: <catalog-stem>-backups/."""
    return catalog.parent / f"{catalog.stem}-backups"


def _manifest_path(backup_file: Path) -> Path:
    return backup_file.with_name(backup_file.name + MANIFEST_SUFFIX)


def _backup_pairs(destination: Path) -> list[tuple[Path, Path | None]]:
    """Complete-or-file-only backups in the destination, oldest first.

    Only files matching our own timestamped naming are considered; anything
    else in the directory is left strictly alone.
    """
    pairs: list[tuple[Path, Path | None]] = []
    if not destination.is_dir():
        return pairs
    for entry in sorted(destination.iterdir()):
        if entry.suffix != ".sqlite3" or not _BACKUP_NAME_PATTERN.fullmatch(entry.stem):
            continue
        manifest = _manifest_path(entry)
        pairs.append((entry, manifest if manifest.is_file() else None))
    return pairs


@dataclass(frozen=True, slots=True)
class BackupResult:
    backup_path: Path
    manifest_path: Path
    sha256: str
    byte_size: int
    schema_version: int
    row_counts: dict[str, int]
    pruned: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "backup": public_path(self.backup_path),
            "manifest": public_path(self.manifest_path),
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "schema_version": self.schema_version,
            "row_counts": self.row_counts,
            "pruned": self.pruned,
        }


def _row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in _BACKUP_TABLES:
        row = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if row[0]:
            counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    return counts


def _managed_roots(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT r.managed_root_id, r.root_identity, r.display_label,
                  COUNT(l.asset_location_id) AS location_count,
                  COALESCE(SUM(l.byte_size), 0) AS byte_total
             FROM managed_roots r
             LEFT JOIN asset_locations l
               ON l.managed_root_id = r.managed_root_id
              AND l.location_kind = 'managed'
            WHERE r.root_kind = 'managed'
            GROUP BY r.managed_root_id
            ORDER BY r.managed_root_id"""
    ).fetchall()
    return [
        {
            "managed_root_id": int(row["managed_root_id"]),
            "root_identity": row["root_identity"],
            "display_label": row["display_label"],
            "managed_locations": int(row["location_count"]),
            "managed_bytes": int(row["byte_total"]),
        }
        for row in rows
    ]


def backup_catalog(
    catalog: Path,
    *,
    destination: Path | None = None,
    keep: int | None = None,
) -> BackupResult:
    """Snapshot the catalog online into a timestamped backup + manifest."""
    catalog = Path(catalog)
    if not catalog.is_file():
        raise ValueError("catalog file does not exist")
    destination = Path(destination) if destination is not None else default_backup_dir(catalog)
    if keep is not None and keep < 1:
        raise ValueError("--keep must be at least 1")
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = _now().strftime("%Y%m%dT%H%M%SZ")
    backup_path = destination / f"{timestamp}.sqlite3"
    if backup_path.exists():
        # Two backups in one second: wait briefly for the next slot rather
        # than failing the operator's command.
        deadline = _time.monotonic() + 1.05
        while backup_path.exists() and _time.monotonic() < deadline:
            _time.sleep(0.05)
            timestamp = _now().strftime("%Y%m%dT%H%M%SZ")
            backup_path = destination / f"{timestamp}.sqlite3"
        if backup_path.exists():
            raise ValueError(f"backup for this second already exists: {public_path(backup_path)}")

    with CatalogDatabase(catalog) as database:
        schema_version = database.schema_version
        row_counts = _row_counts(database.connection)
        managed_roots = _managed_roots(database.connection)
        # VACUUM cannot run inside a transaction; commit anything pending on
        # this connection first.  Other processes may keep writing: VACUUM
        # INTO snapshots the committed state consistently.
        database.connection.commit()
        database.connection.execute("VACUUM INTO ?", (str(backup_path),))

    sha256 = _sha256_file(backup_path)
    manifest = {
        "format": "catalog-backup-v1",
        "created_at": f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}T"
        f"{timestamp[9:11]}:{timestamp[11:13]}:{timestamp[13:15]}Z",
        "catalog": catalog.name,
        "schema_version": schema_version,
        "row_counts": row_counts,
        "managed_roots": managed_roots,
        "byte_size": backup_path.stat().st_size,
        "sha256": sha256,
    }
    manifest_path = _manifest_path(backup_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    pruned: list[str] = []
    if keep is not None:
        pairs = _backup_pairs(destination)
        # Never prune the newest verified pair; prune oldest beyond --keep.
        for backup_file, file_manifest in pairs[:-keep] if keep else []:
            if file_manifest is not None:
                backup_file.unlink()
                _manifest_path(backup_file).unlink()
                pruned.append(public_path(backup_file))
    return BackupResult(
        backup_path=backup_path,
        manifest_path=manifest_path,
        sha256=sha256,
        byte_size=manifest["byte_size"],
        schema_version=schema_version,
        row_counts=row_counts,
        pruned=pruned,
    )


@dataclass(frozen=True, slots=True)
class RestoreResult:
    restored_path: Path
    sha256: str
    schema_version: int
    verified: bool
    integrity: list[str] | None = None
    foreign_key_violations: list[dict[str, Any]] | None = None
    media_roots: list[dict[str, Any]] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "restored": public_path(self.restored_path),
            "sha256": self.sha256,
            "schema_version": self.schema_version,
            "verified": self.verified,
            "integrity": self.integrity,
            "foreign_key_violations": self.foreign_key_violations,
            "media_roots": self.media_roots,
        }


def _verify_backup_file(backup_path: Path) -> tuple[str, dict[str, Any] | None]:
    """Hash the backup and check it against its manifest, when present."""
    sha256 = _sha256_file(backup_path)
    manifest_path = _manifest_path(backup_path)
    if not manifest_path.is_file():
        return sha256, None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("sha256") != sha256:
        raise ValueError(
            "backup digest mismatch: manifest records "
            f"{manifest.get('sha256', '?')[:16]}… but the file hashes {sha256[:16]}…"
        )
    if manifest.get("format") != "catalog-backup-v1":
        raise ValueError("backup manifest has an unknown format")
    return sha256, manifest


def restore_catalog(
    backup_path: Path,
    *,
    to: Path,
    force: bool = False,
    verify: bool = False,
    media_roots: tuple[Path, ...] = (),
) -> RestoreResult:
    """Verify a backup, then restore it to a new catalog path."""
    backup_path = Path(backup_path)
    if not backup_path.is_file():
        raise ValueError("backup file does not exist")
    to = Path(to)
    if to.exists() and not force:
        raise ValueError(f"restore target already exists: {public_path(to)}; use --force")
    sha256, manifest = _verify_backup_file(backup_path)

    source = CatalogDatabase.open_read_only(backup_path)
    try:
        schema_version = source.schema_version
    finally:
        source.close()

    to.parent.mkdir(parents=True, exist_ok=True)
    temp_target = to.with_name(to.name + ".restore-tmp")
    if temp_target.exists():
        temp_target.unlink()
    temp_target.write_bytes(backup_path.read_bytes())
    os_replace(temp_target, to)

    integrity: list[str] | None = None
    foreign_keys: list[dict[str, Any]] | None = None
    media_reports: list[dict[str, Any]] | None = None
    if verify:
        with CatalogDatabase(to) as database:
            integrity = [row[0] for row in database.connection.execute("PRAGMA integrity_check")]
            foreign_keys = [
                dict(row) for row in database.connection.execute("PRAGMA foreign_key_check")
            ]
            if integrity != ["ok"] or foreign_keys:
                raise ValueError(
                    "restored catalog failed verification"
                    f" (integrity: {integrity}, foreign keys: {len(foreign_keys)})"
                )
            row_counts = _row_counts(database.connection)
        if manifest is not None:
            recorded = manifest.get("row_counts", {})
            if row_counts != recorded:
                raise ValueError("restored catalog row counts differ from the manifest")
        if media_roots:
            from media_catalog.storage.verification import AssetStorageVerifier

            media_reports = []
            for root in media_roots:
                report = AssetStorageVerifier(to, root).verify()
                media_reports.append(
                    {
                        "media_root": public_path(Path(root)),
                        "ok": report.ok,
                        "entries_examined": report.entries_examined,
                        "findings": [finding.as_dict() for finding in report.findings],
                    }
                )
                if not report.ok:
                    raise ValueError(f"media root verification failed: {public_path(Path(root))}")
    return RestoreResult(
        restored_path=to,
        sha256=sha256,
        schema_version=schema_version,
        verified=verify,
        integrity=integrity,
        foreign_key_violations=foreign_keys,
        media_roots=media_reports,
    )


def backup_doctor_section(catalog: Path) -> dict[str, Any]:
    """Backup state for doctor: neutral when absent, failing on drift."""
    destination = default_backup_dir(Path(catalog))
    pairs = _backup_pairs(destination)
    if not pairs:
        return {"backup": {"directory": public_path(destination), "backups": "none"}}
    latest_file, latest_manifest = pairs[-1]
    backup_section: dict[str, Any] = {
        "directory": public_path(destination),
        "latest": public_path(latest_file),
    }
    section: dict[str, Any] = {"backup": backup_section}
    if latest_manifest is None:
        backup_section["manifest"] = "missing"
        backup_section["ok"] = False
        return section
    manifest = json.loads(latest_manifest.read_text(encoding="utf-8"))
    section["backup"]["created_at"] = manifest.get("created_at")
    section["backup"]["schema_version"] = manifest.get("schema_version")
    actual = _sha256_file(latest_file)
    if actual != manifest.get("sha256"):
        backup_section["ok"] = False
        backup_section["digest"] = "mismatch"
    else:
        backup_section["ok"] = True
        backup_section["digest"] = "verified"
    return section
