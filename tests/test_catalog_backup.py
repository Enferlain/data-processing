"""Catalog backup/restore with integrity verification (bead data-processing-dbq).

Pins the operator contract: online consistent snapshots under active WAL
writers, self-describing manifests whose digest is the trust anchor,
verify-first restore that never writes on failure, retention that keeps the
newest verified backup, and doctor reporting that is neutral about absence
but fails on digest drift.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from media_catalog.backup import (
    backup_catalog,
    backup_doctor_section,
    default_backup_dir,
    restore_catalog,
)
from media_catalog.database import CatalogDatabase


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "private" / "catalog.sqlite3"
    with CatalogDatabase(path) as database, database.transaction():
        platform_id = int(
            database.connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'pixiv'"
            ).fetchone()[0]
        )
        database.connection.execute(
            """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
               VALUES (?, 'backup-1', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
            (platform_id,),
        )
    return path


def _wait_next_second() -> None:
    import time

    now = time.localtime()
    time.sleep(max(0.0, 1.05 - (now.tm_sec % 1)))


def test_backup_is_consistent_under_an_active_wal_writer(catalog: Path) -> None:
    writer = sqlite3.connect(catalog)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(
            "UPDATE posts SET last_seen_at = '2026-11-08T00:00:00Z'"
            " WHERE native_post_id = 'backup-1'"
        )
        writer.commit()
        result = backup_catalog(catalog)

        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        assert manifest["format"] == "catalog-backup-v1"
        assert manifest["schema_version"] == 33
        assert manifest["row_counts"]["posts"] == 1
        assert manifest["sha256"] == result.sha256
        assert manifest["byte_size"] == result.byte_size
        # The backup opens cleanly and carries the committed WAL state.
        with CatalogDatabase(result.backup_path) as restored:
            assert restored.schema_version == 33
            last_seen = restored.connection.execute(
                "SELECT last_seen_at FROM posts WHERE native_post_id = 'backup-1'"
            ).fetchone()[0]
        assert last_seen == "2026-11-08T00:00:00Z"
    finally:
        writer.close()


def test_default_destination_is_the_sibling_backup_directory(catalog: Path) -> None:
    result = backup_catalog(catalog)
    assert result.backup_path.parent == default_backup_dir(catalog)
    assert default_backup_dir(catalog) == catalog.parent / "catalog-backups"


def test_restore_verifies_manifest_and_refuses_tampered_backups(
    catalog: Path,
) -> None:
    result = backup_catalog(catalog)
    payload = bytearray(result.backup_path.read_bytes())
    payload[-1] ^= 0xFF
    result.backup_path.write_bytes(bytes(payload))
    target = catalog.parent / "restored.sqlite3"
    with pytest.raises(ValueError, match="digest mismatch"):
        restore_catalog(result.backup_path, to=target)
    assert not target.exists()  # failure wrote nothing


def test_restore_refuses_overwrite_without_force(catalog: Path) -> None:
    result = backup_catalog(catalog)
    target = catalog.parent / "restored.sqlite3"
    target.write_bytes(result.backup_path.read_bytes())
    with pytest.raises(ValueError, match="restore target already exists"):
        restore_catalog(result.backup_path, to=target)
    forced = restore_catalog(result.backup_path, to=target, force=True, verify=True)
    assert forced.verified is True
    assert forced.integrity == ["ok"]
    assert forced.foreign_key_violations == []
    assert forced.media_roots is None


def test_restore_row_counts_must_match_manifest(catalog: Path) -> None:
    result = backup_catalog(catalog)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest["row_counts"]["posts"] = 99
    result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    # The digest still matches the file; the count check is a --verify check.
    # Recompute digest so the tamper is only in the counts:
    # (rewriting the manifest keeps the sqlite digest unchanged)
    target = catalog.parent / "restored2.sqlite3"
    with pytest.raises(ValueError, match="row counts differ"):
        restore_catalog(result.backup_path, to=target, verify=True)


def test_retention_keeps_the_newest_verified_backup(catalog: Path) -> None:
    first = backup_catalog(catalog)
    _wait_next_second()
    second = backup_catalog(catalog, keep=1)
    destination = second.backup_path.parent
    remaining = sorted(path.name for path in destination.glob("*.sqlite3"))
    assert remaining == [second.backup_path.name]
    assert first.backup_path.name in second.pruned
    assert not first.manifest_path.exists()
    # The newest is never pruned by retention.
    _wait_next_second()
    third = backup_catalog(catalog, keep=1)
    assert third.backup_path.exists()
    assert third.backup_path.name not in third.pruned


def test_doctor_section_is_neutral_without_backups_and_fails_on_drift(
    catalog: Path,
) -> None:
    neutral = backup_doctor_section(catalog)
    assert neutral == {"backup": {"directory": "catalog-backups", "backups": "none"}}

    result = backup_catalog(catalog)
    healthy = backup_doctor_section(catalog)
    assert healthy["backup"]["ok"] is True
    assert healthy["backup"]["digest"] == "verified"
    assert healthy["backup"]["schema_version"] == 33

    payload = bytearray(result.backup_path.read_bytes())
    payload[-1] ^= 0xFF
    result.backup_path.write_bytes(bytes(payload))
    drifted = backup_doctor_section(catalog)
    assert drifted["backup"]["ok"] is False
    assert drifted["backup"]["digest"] == "mismatch"


def test_cli_backup_restore_and_doctor_report(
    catalog: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from media_catalog.cli import main

    main(["backup", str(catalog), "--json"])
    backed_up = json.loads(capsys.readouterr().out)
    assert backed_up["catalog"] == "catalog.sqlite3"
    assert backed_up["schema_version"] == 33
    backup_path = catalog.parent / "catalog-backups" / (Path(backed_up["backup"]).name)
    assert backup_path.is_file()

    target = catalog.parent / "restored.sqlite3"
    main(["restore", str(backup_path), "--to", str(target), "--verify", "--json"])
    restored = json.loads(capsys.readouterr().out)
    assert restored["verified"] is True
    assert restored["integrity"] == ["ok"]

    main(["doctor", str(catalog), "--json"])
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["backup"]["ok"] is True
    assert doctor["ok"] is True

    payload = bytearray(backup_path.read_bytes())
    payload[-1] ^= 0xFF
    backup_path.write_bytes(bytes(payload))
    main(["doctor", str(catalog), "--json"])
    drifted = json.loads(capsys.readouterr().out)
    assert drifted["backup"]["ok"] is False
    assert drifted["ok"] is False


def test_cli_backup_runs_while_a_wal_writer_holds_committed_frames(
    catalog: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from media_catalog.cli import main

    writer = sqlite3.connect(catalog)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(
            "UPDATE posts SET last_seen_at = '2026-11-08T00:00:00Z'"
            " WHERE native_post_id = 'backup-1'"
        )
        writer.commit()
        main(["backup", str(catalog), "--json"])
        result = json.loads(capsys.readouterr().out)
        assert result["schema_version"] == 33
        with CatalogDatabase(
            Path(catalog.parent, "catalog-backups", Path(result["backup"]).name)
        ) as snapshot:
            last_seen = snapshot.connection.execute(
                "SELECT last_seen_at FROM posts WHERE native_post_id = 'backup-1'"
            ).fetchone()[0]
        assert last_seen == "2026-11-08T00:00:00Z"
    finally:
        writer.close()
