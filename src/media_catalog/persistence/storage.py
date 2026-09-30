from __future__ import annotations

import json
from dataclasses import asdict

from media_catalog.database import CatalogDatabase
from media_catalog.persistence.support import caller_connection, inserted_id, now
from media_catalog.records import (
    AdoptionAttemptRecord,
    AdoptionItemRecord,
    AdoptionRunRecord,
    AssetFingerprintRecord,
    AssetLocationRecord,
    ManagedRootRecord,
    OccurrenceSourceRecord,
)


class StorageWrites:
    def __init__(self, database: CatalogDatabase) -> None:
        self.connection = caller_connection(database)

    def register_managed_root(self, record: ManagedRootRecord) -> int:
        """Insert or retrieve a stable source/managed root identity."""
        created_at = record.created_at or now()
        self.connection.execute(
            """INSERT INTO managed_roots (
                   root_kind, root_identity, display_label, private_path, created_at
               ) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(root_kind, root_identity) DO UPDATE SET
                   display_label = excluded.display_label,
                   private_path = COALESCE(excluded.private_path, managed_roots.private_path)""",
            (
                record.root_kind,
                record.root_identity,
                record.display_label,
                record.private_path,
                created_at,
            ),
        )
        return int(
            self.connection.execute(
                """SELECT managed_root_id FROM managed_roots
                   WHERE root_kind = ? AND root_identity = ?""",
                (record.root_kind, record.root_identity),
            ).fetchone()[0]
        )

    def add_asset_location(self, record: AssetLocationRecord) -> int:
        created_at = record.created_at or now()
        self.connection.execute(
            """INSERT INTO asset_locations (
                   asset_id, managed_root_id, relative_path, location_kind, byte_size,
                   recorded_sha256, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(managed_root_id, relative_path) DO UPDATE SET
                   location_kind = excluded.location_kind,
                   byte_size = COALESCE(excluded.byte_size, asset_locations.byte_size),
                   recorded_sha256 = COALESCE(excluded.recorded_sha256,
                                              asset_locations.recorded_sha256)
               WHERE asset_locations.asset_id = excluded.asset_id""",
            (
                record.asset_id,
                record.managed_root_id,
                record.relative_path,
                record.location_kind,
                record.byte_size,
                record.recorded_sha256,
                created_at,
            ),
        )
        row = self.connection.execute(
            """SELECT asset_location_id, asset_id FROM asset_locations
               WHERE managed_root_id = ? AND relative_path = ?""",
            (record.managed_root_id, record.relative_path),
        ).fetchone()
        if row is None or int(row["asset_id"]) != record.asset_id:
            raise ValueError("managed location is already assigned to another asset")
        return int(row["asset_location_id"])

    def add_occurrence_source(self, record: OccurrenceSourceRecord) -> int:
        self.connection.execute(
            """INSERT INTO occurrence_sources (
                   media_occurrence_id, managed_root_id, source_kind, relative_path,
                   source_identity, recorded_at
               ) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(media_occurrence_id, managed_root_id, relative_path, source_kind)
               DO UPDATE SET source_identity = COALESCE(
                   excluded.source_identity, occurrence_sources.source_identity),
                   recorded_at = MAX(excluded.recorded_at, occurrence_sources.recorded_at)""",
            (
                record.media_occurrence_id,
                record.managed_root_id,
                record.source_kind,
                record.relative_path,
                record.source_identity,
                record.recorded_at,
            ),
        )
        return int(
            self.connection.execute(
                """SELECT occurrence_source_id FROM occurrence_sources
                   WHERE media_occurrence_id = ? AND managed_root_id IS ?
                     AND relative_path = ? AND source_kind = ?""",
                (
                    record.media_occurrence_id,
                    record.managed_root_id,
                    record.relative_path,
                    record.source_kind,
                ),
            ).fetchone()[0]
        )

    def add_asset_fingerprint(self, record: AssetFingerprintRecord) -> int:
        self.connection.execute(
            """INSERT INTO asset_fingerprints (
                   asset_id, fingerprint_kind, fingerprint_value, algorithm,
                   algorithm_version, source, verification_status, observed_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(asset_id, fingerprint_kind, algorithm, algorithm_version, source)
               DO UPDATE SET fingerprint_value = excluded.fingerprint_value,
                   verification_status = excluded.verification_status,
                   observed_at = excluded.observed_at""",
            (
                record.asset_id,
                record.fingerprint_kind,
                record.fingerprint_value,
                record.algorithm,
                record.algorithm_version,
                record.source,
                record.verification_status,
                record.observed_at,
            ),
        )
        return int(
            self.connection.execute(
                """SELECT asset_fingerprint_id FROM asset_fingerprints
                   WHERE asset_id = ? AND fingerprint_kind = ? AND algorithm = ?
                     AND algorithm_version = ? AND source = ?""",
                (
                    record.asset_id,
                    record.fingerprint_kind,
                    record.algorithm,
                    record.algorithm_version,
                    record.source,
                ),
            ).fetchone()[0]
        )

    def begin_adoption_run(self, record: AdoptionRunRecord) -> int:
        limits = json.dumps(asdict(record.limits), sort_keys=True, separators=(",", ":"))
        cursor = self.connection.execute(
            """INSERT INTO adoption_runs (
                   source_root_id, managed_root_id, source_root_identity, managed_root_identity,
                   algorithm_version, fingerprint_algorithm, limits_json, started_at, finished_at,
                   status, planned_count, completed_count, failed_count, diagnostic
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.source_root_id,
                record.managed_root_id,
                record.source_root_identity,
                record.managed_root_identity,
                record.algorithm_version,
                record.fingerprint_algorithm,
                limits,
                record.started_at,
                record.finished_at,
                record.status,
                record.planned_count,
                record.completed_count,
                record.failed_count,
                record.diagnostic,
            ),
        )
        return inserted_id(cursor)

    def finish_adoption_run(
        self,
        run_id: int,
        *,
        status: str,
        finished_at: str,
        completed_count: int | None = None,
        failed_count: int | None = None,
        diagnostic: str | None = None,
    ) -> None:
        from media_catalog.records import validate_adoption_state

        validate_adoption_state(status)
        if completed_count is not None and completed_count < 0:
            raise ValueError("completed count must not be negative")
        if failed_count is not None and failed_count < 0:
            raise ValueError("failed count must not be negative")
        self.connection.execute(
            """UPDATE adoption_runs SET status = ?, finished_at = ?,
                   completed_count = COALESCE(?, completed_count),
                   failed_count = COALESCE(?, failed_count), diagnostic = ?
               WHERE adoption_run_id = ?""",
            (status, finished_at, completed_count, failed_count, diagnostic, run_id),
        )

    def record_adoption_item(self, record: AdoptionItemRecord) -> int:
        created_at = record.created_at or now()
        updated_at = record.updated_at or created_at
        self.connection.execute(
            """INSERT INTO adoption_items (
                   adoption_run_id, item_key, media_occurrence_id, occurrence_source_id, asset_id,
                   outcome, detected_mime_type, detected_width, detected_height,
                   detected_frame_count, byte_size, sha256, md5, diagnostic, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(adoption_run_id, item_key) DO UPDATE SET
                   media_occurrence_id = COALESCE(excluded.media_occurrence_id,
                                                  adoption_items.media_occurrence_id),
                   occurrence_source_id = COALESCE(excluded.occurrence_source_id,
                                                    adoption_items.occurrence_source_id),
                   asset_id = COALESCE(excluded.asset_id, adoption_items.asset_id),
                   outcome = excluded.outcome,
                   detected_mime_type = COALESCE(excluded.detected_mime_type,
                                                 adoption_items.detected_mime_type),
                   detected_width = COALESCE(
                       excluded.detected_width, adoption_items.detected_width),
                   detected_height = COALESCE(
                       excluded.detected_height, adoption_items.detected_height),
                   detected_frame_count = COALESCE(excluded.detected_frame_count,
                                                   adoption_items.detected_frame_count),
                   byte_size = COALESCE(excluded.byte_size, adoption_items.byte_size),
                   sha256 = COALESCE(excluded.sha256, adoption_items.sha256),
                   md5 = COALESCE(excluded.md5, adoption_items.md5),
                   diagnostic = excluded.diagnostic, updated_at = excluded.updated_at""",
            (
                record.adoption_run_id,
                record.item_key,
                record.media_occurrence_id,
                record.occurrence_source_id,
                record.asset_id,
                record.outcome,
                record.detected_mime_type,
                record.detected_width,
                record.detected_height,
                record.detected_frame_count,
                record.byte_size,
                record.sha256,
                record.md5,
                record.diagnostic,
                created_at,
                updated_at,
            ),
        )
        return int(
            self.connection.execute(
                """SELECT adoption_item_id FROM adoption_items
                   WHERE adoption_run_id = ? AND item_key = ?""",
                (record.adoption_run_id, record.item_key),
            ).fetchone()[0]
        )

    def record_adoption_attempt(self, record: AdoptionAttemptRecord) -> int:
        self.connection.execute(
            """INSERT INTO adoption_attempts (
                   adoption_item_id, attempt_number, outcome, sha256, md5, byte_size,
                   detected_mime_type, detected_width, detected_height, detected_frame_count,
                   diagnostic, started_at, finished_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(adoption_item_id, attempt_number) DO UPDATE SET
                   outcome = excluded.outcome, sha256 = excluded.sha256, md5 = excluded.md5,
                   byte_size = excluded.byte_size, detected_mime_type = excluded.detected_mime_type,
                   detected_width = excluded.detected_width,
                   detected_height = excluded.detected_height,
                   detected_frame_count = excluded.detected_frame_count,
                   diagnostic = excluded.diagnostic, finished_at = excluded.finished_at""",
            (
                record.adoption_item_id,
                record.attempt_number,
                record.outcome,
                record.sha256,
                record.md5,
                record.byte_size,
                record.detected_mime_type,
                record.detected_width,
                record.detected_height,
                record.detected_frame_count,
                record.diagnostic,
                record.started_at,
                record.finished_at,
            ),
        )
        return int(
            self.connection.execute(
                """SELECT adoption_attempt_id FROM adoption_attempts
                   WHERE adoption_item_id = ? AND attempt_number = ?""",
                (record.adoption_item_id, record.attempt_number),
            ).fetchone()[0]
        )
