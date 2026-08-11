from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from media_catalog.acquisition.planning import PlannedAcquisitionItem
from media_catalog.asset_storage import (
    AssetStorage,
    InspectionResult,
    LimitExceededError,
    StagedAsset,
)
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    AcquisitionQuarantineRecord,
    AcquisitionRunItemRecord,
    AcquisitionVerificationRecord,
    AssetFingerprintRecord,
    AssetLocationRecord,
    AssetRecord,
    OccurrenceSourceRecord,
)
from media_catalog.writer import CatalogWriter

SHA256_VERSION = "sha256-v1"
MD5_VERSION = "md5-v1"
PHASH_VERSION = "imagehash.phash-v1"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ClaimComparison:
    kind: str
    declared: str
    verified: str
    result: str


@dataclass(frozen=True, slots=True)
class PublicationResult:
    outcome: str
    inspection: InspectionResult
    comparisons: tuple[ClaimComparison, ...]
    asset_id: int | None = None
    relative_path: str | None = None
    published_new: bool = False
    quarantine_id: int | None = None
    quarantined_bytes: int = 0


def compare_declared_claims(
    item: PlannedAcquisitionItem,
    inspection: InspectionResult,
) -> tuple[ClaimComparison, ...]:
    values: tuple[tuple[str, object | None, object], ...] = (
        ("sha256", item.declared_sha256, inspection.sha256),
        ("md5", item.declared_md5, inspection.md5),
        ("file_size", item.declared_file_size, inspection.size),
        ("mime_type", item.declared_mime_type, inspection.mime_type),
        ("width", item.declared_width, inspection.width),
        ("height", item.declared_height, inspection.height),
    )
    comparisons: list[ClaimComparison] = []
    for kind, declared_value, verified_value in values:
        if declared_value is None:
            continue
        declared = str(declared_value).lower() if kind in {"sha256", "md5"} else str(declared_value)
        if verified_value is None:
            verified = "unavailable"
            result = "not_comparable"
        else:
            verified = (
                str(verified_value).lower()
                if kind in {"sha256", "md5"}
                else str(verified_value)
            )
            if kind == "mime_type" and "/" not in declared:
                result = "not_comparable"
            else:
                result = "matched" if declared.lower() == verified.lower() else "mismatched"
        comparisons.append(ClaimComparison(kind, declared, verified, result))
    return tuple(comparisons)


def _persist_comparisons(
    writer: CatalogWriter,
    run_item_id: int,
    item: PlannedAcquisitionItem,
    comparisons: tuple[ClaimComparison, ...],
    created_at: str,
) -> None:
    for comparison in comparisons:
        writer.record_acquisition_verification(
            AcquisitionVerificationRecord(
                run_item_id,
                comparison.kind,
                comparison.declared,
                comparison.verified,
                comparison.result,
                created_at,
                item.source_raw_observation_id,
            )
        )


def _persist_asset(
    writer: CatalogWriter,
    *,
    item: PlannedAcquisitionItem,
    inspection: InspectionResult,
    managed_root_id: int,
    relative_path: str,
    request_identity: str,
    observed_at: str,
) -> int:
    asset_id = writer.link_asset(
        item.media_occurrence_id,
        AssetRecord(
            inspection.sha256,
            inspection.md5,
            inspection.phash,
            inspection.size,
            "managed",
            None,
            observed_at,
            "acquisition",
            inspection.mime_type,
            inspection.width,
            inspection.height,
            inspection.frame_count,
        ),
        relationship="downloaded",
    )
    writer.add_asset_location(
        AssetLocationRecord(
            asset_id,
            managed_root_id,
            relative_path,
            byte_size=inspection.size,
            recorded_sha256=inspection.sha256,
            created_at=observed_at,
        )
    )
    writer.add_occurrence_source(
        OccurrenceSourceRecord(
            item.media_occurrence_id,
            "external",
            f"request:{request_identity}",
            observed_at,
            source_identity=request_identity,
        )
    )
    writer.add_asset_fingerprint(
        AssetFingerprintRecord(
            asset_id,
            "sha256",
            inspection.sha256,
            "sha256",
            SHA256_VERSION,
            "acquisition",
            "verified",
            observed_at,
        )
    )
    writer.add_asset_fingerprint(
        AssetFingerprintRecord(
            asset_id,
            "md5",
            inspection.md5,
            "md5",
            MD5_VERSION,
            "acquisition",
            "verified",
            observed_at,
        )
    )
    if inspection.phash is not None:
        writer.add_asset_fingerprint(
            AssetFingerprintRecord(
                asset_id,
                "phash",
                inspection.phash,
                inspection.phash_algorithm or "phash",
                PHASH_VERSION,
                "acquisition",
                "calculated",
                observed_at,
            )
        )
    return asset_id


def verify_publish_and_persist(
    database: CatalogDatabase,
    storage: AssetStorage,
    *,
    item: PlannedAcquisitionItem,
    staged: StagedAsset,
    run_item_id: int,
    acquisition_attempt_id: int | None,
    managed_root_id: int,
    request_identity: str,
    max_quarantine_bytes: int,
    clock: Callable[[], str] = _now,
) -> PublicationResult:
    """Inspect, compare, publish, and persist one completed remote staging file."""

    inspection = storage.inspect_staged(staged)
    comparisons = compare_declared_claims(item, inspection)
    exact_mismatch = any(
        comparison.kind in {"sha256", "md5"} and comparison.result == "mismatched"
        for comparison in comparisons
    )
    writer = CatalogWriter(database)
    created_at = clock()
    with database.transaction():
        _persist_comparisons(writer, run_item_id, item, comparisons, created_at)
        row = database.connection.execute(
            "SELECT * FROM media_acquisition_run_items WHERE acquisition_run_item_id = ?",
            (run_item_id,),
        ).fetchone()
        if row is None or row["state"] not in {"pending", "running"}:
            raise ValueError("acquisition run item cannot accept verified exact evidence")
        writer.record_acquisition_run_item(
            AcquisitionRunItemRecord(
                int(row["acquisition_run_id"]),
                int(row["acquisition_plan_item_id"]),
                "running",
                str(row["created_at"]),
                created_at,
                attempt_count=int(row["attempt_count"]),
                received_bytes=int(row["received_bytes"]),
                sha256=inspection.sha256,
                md5=inspection.md5,
            )
        )
    if exact_mismatch:
        try:
            quarantined = storage.quarantine_staged(
                staged,
                reason="hash_mismatch",
                max_bytes=max_quarantine_bytes,
            )
            storage.cleanup_staging(staged)
            quarantine = AcquisitionQuarantineRecord(
                run_item_id,
                managed_root_id,
                quarantined.quarantine_name,
                "hash_mismatch",
                quarantined.size,
                created_at,
                acquisition_attempt_id,
                quarantined.sha256,
                quarantined.md5,
            )
            quarantined_bytes = quarantined.size
        except LimitExceededError:
            storage.cleanup_staging(staged)
            quarantine = AcquisitionQuarantineRecord(
                run_item_id,
                managed_root_id,
                f"not-retained-{secrets.token_hex(16)}",
                "hash_mismatch",
                inspection.size,
                created_at,
                acquisition_attempt_id,
                inspection.sha256,
                inspection.md5,
                "missing",
            )
            quarantined_bytes = 0
        with database.transaction():
            quarantine_id = writer.record_acquisition_quarantine(quarantine)
        return PublicationResult(
            "hash_mismatch",
            inspection,
            comparisons,
            quarantine_id=quarantine_id,
            quarantined_bytes=quarantined_bytes,
        )

    # Publication is durable before the catalog gains an asset/location reference.
    relative_path, published_new = storage.publish_staged(staged)
    with database.transaction():
        asset_id = _persist_asset(
            writer,
            item=item,
            inspection=inspection,
            managed_root_id=managed_root_id,
            relative_path=relative_path,
            request_identity=request_identity,
            observed_at=created_at,
        )
    return PublicationResult(
        "downloaded_exact_only" if inspection.exact_only else "downloaded",
        inspection,
        comparisons,
        asset_id,
        relative_path,
        published_new,
    )
