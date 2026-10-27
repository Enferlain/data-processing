"""Anchorless-observation repair tests (OpenSpec source-scoped-anchorless-identity).

The repair dedups pre-0018 anchorless duplicates under the strict 0018
definition so the migration chain passes: keep the earliest row, re-point
referencing rows (update triggers lift and recreate verbatim), delete
unreferenced members, and report same-platform and cross-platform folds
separately.  Dry run is the default and touches nothing.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

from media_catalog.database import CatalogDatabase
from media_catalog.records import AccountRecord, RawRecord
from media_catalog.writer import CatalogWriter

_NOW = "2026-01-01T00:00:00Z"

_SPEC = importlib.util.spec_from_file_location(
    "repair_anchorless_observations",
    Path(__file__).parent.parent / "scripts" / "repair_anchorless_observations.py",
)
repair = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(repair)


def _catalog_with_duplicates(catalog: Path, *, referenced_member: bool) -> dict[str, int]:
    """Seed the pre-0018 damage on a schema-17 catalog: a same-platform retry
    and a cross-platform twin of one observation, plus (optionally) an account
    snapshot referencing the retry row.

    A fresh catalog is already at schema 19, whose platform-scoped indexes
    prevent the damage from existing at all -- so the fixture drops the
    anchorless indexes and rewinds the version, exactly the state the repair
    targets (the real catalog's shape below 0018).
    """

    with CatalogDatabase(catalog) as database:
        writer = CatalogWriter(database)
        with database.transaction():
            keep = writer.store_raw(
                RawRecord(
                    b'{"ok":1}',
                    "application/json",
                    "post",
                    "42",
                    _NOW,
                    platform="danbooru",
                )
            )
            account_id = writer.upsert_account(
                AccountRecord("danbooru", "99", _NOW, handle="artist"),
                raw_observation_id=keep,
            ).id
    raw = sqlite3.connect(catalog)
    raw.execute("DROP INDEX raw_observations_anchorless_native_idx")
    raw.execute("DROP INDEX raw_observations_anchorless_anonymous_idx")
    triggers = raw.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' "
        "AND tbl_name = 'account_snapshots'"
    ).fetchall()
    for name, _ in triggers:
        raw.execute(f"DROP TRIGGER {name}")
    retry_id = int(
        raw.execute(
            """INSERT INTO raw_observations (
                   raw_payload_id, platform_id, object_kind, native_id,
                   media_type, observed_at, adapter_version, schema_version
               ) SELECT raw_payload_id, platform_id, object_kind, native_id,
                        media_type, '2026-01-02T00:00:00Z', adapter_version,
                        schema_version
                  FROM raw_observations WHERE raw_observation_id = ?""",
            (keep,),
        ).lastrowid
    )
    twin_id = int(
        raw.execute(
            """INSERT INTO raw_observations (
                   raw_payload_id, platform_id, object_kind, native_id,
                   media_type, observed_at, adapter_version, schema_version
               ) SELECT raw_payload_id, ?, object_kind, native_id, media_type,
                        '2026-01-03T00:00:00Z', adapter_version, schema_version
                  FROM raw_observations WHERE raw_observation_id = ?""",
            (
                raw.execute(
                    "SELECT platform_id FROM platforms WHERE platform_key = 'aibooru'"
                ).fetchone()[0],
                keep,
            ),
        ).lastrowid
    )
    if referenced_member:
        # A referencing row on the retry member proves the re-point path.
        raw.execute(
            "UPDATE account_snapshots SET raw_observation_id = ? WHERE account_id = ?",
            (retry_id, account_id),
        )
    for _, sql in triggers:
        raw.execute(sql)
    raw.execute("PRAGMA user_version = 17")
    raw.commit()
    raw.close()
    return {"keep": keep, "retry": retry_id, "twin": twin_id, "account_id": account_id}


def test_dry_run_reports_without_touching(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _catalog_with_duplicates(catalog, referenced_member=True)
    before = (catalog).read_bytes()
    report = repair.plan_and_apply(catalog, apply=False)
    assert report["applied"] is False
    assert report["folds"] == {"same_platform": 1, "cross_platform": 1}
    assert len(report["plan"]) == 2
    assert catalog.read_bytes() == before


def test_apply_folds_repoints_and_verifies(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    ids = _catalog_with_duplicates(catalog, referenced_member=True)
    report = repair.plan_and_apply(catalog, apply=True)
    assert report["applied"] is True
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        remaining = connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0]
        assert remaining == 1
        # The snapshot was re-pointed at the keeper, not orphaned.
        pointed = connection.execute(
            "SELECT raw_observation_id FROM account_snapshots WHERE account_id = ?",
            (ids["account_id"],),
        ).fetchone()[0]
        assert pointed == ids["keep"]
        # The immutability triggers dropped for the deletes are back.
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND tbl_name = 'raw_observations'"
            )
        }
        assert triggers, "immutability triggers were not recreated"
        with _expect_block():
            connection.execute(
                "UPDATE raw_observations SET native_id = 'x' WHERE raw_observation_id = ?",
                (ids["keep"],),
            )
        # The repaired catalog migrates through 0019.
        assert connection.execute("PRAGMA user_version").fetchone()[0] >= 19
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


class _expect_block:
    def __enter__(self) -> None:
        self.succeeded = False

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None and issubclass(exc_type, sqlite3.DatabaseError):
            return True
        raise AssertionError("immutability trigger did not fire after repair")


def test_cross_platform_twin_survives_under_source_scoped_identity(
    tmp_path: Path,
) -> None:
    """Without the referenced-retry fold, only the twin needs folding -- and
    under the 0019 identity the same two-platform bytes land as two rows."""

    catalog = tmp_path / "catalog.sqlite3"
    ids = _catalog_with_duplicates(catalog, referenced_member=False)
    report = repair.plan_and_apply(catalog, apply=True)
    assert report["folds"] == {"same_platform": 1, "cross_platform": 1}
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        # Post-repair under 0018's strict definition both members folded;
        # verify the surviving semantics: re-storing the same bytes from the
        # other platform now lands its own observation (0019 identity).
        writer = CatalogWriter(database)
        with database.transaction():
            mirror = writer.store_raw(
                RawRecord(b'{"ok":1}', "application/json", "post", "42", _NOW, platform="aibooru")
            )
        platforms = {
            row[0]
            for row in connection.execute(
                """SELECT pl.platform_key FROM raw_observations ro
                     JOIN platforms pl ON pl.platform_id = ro.platform_id
                    WHERE ro.object_kind = 'post' AND ro.native_id = '42'"""
            )
        }
        assert platforms == {"danbooru", "aibooru"}
        assert mirror != ids["keep"]
