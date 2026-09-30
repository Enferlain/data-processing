from __future__ import annotations

from media_catalog.database import CatalogDatabase
from media_catalog.persistence.support import caller_connection, inserted_id
from media_catalog.records import (
    AcquisitionAttemptRecord,
    AcquisitionPartialRecord,
    AcquisitionPlanItemRecord,
    AcquisitionPlanRecord,
    AcquisitionQuarantineRecord,
    AcquisitionRunItemRecord,
    AcquisitionRunRecord,
    AcquisitionVerificationRecord,
    normalize_timestamp,
    validate_acquisition_run_outcome,
    validate_acquisition_run_status,
)


class AcquisitionWrites:
    def __init__(self, database: CatalogDatabase) -> None:
        self.connection = caller_connection(database)

    def create_acquisition_plan(self, record: AcquisitionPlanRecord) -> int:
        cursor = self.connection.execute(
            """INSERT INTO media_acquisition_plans (
                   plan_version, selection_digest, requested_count, eligible_count,
                   satisfied_count, excluded_count, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                record.plan_version,
                record.selection_digest,
                record.requested_count,
                record.eligible_count,
                record.satisfied_count,
                record.excluded_count,
                record.created_at,
            ),
        )
        return inserted_id(cursor)

    def add_acquisition_plan_item(self, record: AcquisitionPlanItemRecord) -> int:
        values = (
            record.acquisition_plan_id,
            record.item_key,
            record.media_occurrence_id,
            record.variant_key,
            record.material_digest,
            record.request_policy_key,
            record.request_policy_version,
            record.source_raw_observation_id,
            record.eligibility,
            record.exclusion_reason,
            record.satisfied_asset_id,
            record.declared_sha256,
            record.declared_md5,
            record.declared_file_size,
            record.declared_mime_type,
            record.declared_width,
            record.declared_height,
            record.created_at,
        )
        self.connection.execute(
            """INSERT OR IGNORE INTO media_acquisition_plan_items (
                   acquisition_plan_id, item_key, media_occurrence_id, variant_key,
                   material_digest, request_policy_key, request_policy_version,
                   source_raw_observation_id, eligibility, exclusion_reason, satisfied_asset_id,
                   declared_sha256, declared_md5, declared_file_size, declared_mime_type,
                   declared_width, declared_height, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )
        row = self.connection.execute(
            """SELECT * FROM media_acquisition_plan_items
               WHERE acquisition_plan_id = ? AND item_key = ?""",
            (record.acquisition_plan_id, record.item_key),
        ).fetchone()
        if row is None:
            raise ValueError("acquisition plan item conflicts with another variant selection")
        columns = (
            "acquisition_plan_id",
            "item_key",
            "media_occurrence_id",
            "variant_key",
            "material_digest",
            "request_policy_key",
            "request_policy_version",
            "source_raw_observation_id",
            "eligibility",
            "exclusion_reason",
            "satisfied_asset_id",
            "declared_sha256",
            "declared_md5",
            "declared_file_size",
            "declared_mime_type",
            "declared_width",
            "declared_height",
            "created_at",
        )
        if tuple(row[column] for column in columns) != values:
            raise ValueError("acquisition plan item is immutable and differs from existing data")
        return int(row["acquisition_plan_item_id"])

    def begin_acquisition_run(self, record: AcquisitionRunRecord) -> int:
        limits = record.limits
        cursor = self.connection.execute(
            """INSERT INTO media_acquisition_runs (
                   acquisition_plan_id, managed_root_id, resumed_from_run_id, max_items,
                   max_item_bytes, max_total_bytes, max_attempts_per_item, max_seconds,
                   max_redirects, max_quarantine_bytes, concurrency, planned_count, started_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.acquisition_plan_id,
                record.managed_root_id,
                record.resumed_from_run_id,
                limits.max_items,
                limits.max_item_bytes,
                limits.max_total_bytes,
                limits.max_attempts_per_item,
                limits.max_seconds,
                limits.max_redirects,
                limits.max_quarantine_bytes,
                limits.concurrency,
                record.planned_count,
                record.started_at,
            ),
        )
        return inserted_id(cursor)

    def finish_acquisition_run(
        self,
        acquisition_run_id: int,
        *,
        status: str,
        outcome: str,
        completed_count: int,
        failed_count: int,
        deferred_count: int,
        received_bytes: int,
        quarantined_bytes: int,
        finished_at: str,
        diagnostic: str | None = None,
    ) -> None:
        validate_acquisition_run_status(status)
        validate_acquisition_run_outcome(outcome)
        if status == "running":
            raise ValueError("finished acquisition run cannot remain running")
        for name, value in (
            ("completed count", completed_count),
            ("failed count", failed_count),
            ("deferred count", deferred_count),
            ("received bytes", received_bytes),
            ("quarantined bytes", quarantined_bytes),
        ):
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        finished_at = normalize_timestamp(finished_at)
        if diagnostic is not None:
            diagnostic = diagnostic[:1000]
        values = (
            status,
            outcome,
            completed_count,
            failed_count,
            deferred_count,
            received_bytes,
            quarantined_bytes,
            diagnostic,
            finished_at,
        )
        cursor = self.connection.execute(
            """UPDATE media_acquisition_runs SET
                   status = ?, termination_outcome = ?, completed_count = ?, failed_count = ?,
                   deferred_count = ?, received_bytes = ?, quarantined_bytes = ?,
                   diagnostic = ?, finished_at = ?
               WHERE acquisition_run_id = ? AND status = 'running'""",
            (*values, acquisition_run_id),
        )
        if cursor.rowcount == 1:
            return
        row = self.connection.execute(
            """SELECT status, termination_outcome, completed_count, failed_count,
                      deferred_count, received_bytes, quarantined_bytes, diagnostic, finished_at
               FROM media_acquisition_runs WHERE acquisition_run_id = ?""",
            (acquisition_run_id,),
        ).fetchone()
        if row is None or tuple(row) != values:
            raise ValueError("acquisition run is missing or already finished differently")

    def record_acquisition_run_item(self, record: AcquisitionRunItemRecord) -> int:
        row = self.connection.execute(
            """SELECT * FROM media_acquisition_run_items
               WHERE acquisition_run_id = ? AND acquisition_plan_item_id = ?""",
            (record.acquisition_run_id, record.acquisition_plan_item_id),
        ).fetchone()
        values = (
            record.state,
            record.outcome,
            int(record.retryable),
            record.attempt_count,
            record.received_bytes,
            record.asset_id,
            record.sha256,
            record.md5,
            record.diagnostic,
            record.updated_at,
        )
        if row is None:
            cursor = self.connection.execute(
                """INSERT INTO media_acquisition_run_items (
                       acquisition_run_id, acquisition_plan_item_id, state, outcome, retryable,
                       attempt_count, received_bytes, asset_id, sha256, md5, diagnostic,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.acquisition_run_id,
                    record.acquisition_plan_item_id,
                    *values[:-1],
                    record.created_at,
                    record.updated_at,
                ),
            )
            return inserted_id(cursor)
        terminal = row["state"] not in {"pending", "running"}
        existing = tuple(
            row[column]
            for column in (
                "state",
                "outcome",
                "retryable",
                "attempt_count",
                "received_bytes",
                "asset_id",
                "sha256",
                "md5",
                "diagnostic",
                "updated_at",
            )
        )
        if terminal:
            if existing != values:
                raise ValueError("terminal acquisition run item is immutable")
            return int(row["acquisition_run_item_id"])
        self.connection.execute(
            """UPDATE media_acquisition_run_items SET
                   state = ?, outcome = ?, retryable = ?, attempt_count = ?, received_bytes = ?,
                   asset_id = ?, sha256 = ?, md5 = ?, diagnostic = ?, updated_at = ?
               WHERE acquisition_run_item_id = ?""",
            (*values, row["acquisition_run_item_id"]),
        )
        return int(row["acquisition_run_item_id"])

    def record_acquisition_attempt(self, record: AcquisitionAttemptRecord) -> int:
        row = self.connection.execute(
            """SELECT * FROM media_acquisition_attempts
               WHERE acquisition_run_item_id = ? AND attempt_number = ?""",
            (record.acquisition_run_item_id, record.attempt_number),
        ).fetchone()
        values = (
            record.state,
            record.outcome,
            int(record.retryable),
            record.request_identity,
            record.request_policy_key,
            record.request_policy_version,
            record.status_code,
            record.redirect_count,
            record.response_etag,
            record.received_bytes,
            record.response_size,
            record.retry_after,
            record.diagnostic,
            record.started_at,
            record.finished_at,
        )
        if row is None:
            cursor = self.connection.execute(
                """INSERT INTO media_acquisition_attempts (
                       acquisition_run_item_id, attempt_number, state, outcome, retryable,
                       request_identity, request_policy_key, request_policy_version, status_code,
                       redirect_count, response_etag, received_bytes, response_size, retry_after,
                       diagnostic, started_at, finished_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record.acquisition_run_item_id, record.attempt_number, *values),
            )
            return inserted_id(cursor)
        columns = (
            "state",
            "outcome",
            "retryable",
            "request_identity",
            "request_policy_key",
            "request_policy_version",
            "status_code",
            "redirect_count",
            "response_etag",
            "received_bytes",
            "response_size",
            "retry_after",
            "diagnostic",
            "started_at",
            "finished_at",
        )
        existing = tuple(row[column] for column in columns)
        if row["state"] != "running":
            if existing != values:
                raise ValueError("terminal acquisition attempt is immutable")
            return int(row["acquisition_attempt_id"])
        if record.state == "running" and existing != values:
            raise ValueError("running acquisition attempt can only advance to a terminal state")
        if existing != values:
            self.connection.execute(
                """UPDATE media_acquisition_attempts SET
                       state = ?, outcome = ?, retryable = ?, request_identity = ?,
                       request_policy_key = ?, request_policy_version = ?, status_code = ?,
                       redirect_count = ?, response_etag = ?, received_bytes = ?,
                       response_size = ?, retry_after = ?, diagnostic = ?, started_at = ?,
                       finished_at = ?
                   WHERE acquisition_attempt_id = ? AND state = 'running'""",
                (*values, row["acquisition_attempt_id"]),
            )
        return int(row["acquisition_attempt_id"])

    def save_acquisition_partial(self, record: AcquisitionPartialRecord) -> int:
        if record.acquisition_partial_id is not None:
            cursor = self.connection.execute(
                """UPDATE media_acquisition_partials SET byte_count = ?, prefix_sha256 = ?,
                       prefix_md5 = ?, strong_etag = ?, state = ?, updated_at = ?
                   WHERE acquisition_partial_id = ? AND acquisition_run_item_id = ?
                     AND managed_root_id = ? AND managed_root_identity = ?
                     AND staging_device = ? AND staging_inode = ?
                     AND staging_name = ? AND request_identity = ?""",
                (
                    record.byte_count,
                    record.prefix_sha256,
                    record.prefix_md5,
                    record.strong_etag,
                    record.state,
                    record.updated_at,
                    record.acquisition_partial_id,
                    record.acquisition_run_item_id,
                    record.managed_root_id,
                    record.managed_root_identity,
                    record.staging_device,
                    record.staging_inode,
                    record.staging_name,
                    record.request_identity,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("acquisition partial identity is missing or changed")
            return record.acquisition_partial_id
        cursor = self.connection.execute(
            """INSERT INTO media_acquisition_partials (
                   acquisition_run_item_id, managed_root_id, managed_root_identity,
                   staging_device, staging_inode, staging_name, request_identity,
                   strong_etag, byte_count, prefix_sha256, prefix_md5, state,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.acquisition_run_item_id,
                record.managed_root_id,
                record.managed_root_identity,
                record.staging_device,
                record.staging_inode,
                record.staging_name,
                record.request_identity,
                record.strong_etag,
                record.byte_count,
                record.prefix_sha256,
                record.prefix_md5,
                record.state,
                record.created_at,
                record.updated_at,
            ),
        )
        return inserted_id(cursor)

    def record_acquisition_verification(self, record: AcquisitionVerificationRecord) -> int:
        self.connection.execute(
            """INSERT OR IGNORE INTO media_acquisition_verifications (
                   acquisition_run_item_id, claim_kind, declared_value, verified_value,
                   comparison_result, source_raw_observation_id, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                record.acquisition_run_item_id,
                record.claim_kind,
                record.declared_value,
                record.verified_value,
                record.comparison_result,
                record.source_raw_observation_id,
                record.created_at,
            ),
        )
        row = self.connection.execute(
            """SELECT * FROM media_acquisition_verifications
               WHERE acquisition_run_item_id = ? AND claim_kind = ?""",
            (record.acquisition_run_item_id, record.claim_kind),
        ).fetchone()
        expected = (
            record.declared_value,
            record.verified_value,
            record.comparison_result,
            record.source_raw_observation_id,
            record.created_at,
        )
        columns = (
            "declared_value",
            "verified_value",
            "comparison_result",
            "source_raw_observation_id",
            "created_at",
        )
        if row is None or tuple(row[column] for column in columns) != expected:
            raise ValueError("acquisition verification already exists with different evidence")
        return int(row["acquisition_verification_id"])

    def record_acquisition_quarantine(self, record: AcquisitionQuarantineRecord) -> int:
        self.connection.execute(
            """INSERT OR IGNORE INTO media_acquisition_quarantine (
                   acquisition_run_item_id, acquisition_attempt_id, managed_root_id,
                   quarantine_name, reason, byte_size, sha256, md5, state, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.acquisition_run_item_id,
                record.acquisition_attempt_id,
                record.managed_root_id,
                record.quarantine_name,
                record.reason,
                record.byte_size,
                record.sha256,
                record.md5,
                record.state,
                record.created_at,
            ),
        )
        row = self.connection.execute(
            """SELECT * FROM media_acquisition_quarantine
               WHERE managed_root_id = ? AND quarantine_name = ?""",
            (record.managed_root_id, record.quarantine_name),
        ).fetchone()
        expected = (
            record.acquisition_run_item_id,
            record.acquisition_attempt_id,
            record.reason,
            record.byte_size,
            record.sha256,
            record.md5,
            record.state,
            record.created_at,
        )
        columns = (
            "acquisition_run_item_id",
            "acquisition_attempt_id",
            "reason",
            "byte_size",
            "sha256",
            "md5",
            "state",
            "created_at",
        )
        if row is None or tuple(row[column] for column in columns) != expected:
            raise ValueError("quarantine entry already exists with different evidence")
        return int(row["acquisition_quarantine_id"])
