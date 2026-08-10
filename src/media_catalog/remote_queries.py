from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from media_catalog.database import CatalogDatabase


def _connection(database: CatalogDatabase | Path | str) -> sqlite3.Connection:
    if isinstance(database, CatalogDatabase):
        snapshot = sqlite3.connect(":memory:")
        snapshot.row_factory = sqlite3.Row
        database.connection.backup(snapshot)
        snapshot.execute("PRAGMA query_only = ON")
        return snapshot
    return CatalogDatabase.open_read_only(Path(database)).connection


def _rows(database: CatalogDatabase | Path | str, sql: str, values: tuple = ()) -> list[dict]:
    connection = _connection(database)
    try:
        return _rows_on(connection, sql, values)
    finally:
        connection.close()


def _rows_on(connection: sqlite3.Connection, sql: str, values: tuple = ()) -> list[dict]:
    return [dict(row) for row in connection.execute(sql, values)]


def list_remote_runs(
    database: CatalogDatabase | Path | str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    return _rows(
        database,
        """SELECT rr.remote_run_id, p.platform_key AS platform, rr.instance_host,
                  rr.operation, rr.target, rr.adapter_version, rr.schema_version,
                  rr.resumed_from_run_id, rr.status, rr.request_budget, rr.page_budget,
                  rr.record_budget, rr.time_budget_seconds, rr.request_count, rr.page_count,
                  rr.record_count, rr.termination_outcome, rr.budget_boundary, rr.retry_after,
                  rr.diagnostic_summary, rr.started_at, rr.finished_at
           FROM remote_runs rr JOIN platforms p USING(platform_id)
           ORDER BY rr.remote_run_id DESC LIMIT ?""",
        (limit,),
    )


def get_remote_run(
    database: CatalogDatabase | Path | str,
    remote_run_id: int,
) -> dict[str, Any] | None:
    connection = _connection(database)
    try:
        runs = _rows_on(
            connection,
            """SELECT rr.remote_run_id, p.platform_key AS platform, rr.instance_host,
                  rr.operation, rr.target, rr.adapter_version, rr.schema_version,
                  rr.resumed_from_run_id, rr.status, rr.request_count, rr.page_count,
                  rr.record_count, rr.termination_outcome, rr.budget_boundary, rr.retry_after,
                  rr.diagnostic_summary, rr.started_at, rr.finished_at
           FROM remote_runs rr JOIN platforms p USING(platform_id)
           WHERE rr.remote_run_id = ?""",
            (remote_run_id,),
        )
        if not runs:
            return None
        runs[0]["requests"] = _rows_on(
            connection,
            """SELECT remote_request_id, attempt_number, request_identity, operation, target,
                  status_code, outcome, retry_after, rate_limit_state,
                  response_adapter_version, response_schema_version, object_kind, native_id,
                  media_type, response_size, request_started_at, response_observed_at,
                  request_finished_at
           FROM remote_requests WHERE remote_run_id = ? ORDER BY attempt_number""",
            (remote_run_id,),
        )
        runs[0]["checkpoints"] = _rows_on(
            connection,
            """SELECT remote_checkpoint_id, operation, target, continuation_adapter,
                  continuation_version, last_page_identity, page_count, committed_at
           FROM remote_checkpoints WHERE remote_run_id = ?
           ORDER BY remote_checkpoint_id""",
            (remote_run_id,),
        )
        return runs[0]
    finally:
        connection.close()


def list_post_tags(
    database: CatalogDatabase | Path | str,
    post_id: int,
) -> list[dict[str, Any]]:
    return _rows(
        database,
        """SELECT t.tag_id, p.platform_key AS platform, t.category, t.name,
                  t.normalization_version, pt.first_seen_at, pt.last_seen_at,
                  COUNT(pto.post_tag_observation_id) AS observation_count
           FROM post_tags pt JOIN tags t USING(tag_id) JOIN platforms p USING(platform_id)
           LEFT JOIN post_tag_observations pto USING(post_tag_id)
           WHERE pt.post_id = ? GROUP BY pt.post_tag_id ORDER BY t.category, t.name""",
        (post_id,),
    )


def list_post_external_references(
    database: CatalogDatabase | Path | str,
    post_id: int,
) -> list[dict[str, Any]]:
    return _rows(
        database,
        """SELECT per.post_external_reference_id, per.reference_kind,
                  el.canonical_url AS observed_url, p.platform_key AS target_platform,
                  pr.object_kind AS target_object_kind,
                  pr.identifier_kind AS target_identifier_kind,
                  pr.native_identifier AS target_native_identifier, per.observed_at
           FROM post_external_references per
           LEFT JOIN external_links el USING(external_link_id)
           LEFT JOIN platform_references pr USING(platform_reference_id)
           LEFT JOIN platforms p ON p.platform_id = pr.platform_id
           WHERE per.post_id = ? ORDER BY per.post_external_reference_id""",
        (post_id,),
    )


def list_account_external_links(
    database: CatalogDatabase | Path | str,
    account_id: int,
) -> list[dict[str, Any]]:
    return _rows(
        database,
        """SELECT ael.account_external_link_id, el.canonical_url, ael.source_context,
                  ael.observed_at
           FROM account_external_links ael JOIN external_links el USING(external_link_id)
           WHERE ael.account_id = ? ORDER BY ael.account_external_link_id""",
        (account_id,),
    )


def list_attributions(
    database: CatalogDatabase | Path | str,
    *,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    where = "WHERE p.platform_key = ?" if platform is not None else ""
    values = (platform,) if platform is not None else ()
    return _rows(
        database,
        f"""SELECT ae.attribution_entity_id, p.platform_key AS platform, ae.instance_host,
                   ae.provider_attribution_id, ae.adapter_version, ae.availability,
                   ae.first_seen_at, ae.last_seen_at,
                   COUNT(DISTINCT an.attribution_name_id) AS name_count,
                   COUNT(DISTINCT au.attribution_url_id) AS url_count
            FROM attribution_entities ae JOIN platforms p USING(platform_id)
            LEFT JOIN attribution_names an USING(attribution_entity_id)
            LEFT JOIN attribution_urls au USING(attribution_entity_id)
            {where} GROUP BY ae.attribution_entity_id
            ORDER BY ae.attribution_entity_id""",
        values,
    )


class RemoteQueryService:
    def __init__(self, database: CatalogDatabase | Path | str) -> None:
        self.database = database

    def runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return list_remote_runs(self.database, limit=limit)

    def run(self, remote_run_id: int) -> dict[str, Any] | None:
        return get_remote_run(self.database, remote_run_id)

    def post_tags(self, post_id: int) -> list[dict[str, Any]]:
        return list_post_tags(self.database, post_id)

    def post_external_references(self, post_id: int) -> list[dict[str, Any]]:
        return list_post_external_references(self.database, post_id)

    def account_external_links(self, account_id: int) -> list[dict[str, Any]]:
        return list_account_external_links(self.database, account_id)

    def attributions(self, *, platform: str | None = None) -> list[dict[str, Any]]:
        return list_attributions(self.database, platform=platform)
