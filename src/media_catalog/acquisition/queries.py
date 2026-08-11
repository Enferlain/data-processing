from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.records import validate_acquisition_run_status

DatabaseSource = CatalogDatabase | Path | str


def _connection(database: DatabaseSource) -> sqlite3.Connection:
    if isinstance(database, CatalogDatabase):
        snapshot = sqlite3.connect(":memory:")
        snapshot.row_factory = sqlite3.Row
        database.connection.backup(snapshot)
        snapshot.execute("PRAGMA query_only = ON")
        return snapshot
    return CatalogDatabase.open_read_only(Path(database)).connection


def _rows_on(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[object, ...] = (),
) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, parameters)]


def _one_on(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[object, ...],
) -> dict[str, Any] | None:
    row = connection.execute(sql, parameters).fetchone()
    return None if row is None else dict(row)


def list_acquisition_plans(
    database: DatabaseSource,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    connection = _connection(database)
    try:
        return _rows_on(
            connection,
            """SELECT acquisition_plan_id, plan_version, selection_digest,
                      requested_count, eligible_count, satisfied_count, excluded_count,
                      created_at
               FROM media_acquisition_plans
               ORDER BY acquisition_plan_id DESC LIMIT ?""",
            (limit,),
        )
    finally:
        connection.close()


def get_acquisition_plan(
    database: DatabaseSource,
    acquisition_plan_id: int,
) -> dict[str, Any] | None:
    if acquisition_plan_id <= 0:
        raise ValueError("acquisition plan id must be positive")
    connection = _connection(database)
    try:
        plan = _one_on(
            connection,
            """SELECT acquisition_plan_id, plan_version, selection_digest,
                      requested_count, eligible_count, satisfied_count, excluded_count,
                      created_at
               FROM media_acquisition_plans WHERE acquisition_plan_id = ?""",
            (acquisition_plan_id,),
        )
        if plan is None:
            return None
        plan["items"] = _rows_on(
            connection,
            """SELECT api.acquisition_plan_item_id, api.item_key,
                      api.media_occurrence_id, api.variant_key, api.material_digest,
                      api.request_policy_key, api.request_policy_version,
                      api.source_raw_observation_id, api.eligibility, api.exclusion_reason,
                      api.satisfied_asset_id, api.declared_sha256, api.declared_md5,
                      api.declared_file_size, api.declared_mime_type,
                      api.declared_width, api.declared_height, api.created_at,
                      platform.platform_key AS platform, post.native_post_id,
                      mo.source_key, mo.media_index, mo.media_type
               FROM media_acquisition_plan_items api
               JOIN media_occurrences mo USING(media_occurrence_id)
               JOIN posts post USING(post_id)
               JOIN platforms platform USING(platform_id)
               WHERE api.acquisition_plan_id = ?
               ORDER BY api.acquisition_plan_item_id""",
            (acquisition_plan_id,),
        )
        return plan
    finally:
        connection.close()


def list_acquisition_runs(
    database: DatabaseSource,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if status is not None:
        validate_acquisition_run_status(status)
    connection = _connection(database)
    try:
        where = "WHERE ar.status = ?" if status is not None else ""
        parameters: tuple[object, ...] = (status, limit) if status is not None else (limit,)
        return _rows_on(
            connection,
            f"""SELECT ar.acquisition_run_id, ar.acquisition_plan_id,
                       ar.managed_root_id, mr.display_label AS managed_root,
                       ar.resumed_from_run_id, ar.status, ar.termination_outcome,
                       ar.max_items, ar.max_item_bytes, ar.max_total_bytes,
                       ar.max_attempts_per_item, ar.max_seconds, ar.max_redirects,
                       ar.max_quarantine_bytes, ar.concurrency, ar.planned_count,
                       ar.completed_count, ar.failed_count, ar.deferred_count,
                       ar.received_bytes, ar.quarantined_bytes, ar.diagnostic,
                       ar.started_at, ar.finished_at
                FROM media_acquisition_runs ar
                JOIN managed_roots mr USING(managed_root_id)
                {where}
                ORDER BY ar.acquisition_run_id DESC LIMIT ?""",
            parameters,
        )
    finally:
        connection.close()


def get_acquisition_run(
    database: DatabaseSource,
    acquisition_run_id: int,
) -> dict[str, Any] | None:
    if acquisition_run_id <= 0:
        raise ValueError("acquisition run id must be positive")
    connection = _connection(database)
    try:
        run = _one_on(
            connection,
            """SELECT ar.acquisition_run_id, ar.acquisition_plan_id,
                      ar.managed_root_id, mr.display_label AS managed_root,
                      ar.resumed_from_run_id, ar.status, ar.termination_outcome,
                      ar.max_items, ar.max_item_bytes, ar.max_total_bytes,
                      ar.max_attempts_per_item, ar.max_seconds, ar.max_redirects,
                      ar.max_quarantine_bytes, ar.concurrency, ar.planned_count,
                      ar.completed_count, ar.failed_count, ar.deferred_count,
                      ar.received_bytes, ar.quarantined_bytes, ar.diagnostic,
                      ar.started_at, ar.finished_at
               FROM media_acquisition_runs ar
               JOIN managed_roots mr USING(managed_root_id)
               WHERE ar.acquisition_run_id = ?""",
            (acquisition_run_id,),
        )
        if run is None:
            return None
        items = _rows_on(
            connection,
            """SELECT ari.acquisition_run_item_id, ari.acquisition_plan_item_id,
                      api.item_key, api.media_occurrence_id, api.variant_key,
                      api.request_policy_key, api.request_policy_version,
                      ari.state, ari.outcome, ari.retryable, ari.attempt_count,
                      ari.received_bytes, ari.asset_id, ari.sha256, ari.md5,
                      ari.diagnostic, ari.created_at, ari.updated_at
               FROM media_acquisition_run_items ari
               JOIN media_acquisition_plan_items api USING(acquisition_plan_item_id)
               WHERE ari.acquisition_run_id = ?
               ORDER BY ari.acquisition_run_item_id""",
            (acquisition_run_id,),
        )
        for item in items:
            run_item_id = item["acquisition_run_item_id"]
            item["attempts"] = _rows_on(
                connection,
                """SELECT acquisition_attempt_id, attempt_number, state, outcome,
                          retryable, request_identity, request_policy_key,
                          request_policy_version, status_code, redirect_count,
                          received_bytes, response_size, retry_after, diagnostic,
                          started_at, finished_at
                   FROM media_acquisition_attempts
                   WHERE acquisition_run_item_id = ? ORDER BY attempt_number""",
                (run_item_id,),
            )
            item["partials"] = _rows_on(
                connection,
                """SELECT acquisition_partial_id, managed_root_id, byte_count, state,
                          created_at, updated_at
                   FROM media_acquisition_partials
                   WHERE acquisition_run_item_id = ? ORDER BY acquisition_partial_id""",
                (run_item_id,),
            )
            item["verifications"] = _rows_on(
                connection,
                """SELECT acquisition_verification_id, claim_kind, declared_value,
                          verified_value, comparison_result, source_raw_observation_id,
                          created_at
                   FROM media_acquisition_verifications
                   WHERE acquisition_run_item_id = ?
                   ORDER BY acquisition_verification_id""",
                (run_item_id,),
            )
            item["quarantine"] = _rows_on(
                connection,
                """SELECT acquisition_quarantine_id, acquisition_attempt_id,
                          managed_root_id, reason, byte_size, sha256, md5, state, created_at
                   FROM media_acquisition_quarantine
                   WHERE acquisition_run_item_id = ? ORDER BY acquisition_quarantine_id""",
                (run_item_id,),
            )
        run["items"] = items
        return run
    finally:
        connection.close()


def list_retryable_acquisition_items(
    database: DatabaseSource,
    *,
    acquisition_run_id: int | None = None,
) -> list[dict[str, Any]]:
    if acquisition_run_id is not None and acquisition_run_id <= 0:
        raise ValueError("acquisition run id must be positive")
    connection = _connection(database)
    try:
        where = "AND ari.acquisition_run_id = ?" if acquisition_run_id is not None else ""
        parameters: tuple[object, ...] = (
            (acquisition_run_id,) if acquisition_run_id is not None else ()
        )
        return _rows_on(
            connection,
            f"""SELECT ari.acquisition_run_item_id, ari.acquisition_run_id,
                       ari.acquisition_plan_item_id, api.item_key,
                       api.media_occurrence_id, api.variant_key, ari.state, ari.outcome,
                       ari.attempt_count, ari.received_bytes, ari.updated_at
                FROM media_acquisition_run_items ari
                JOIN media_acquisition_plan_items api USING(acquisition_plan_item_id)
                WHERE ari.retryable = 1
                  AND ari.state IN ('failed', 'interrupted', 'deferred')
                  {where}
                ORDER BY ari.acquisition_run_id, ari.acquisition_run_item_id""",
            parameters,
        )
    finally:
        connection.close()


class AcquisitionQueryService:
    def __init__(self, database: DatabaseSource) -> None:
        self.database = database

    def plans(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return list_acquisition_plans(self.database, limit=limit)

    def plan(self, acquisition_plan_id: int) -> dict[str, Any] | None:
        return get_acquisition_plan(self.database, acquisition_plan_id)

    def runs(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return list_acquisition_runs(self.database, status=status, limit=limit)

    def run(self, acquisition_run_id: int) -> dict[str, Any] | None:
        return get_acquisition_run(self.database, acquisition_run_id)

    def retryable_items(
        self,
        *,
        acquisition_run_id: int | None = None,
    ) -> list[dict[str, Any]]:
        return list_retryable_acquisition_items(
            self.database,
            acquisition_run_id=acquisition_run_id,
        )
