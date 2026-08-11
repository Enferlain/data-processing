from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image

from media_catalog.acquisition.planning import PlannedAcquisitionItem
from media_catalog.acquisition.policies import PIXIV_MEDIA_POLICY
from media_catalog.acquisition.publication import verify_publish_and_persist
from media_catalog.asset_storage import AssetStorage, InspectionLimits, StagedAsset
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    AcquisitionLimits,
    AcquisitionPlanRecord,
    AcquisitionRunItemRecord,
    AcquisitionRunRecord,
    ManagedRootRecord,
)
from media_catalog.writer import CatalogWriter

NOW = "2026-08-10T12:00:00Z"


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 3), color=(20, 40, 60)).save(output, format="PNG")
    return output.getvalue()


def _planned_item(
    occurrence_id: int,
    *,
    sha256: str | None = None,
    md5: str | None = None,
    size: int | None = None,
    mime_type: str | None = "image/png",
    width: int | None = 4,
    height: int | None = 3,
) -> PlannedAcquisitionItem:
    return PlannedAcquisitionItem(
        "item-key",
        occurrence_id,
        "original",
        "https://i.pximg.net/file.png?signature=private",
        "a" * 64,
        PIXIV_MEDIA_POLICY.identity,
        None,
        "eligible",
        None,
        None,
        sha256,
        md5,
        size,
        mime_type,
        width,
        height,
    )


def _seed(
    database: CatalogDatabase,
    storage: AssetStorage,
    *,
    item_factory=_planned_item,
) -> tuple[PlannedAcquisitionItem, int, int]:
    writer = CatalogWriter(database)
    with database.transaction():
        platform_id = int(
            database.connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'pixiv'"
            ).fetchone()[0]
        )
        post_id = int(
            database.connection.execute(
                """INSERT INTO posts (
                       platform_id, native_post_id, first_seen_at, last_seen_at
                   ) VALUES (?, 'publication-fixture', ?, ?)""",
                (platform_id, NOW, NOW),
            ).lastrowid
        )
        occurrence_id = int(
            database.connection.execute(
                """INSERT INTO media_occurrences (
                       post_id, source_key, media_index, media_type, remote_url, observed_at
                   ) VALUES (?, 'fixture:p0', 0, 'image',
                             'https://i.pximg.net/file.png', ?)""",
                (post_id, NOW),
            ).lastrowid
        )
        item = item_factory(occurrence_id)
        managed_id = writer.register_managed_root(
            ManagedRootRecord(
                "managed",
                f"{storage.media.identity[0]}:{storage.media.identity[1]}",
                "managed",
                None,
                NOW,
            )
        )
        plan_id = writer.create_acquisition_plan(
            AcquisitionPlanRecord("plan-v1", "b" * 64, 1, 1, 0, 0, NOW)
        )
        plan_item_id = writer.add_acquisition_plan_item(item.to_record(plan_id, NOW))
        run_id = writer.begin_acquisition_run(
            AcquisitionRunRecord(
                plan_id,
                managed_id,
                AcquisitionLimits(1, 1000, 1000, 1, 30, 3, 1000),
                1,
                NOW,
            )
        )
        run_item_id = writer.record_acquisition_run_item(
            AcquisitionRunItemRecord(run_id, plan_item_id, "running", NOW, NOW)
        )
    return item, run_item_id, managed_id


def _stage(
    storage: AssetStorage, payload: bytes, *, label: str = "remote:pixiv.png"
) -> StagedAsset:
    session = storage.begin_remote_staging("c" * 64, max_bytes=1000)
    session.write(payload)
    return session.finalize(source_label=label)


def test_inspects_publishes_and_persists_verified_asset_and_provenance(
    tmp_path: Path,
) -> None:
    payload = _png()
    expected_sha = hashlib.sha256(payload).hexdigest()
    expected_md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()

    def item_factory(occurrence_id: int) -> PlannedAcquisitionItem:
        return _planned_item(
            occurrence_id,
            sha256=expected_sha,
            md5=expected_md5,
            size=len(payload),
        )

    managed = tmp_path / "managed"
    managed.mkdir()
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database, AssetStorage.for_remote(
        managed,
        limits=InspectionLimits(max_bytes=1000, max_pixels=1000, max_frames=10),
    ) as storage:
        item, run_item_id, managed_id = _seed(
            database, storage, item_factory=item_factory
        )
        result = verify_publish_and_persist(
            database,
            storage,
            item=item,
            staged=_stage(storage, payload, label="remote:pixiv.bin"),
            run_item_id=run_item_id,
            acquisition_attempt_id=None,
            managed_root_id=managed_id,
            request_identity="c" * 64,
            max_quarantine_bytes=1000,
            clock=lambda: NOW,
        )

        assert result.outcome == "downloaded"
        assert result.asset_id is not None
        assert result.published_new
        assert (result.inspection.width, result.inspection.height) == (4, 3)
        assert {comparison.result for comparison in result.comparisons} == {"matched"}
        asset = database.connection.execute("SELECT * FROM assets").fetchone()
        assert asset["verified_sha256"] == expected_sha
        assert asset["verified_md5"] == expected_md5
        assert asset["storage_kind"] == "managed"
        assert asset["detected_mime_type"] == "image/png"
        assert database.connection.execute(
            "SELECT COUNT(*) FROM asset_fingerprints WHERE asset_id = ?", (result.asset_id,)
        ).fetchone()[0] == 3
        source = database.connection.execute("SELECT * FROM occurrence_sources").fetchone()
        assert source["relative_path"] == f"request:{'c' * 64}"
        assert "private" not in str(dict(source))


def test_exact_hash_mismatch_is_quarantined_and_never_linked(tmp_path: Path) -> None:
    payload = _png()

    def item_factory(occurrence_id: int) -> PlannedAcquisitionItem:
        return _planned_item(occurrence_id, md5="0" * 32, size=len(payload))

    managed = tmp_path / "managed"
    managed.mkdir()
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database, AssetStorage.for_remote(
        managed,
        limits=InspectionLimits(max_bytes=1000, max_pixels=1000, max_frames=10),
    ) as storage:
        item, run_item_id, managed_id = _seed(
            database, storage, item_factory=item_factory
        )
        result = verify_publish_and_persist(
            database,
            storage,
            item=item,
            staged=_stage(storage, payload, label="remote:pixiv.bin"),
            run_item_id=run_item_id,
            acquisition_attempt_id=None,
            managed_root_id=managed_id,
            request_identity="c" * 64,
            max_quarantine_bytes=1000,
            clock=lambda: NOW,
        )

        assert result.outcome == "hash_mismatch"
        assert result.asset_id is None
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
        assert database.connection.execute(
            "SELECT COUNT(*) FROM occurrence_assets"
        ).fetchone()[0] == 0
        comparison = database.connection.execute(
            "SELECT * FROM media_acquisition_verifications WHERE claim_kind = 'md5'"
        ).fetchone()
        assert comparison["comparison_result"] == "mismatched"
        quarantine = database.connection.execute(
            "SELECT * FROM media_acquisition_quarantine"
        ).fetchone()
        assert quarantine["state"] == "retained"
        assert len(list((managed / "quarantine").iterdir())) == 1


def test_quarantine_budget_retains_metadata_only_and_exact_only_can_publish(
    tmp_path: Path,
) -> None:
    payload = b"not-a-supported-image-format"
    managed = tmp_path / "managed"
    managed.mkdir()
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database, AssetStorage.for_remote(
        managed,
        limits=InspectionLimits(max_bytes=1000, max_pixels=1000, max_frames=10),
    ) as storage:
        item, run_item_id, managed_id = _seed(database, storage)
        result = verify_publish_and_persist(
            database,
            storage,
            item=item,
            staged=_stage(storage, payload, label="remote:pixiv.bin"),
            run_item_id=run_item_id,
            acquisition_attempt_id=None,
            managed_root_id=managed_id,
            request_identity="c" * 64,
            max_quarantine_bytes=1000,
            clock=lambda: NOW,
        )
        assert result.outcome == "downloaded_exact_only"
        assert result.inspection.exact_only
        assert result.asset_id is not None
