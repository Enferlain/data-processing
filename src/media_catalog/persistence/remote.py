from __future__ import annotations

import hashlib

from media_catalog.database import CatalogDatabase
from media_catalog.persistence.support import caller_connection, inserted_id, platform_id
from media_catalog.records import (
    RawRecord,
    RemoteCheckpointRecord,
    RemoteRequestRecord,
    RemoteRunRecord,
    normalize_timestamp,
    validate_budget_boundary,
    validate_remote_outcome,
    validate_remote_run_status,
)


class RemoteWrites:
    def __init__(self, database: CatalogDatabase) -> None:
        self.connection = caller_connection(database)

    def store_raw(
        self,
        record: RawRecord,
        *,
        import_run_id: int | None = None,
        remote_run_id: int | None = None,
        remote_request_id: int | None = None,
    ) -> int:
        if import_run_id is not None and remote_run_id is not None:
            raise ValueError("raw observation cannot belong to import and remote runs")
        if (remote_run_id is None) != (remote_request_id is None):
            raise ValueError("remote raw observation requires both run and request ids")
        record_platform_id = (
            platform_id(self.connection, record.platform) if record.platform is not None else None
        )
        if remote_request_id is not None:
            request = self.connection.execute(
                """SELECT remote_run_id, transport_key, transport_version
                   FROM remote_requests WHERE remote_request_id = ?""",
                (remote_request_id,),
            ).fetchone()
            if request is None or int(request[0]) != remote_run_id:
                raise ValueError("remote request does not belong to the supplied run")
            if (request["transport_key"], request["transport_version"]) != (
                record.transport_key,
                record.transport_version,
            ):
                raise ValueError("raw observation transport identity does not match its request")
        digest = hashlib.sha256(record.payload).hexdigest()
        self.connection.execute(
            """INSERT INTO raw_payloads (sha256, media_type, payload, byte_size)
               VALUES (?, ?, ?, ?) ON CONFLICT(sha256) DO NOTHING""",
            (digest, record.media_type, record.payload, len(record.payload)),
        )
        payload_id = self.connection.execute(
            "SELECT raw_payload_id FROM raw_payloads WHERE sha256 = ?", (digest,)
        ).fetchone()[0]
        values = (
            payload_id,
            import_run_id,
            record_platform_id,
            record.object_kind,
            record.native_id,
            record.media_type,
            record.source_schema,
            record.status,
            record.observed_at,
            remote_run_id,
            remote_request_id,
            record.adapter_version,
            record.schema_version,
            record.transport_key,
            record.transport_version,
        )
        if remote_request_id is not None:
            self.connection.execute(
                """INSERT OR IGNORE INTO raw_observations (
                       raw_payload_id, import_run_id, platform_id, object_kind, native_id,
                       media_type, source_schema, status, observed_at, remote_run_id,
                       remote_request_id, adapter_version, schema_version,
                       transport_key, transport_version
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            row = self.connection.execute(
                """SELECT raw_observation_id FROM raw_observations
                   WHERE remote_request_id = ?""",
                (remote_request_id,),
            ).fetchone()
        else:
            self.connection.execute(
                """INSERT INTO raw_observations (
                       raw_payload_id, import_run_id, platform_id, object_kind, native_id,
                       media_type, source_schema, status, observed_at, remote_run_id,
                       remote_request_id, adapter_version, schema_version,
                       transport_key, transport_version
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(import_run_id, object_kind, native_id, raw_payload_id) DO NOTHING""",
                values,
            )
            row = self.connection.execute(
                """SELECT raw_observation_id FROM raw_observations
                   WHERE import_run_id IS ? AND object_kind = ? AND native_id IS ?
                         AND raw_payload_id = ?
                   ORDER BY raw_observation_id LIMIT 1""",
                (import_run_id, record.object_kind, record.native_id, payload_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to store raw observation")
        raw_observation_id = int(row[0])
        if remote_request_id is not None:
            self.connection.execute(
                """UPDATE remote_requests SET raw_observation_id = ?
                   WHERE remote_request_id = ?""",
                (raw_observation_id, remote_request_id),
            )
        return raw_observation_id

    def begin_remote_run(self, record: RemoteRunRecord) -> int:
        record_platform_id = platform_id(self.connection, record.platform)
        cursor = self.connection.execute(
            """INSERT INTO remote_runs (
                   platform_id, instance_host, operation, target, adapter_version,
                   schema_version, resumed_from_run_id, request_budget, page_budget,
                   record_budget, time_budget_seconds, started_at, origin_kind,
                   origin_reference, transport_key, transport_version
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_platform_id,
                record.instance_host,
                record.operation,
                record.target,
                record.adapter_version,
                record.schema_version,
                record.resumed_from_run_id,
                record.request_budget,
                record.page_budget,
                record.record_budget,
                record.time_budget_seconds,
                record.started_at,
                record.origin_kind,
                record.origin_reference,
                record.transport_key,
                record.transport_version,
            ),
        )
        return inserted_id(cursor)

    def finish_remote_run(
        self,
        remote_run_id: int,
        *,
        status: str,
        outcome: str,
        request_count: int,
        page_count: int,
        record_count: int,
        finished_at: str,
        budget_boundary: str | None = None,
        retry_after: str | None = None,
        diagnostic: str | None = None,
    ) -> None:
        validate_remote_run_status(status)
        validate_remote_outcome(outcome)
        if budget_boundary is not None:
            validate_budget_boundary(budget_boundary)
        for name, value in (
            ("request count", request_count),
            ("page count", page_count),
            ("record count", record_count),
        ):
            if value < 0:
                raise ValueError(f"remote {name} must not be negative")
        finished_at = normalize_timestamp(finished_at)
        if retry_after is not None:
            retry_after = normalize_timestamp(retry_after)
        if diagnostic is not None:
            diagnostic = diagnostic[:1000]
        cursor = self.connection.execute(
            """UPDATE remote_runs SET status = ?, termination_outcome = ?,
                   request_count = ?, page_count = ?, record_count = ?, budget_boundary = ?,
                   retry_after = ?, diagnostic_summary = ?, finished_at = ?
               WHERE remote_run_id = ? AND status = 'running'""",
            (
                status,
                outcome,
                request_count,
                page_count,
                record_count,
                budget_boundary,
                retry_after,
                diagnostic,
                finished_at,
                remote_run_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("remote run is missing or already finished")

    def record_remote_request(self, record: RemoteRequestRecord) -> int:
        run = self.connection.execute(
            "SELECT transport_key, transport_version FROM remote_runs WHERE remote_run_id = ?",
            (record.remote_run_id,),
        ).fetchone()
        if run is None:
            raise ValueError("remote run is missing")
        if (run["transport_key"], run["transport_version"]) != (
            record.transport_key,
            record.transport_version,
        ):
            raise ValueError("remote request transport identity does not match its run")
        existing = self.connection.execute(
            """SELECT remote_request_id, request_identity, transport_key, transport_version
               FROM remote_requests
               WHERE remote_run_id = ? AND attempt_number = ?""",
            (record.remote_run_id, record.attempt_number),
        ).fetchone()
        if existing is not None:
            if existing["request_identity"] != record.request_identity:
                raise ValueError("remote attempt number belongs to another request identity")
            if (existing["transport_key"], existing["transport_version"]) != (
                record.transport_key,
                record.transport_version,
            ):
                raise ValueError("remote attempt transport identity does not match")
            return int(existing["remote_request_id"])
        cursor = self.connection.execute(
            """INSERT INTO remote_requests (
                   remote_run_id, attempt_number, request_identity, operation, target,
                   status_code, outcome, retry_after, rate_limit_state,
                   response_adapter_version, response_schema_version, object_kind, native_id,
                   media_type, response_size, request_started_at, response_observed_at,
                   request_finished_at, transport_key, transport_version
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.remote_run_id,
                record.attempt_number,
                record.request_identity,
                record.operation,
                record.target,
                record.status_code,
                record.outcome,
                record.retry_after,
                record.rate_limit_state,
                record.response_adapter_version,
                record.response_schema_version,
                record.object_kind,
                record.native_id,
                record.media_type,
                record.response_size,
                record.request_started_at,
                record.response_observed_at,
                record.request_finished_at,
                record.transport_key,
                record.transport_version,
            ),
        )
        return inserted_id(cursor)

    def save_remote_checkpoint(self, record: RemoteCheckpointRecord) -> int:
        run = self.connection.execute(
            "SELECT transport_key, transport_version FROM remote_runs WHERE remote_run_id = ?",
            (record.remote_run_id,),
        ).fetchone()
        if run is None:
            raise ValueError("remote run is missing")
        if (run["transport_key"], run["transport_version"]) != (
            record.transport_key,
            record.transport_version,
        ):
            raise ValueError("checkpoint transport identity does not match its run")
        self.connection.execute(
            """INSERT INTO remote_checkpoints (
                   remote_run_id, operation, target, continuation_adapter,
                   continuation_version, continuation_json, last_page_identity,
                   page_count, committed_at, transport_key, transport_version
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(remote_run_id, operation, target) DO UPDATE SET
                   continuation_adapter = excluded.continuation_adapter,
                   continuation_version = excluded.continuation_version,
                   continuation_json = excluded.continuation_json,
                   last_page_identity = excluded.last_page_identity,
                   page_count = excluded.page_count,
                   committed_at = excluded.committed_at,
                   transport_key = excluded.transport_key,
                   transport_version = excluded.transport_version""",
            (
                record.remote_run_id,
                record.operation,
                record.target,
                record.continuation_adapter,
                record.continuation_version,
                record.continuation_json,
                record.last_page_identity,
                record.page_count,
                record.committed_at,
                record.transport_key,
                record.transport_version,
            ),
        )
        return int(
            self.connection.execute(
                """SELECT remote_checkpoint_id FROM remote_checkpoints
                   WHERE remote_run_id = ? AND operation = ? AND target = ?""",
                (record.remote_run_id, record.operation, record.target),
            ).fetchone()[0]
        )
