from __future__ import annotations

from media_catalog.database import CatalogDatabase
from media_catalog.persistence.support import caller_connection, inserted_id, platform_id
from media_catalog.records import (
    CandidateLookupCheckpointRecord,
    CandidateLookupRequestRecord,
    CandidateLookupResultRecord,
    CandidateLookupRunRecord,
    normalize_timestamp,
    validate_lookup_budget_boundary,
    validate_lookup_outcome,
    validate_lookup_run_status,
)


class LookupWrites:
    def __init__(self, database: CatalogDatabase) -> None:
        self.connection = caller_connection(database)

    def begin_candidate_lookup(self, record: CandidateLookupRunRecord) -> int:
        cursor = self.connection.execute(
            """INSERT INTO candidate_lookup_runs (
                   platform_id, instance_host, strategy, strategy_version, adapter_version,
                   schema_version, seed_account_id, seed_post_id, seed_revision, plan_digest,
                   query_kind, material_digest, private_query_json, predecessor_run_id,
                   request_limit, page_limit, result_limit, time_limit_seconds, started_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                platform_id(self.connection, record.platform),
                record.instance_host,
                record.strategy,
                record.strategy_version,
                record.adapter_version,
                record.schema_version,
                record.seed_account_id,
                record.seed_post_id,
                record.seed_revision,
                record.plan_digest,
                record.query_kind,
                record.material_digest,
                record.private_query_json,
                record.predecessor_run_id,
                record.request_limit,
                record.page_limit,
                record.result_limit,
                record.time_limit_seconds,
                record.started_at,
            ),
        )
        return inserted_id(cursor)

    def finish_candidate_lookup(
        self,
        run_id: int,
        *,
        status: str,
        outcome: str,
        request_count: int,
        page_count: int,
        result_count: int,
        finished_at: str,
        budget_boundary: str | None = None,
        retry_after: str | None = None,
        diagnostic: str | None = None,
    ) -> None:
        validate_lookup_run_status(status)
        validate_lookup_outcome(outcome)
        if status == "running":
            raise ValueError("finished lookup run cannot remain running")
        if budget_boundary is not None:
            validate_lookup_budget_boundary(budget_boundary)
        for value, label in (
            (request_count, "request count"),
            (page_count, "page count"),
            (result_count, "result count"),
        ):
            if value < 0:
                raise ValueError(f"{label} must not be negative")
        finished_at = normalize_timestamp(finished_at)
        retry_after = normalize_timestamp(retry_after) if retry_after else None
        diagnostic = diagnostic[:1000] if diagnostic else None
        values = (
            status,
            outcome,
            budget_boundary,
            request_count,
            page_count,
            result_count,
            retry_after,
            diagnostic,
            finished_at,
        )
        cursor = self.connection.execute(
            """UPDATE candidate_lookup_runs SET status = ?, termination_outcome = ?,
                   budget_boundary = ?, request_count = ?, page_count = ?, result_count = ?,
                   retry_after = ?, diagnostic_summary = ?, finished_at = ?
               WHERE candidate_lookup_run_id = ? AND status = 'running'""",
            (*values, run_id),
        )
        if cursor.rowcount == 1:
            return
        row = self.connection.execute(
            """SELECT status, termination_outcome, budget_boundary, request_count, page_count,
                      result_count, retry_after, diagnostic_summary, finished_at
               FROM candidate_lookup_runs WHERE candidate_lookup_run_id = ?""",
            (run_id,),
        ).fetchone()
        if row is None or tuple(row) != values:
            raise ValueError("lookup run is missing or already finished differently")

    def record_candidate_lookup_request(self, record: CandidateLookupRequestRecord) -> int:
        row = self.connection.execute(
            """SELECT * FROM candidate_lookup_requests
               WHERE candidate_lookup_run_id = ? AND attempt_number = ?""",
            (record.candidate_lookup_run_id, record.attempt_number),
        ).fetchone()
        columns = (
            "request_identity",
            "state",
            "outcome",
            "status_code",
            "retry_after",
            "response_size",
            "raw_observation_id",
            "candidate_lookup_checkpoint_id",
            "started_at",
            "observed_at",
            "finished_at",
        )
        values = tuple(getattr(record, name) for name in columns)
        if row is None:
            cursor = self.connection.execute(
                """INSERT INTO candidate_lookup_requests (
                       candidate_lookup_run_id, attempt_number, request_identity, state, outcome,
                       status_code, retry_after, response_size, raw_observation_id,
                       candidate_lookup_checkpoint_id, started_at, observed_at, finished_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record.candidate_lookup_run_id, record.attempt_number, *values),
            )
            return inserted_id(cursor)
        existing = tuple(row[name] for name in columns)
        if row["state"] != "running":
            if existing != values:
                raise ValueError("terminal lookup request is immutable")
            return int(row["candidate_lookup_request_id"])
        if record.state == "running" and existing != values:
            raise ValueError("running lookup request can only become terminal")
        if existing != values:
            self.connection.execute(
                """UPDATE candidate_lookup_requests SET request_identity = ?, state = ?,
                       outcome = ?, status_code = ?, retry_after = ?, response_size = ?,
                       raw_observation_id = ?, candidate_lookup_checkpoint_id = ?, started_at = ?,
                       observed_at = ?, finished_at = ?
                   WHERE candidate_lookup_request_id = ? AND state = 'running'""",
                (*values, row["candidate_lookup_request_id"]),
            )
        return int(row["candidate_lookup_request_id"])

    def save_candidate_lookup_checkpoint(self, record: CandidateLookupCheckpointRecord) -> int:
        self.connection.execute(
            """INSERT INTO candidate_lookup_checkpoints (
                   candidate_lookup_run_id, continuation_adapter, continuation_version,
                   continuation_json, last_page_identity, page_count, result_count, committed_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(candidate_lookup_run_id) DO UPDATE SET
                   continuation_adapter = excluded.continuation_adapter,
                   continuation_version = excluded.continuation_version,
                   continuation_json = excluded.continuation_json,
                   last_page_identity = excluded.last_page_identity,
                   page_count = excluded.page_count, result_count = excluded.result_count,
                   committed_at = excluded.committed_at""",
            (
                record.candidate_lookup_run_id,
                record.continuation_adapter,
                record.continuation_version,
                record.continuation_json,
                record.last_page_identity,
                record.page_count,
                record.result_count,
                record.committed_at,
            ),
        )
        return int(
            self.connection.execute(
                "SELECT candidate_lookup_checkpoint_id FROM candidate_lookup_checkpoints "
                "WHERE candidate_lookup_run_id = ?",
                (record.candidate_lookup_run_id,),
            ).fetchone()[0]
        )

    def record_candidate_lookup_result(self, record: CandidateLookupResultRecord) -> int:
        columns = (
            "result_kind",
            "result_digest",
            "page_number",
            "result_order",
            "normalized_post_id",
            "attribution_entity_id",
            "platform_reference_id",
            "post_candidate_id",
            "account_candidate_id",
            "match_evidence_id",
            "raw_observation_id",
            "normalized_name",
            "match_mode",
            "explanation",
            "observed_at",
        )
        values = tuple(getattr(record, name) for name in columns)
        self.connection.execute(
            """INSERT INTO candidate_lookup_results (
                   candidate_lookup_run_id, result_kind, result_digest, page_number, result_order,
                   normalized_post_id, attribution_entity_id, platform_reference_id,
                   post_candidate_id, account_candidate_id, match_evidence_id,
                   raw_observation_id, normalized_name, match_mode, explanation, observed_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(candidate_lookup_run_id, result_digest) DO NOTHING""",
            (record.candidate_lookup_run_id, *values),
        )
        row = self.connection.execute(
            """SELECT * FROM candidate_lookup_results
               WHERE candidate_lookup_run_id = ? AND result_digest = ?""",
            (record.candidate_lookup_run_id, record.result_digest),
        ).fetchone()
        stable_columns = (
            "result_kind",
            "normalized_post_id",
            "attribution_entity_id",
            "platform_reference_id",
            "post_candidate_id",
            "account_candidate_id",
            "match_evidence_id",
            "normalized_name",
            "match_mode",
        )
        if row is None or tuple(row[name] for name in stable_columns) != tuple(
            getattr(record, name) for name in stable_columns
        ):
            raise ValueError("lookup result already exists with a different target")
        return int(row["candidate_lookup_result_id"])
