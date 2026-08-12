"""Read-only, redacted inspection for artist-library expansions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.media_queries import list_media_occurrences

DatabaseSource = CatalogDatabase | Path | str
MAX_PAGE_SIZE = 200


def _connection(database: DatabaseSource) -> sqlite3.Connection:
    if isinstance(database, CatalogDatabase):
        snapshot = sqlite3.connect(":memory:")
        snapshot.row_factory = sqlite3.Row
        try:
            database.connection.backup(snapshot)
            snapshot.execute("PRAGMA query_only = ON")
        except BaseException:
            snapshot.close()
            raise
        return snapshot
    return CatalogDatabase.open_read_only(Path(database)).connection


def _page(limit: int, after: int | None) -> tuple[int, int]:
    if limit <= 0 or limit > MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if after is not None and after < 0:
        raise ValueError("after must not be negative")
    return limit, after or 0


def list_library_expansions(
    database: DatabaseSource,
    *,
    limit: int = 100,
    after: int | None = None,
) -> dict[str, Any]:
    """List executions in stable order without rendered provider request material."""

    limit, cursor = _page(limit, after)
    connection = _connection(database)
    try:
        rows = list(
            connection.execute(
                """SELECT execution.library_expansion_execution_id,
                          execution.library_expansion_plan_id,
                          execution.predecessor_execution_id, execution.execution_kind,
                          execution.created_at, execution.remote_run_id,
                          plan.target_kind, plan.target_account_id,
                          plan.target_attribution_id, plan.authority_mode,
                          plan.capability_key, plan.estimate_state, plan.estimate_count,
                          plan.plan_digest, run.status, run.termination_outcome,
                          run.request_count, run.page_count, run.record_count,
                          (SELECT COUNT(*) FROM library_expansion_posts discovered
                            WHERE discovered.library_expansion_execution_id =
                                  execution.library_expansion_execution_id) AS post_count,
                          (SELECT COUNT(*) FROM library_expansion_posts incomplete
                            WHERE incomplete.library_expansion_execution_id =
                                  execution.library_expansion_execution_id
                              AND incomplete.details_required = 1) AS incomplete_count
                     FROM library_expansion_executions execution
                     JOIN library_expansion_plans plan USING(library_expansion_plan_id)
                     JOIN remote_runs run USING(remote_run_id)
                    WHERE execution.library_expansion_execution_id > ?
                    ORDER BY execution.library_expansion_execution_id LIMIT ?""",
                (cursor, limit + 1),
            )
        )
        shown = rows[:limit]
        has_more = len(rows) > limit
        results = [_execution_projection(row) for row in shown]
        return {
            "limit": limit,
            "after": after,
            "count": len(results),
            "has_more": has_more,
            "continuation": (
                int(shown[-1]["library_expansion_execution_id"]) if has_more and shown else None
            ),
            "results": results,
        }
    finally:
        connection.close()


def _execution_projection(row: sqlite3.Row) -> dict[str, Any]:
    target_id = (
        row["target_account_id"]
        if row["target_kind"] == "account"
        else row["target_attribution_id"]
    )
    return {
        "library_expansion_execution_id": int(row["library_expansion_execution_id"]),
        "library_expansion_plan_id": int(row["library_expansion_plan_id"]),
        "remote_run_id": int(row["remote_run_id"]),
        "predecessor_execution_id": row["predecessor_execution_id"],
        "execution_kind": str(row["execution_kind"]),
        "created_at": str(row["created_at"]),
        "target": f"{row['target_kind']}:{target_id}",
        "authority": str(row["authority_mode"]),
        "capability": str(row["capability_key"]),
        "estimate": {
            "state": str(row["estimate_state"]),
            "count": row["estimate_count"],
        },
        "status": str(row["status"]),
        "outcome": row["termination_outcome"],
        "request_count": int(row["request_count"]),
        "page_count": int(row["page_count"]),
        "record_count": int(row["record_count"]),
        "discovered_post_count": int(row["post_count"]),
        "incomplete_detail_count": int(row["incomplete_count"]),
        "plan_digest": str(row["plan_digest"]),
    }


def get_library_expansion(database: DatabaseSource, execution_id: int) -> dict[str, Any] | None:
    if execution_id <= 0:
        raise ValueError("library expansion execution id must be positive")
    connection = _connection(database)
    try:
        row = connection.execute(
            """SELECT execution.library_expansion_execution_id,
                      execution.library_expansion_plan_id,
                      execution.predecessor_execution_id, execution.execution_kind,
                      execution.created_at, execution.remote_run_id,
                      plan.target_kind, plan.target_account_id,
                      plan.target_attribution_id, plan.authority_mode,
                      plan.authority_reference, plan.selection_note,
                      plan.capability_key, plan.capability_version,
                      plan.adapter_version, plan.schema_version,
                      plan.seed_revision, plan.target_revision, plan.source_revision,
                      plan.request_limit, plan.page_limit, plan.record_limit,
                      plan.time_limit_seconds, plan.estimate_state, plan.estimate_count,
                      plan.estimate_observed_at, plan.estimate_source,
                      plan.exclusions_json, plan.plan_digest, plan.material_digest,
                      run.status, run.termination_outcome, run.budget_boundary,
                      run.request_count, run.page_count, run.record_count,
                      run.retry_after, run.diagnostic_summary,
                      (SELECT COUNT(*) FROM library_expansion_posts discovered
                        WHERE discovered.library_expansion_execution_id =
                              execution.library_expansion_execution_id) AS post_count,
                      (SELECT COUNT(*) FROM library_expansion_posts incomplete
                        WHERE incomplete.library_expansion_execution_id =
                              execution.library_expansion_execution_id
                          AND incomplete.details_required = 1) AS incomplete_count
                 FROM library_expansion_executions execution
                 JOIN library_expansion_plans plan USING(library_expansion_plan_id)
                 JOIN remote_runs run USING(remote_run_id)
                WHERE execution.library_expansion_execution_id = ?""",
            (execution_id,),
        ).fetchone()
        if row is None:
            return None
        probe_rows = list(
            connection.execute(
                """SELECT library_expansion_probe_id, capability_key,
                          capability_version, outcome, status_code, count_value,
                          raw_observation_id, diagnostic_summary, requested_at, observed_at
                     FROM library_expansion_probes
                    WHERE library_expansion_plan_id = ?
                    ORDER BY library_expansion_probe_id DESC LIMIT 101""",
                (row["library_expansion_plan_id"],),
            )
        )
        result = _execution_projection(row)
        result.update(
            {
                "authority_provenance": row["authority_reference"],
                "selection_note": row["selection_note"],
                "capability_version": str(row["capability_version"]),
                "adapter_version": str(row["adapter_version"]),
                "schema_version": str(row["schema_version"]),
                "revisions": {
                    "seed": str(row["seed_revision"]),
                    "target": str(row["target_revision"]),
                    "source": str(row["source_revision"]),
                },
                "limits": {
                    "requests": int(row["request_limit"]),
                    "pages": int(row["page_limit"]),
                    "records": int(row["record_limit"]),
                    "seconds": int(row["time_limit_seconds"]),
                },
                "estimate": {
                    "state": str(row["estimate_state"]),
                    "count": row["estimate_count"],
                    "observed_at": row["estimate_observed_at"],
                    "source": row["estimate_source"],
                },
                "exclusions": json.loads(row["exclusions_json"]),
                "material_digest": str(row["material_digest"]),
                "budget_boundary": row["budget_boundary"],
                "retry_after": row["retry_after"],
                "diagnostic": row["diagnostic_summary"],
                "probes": [dict(probe) for probe in probe_rows[:100]],
                "probes_truncated": len(probe_rows) > 100,
                "media_filter": {"expansion_plan_id": int(row["library_expansion_plan_id"])},
            }
        )
        return result
    finally:
        connection.close()


def list_expansion_posts(
    database: DatabaseSource,
    plan_id: int,
    *,
    limit: int = 100,
    after: int | None = None,
) -> dict[str, Any]:
    if plan_id <= 0:
        raise ValueError("library expansion plan id must be positive")
    limit, cursor = _page(limit, after)
    connection = _connection(database)
    try:
        rows = list(
            connection.execute(
                """SELECT p.post_id, platform.platform_key, p.native_post_id,
                          p.availability, MIN(discovered.details_required) AS details_required,
                          COUNT(DISTINCT mo.media_occurrence_id) AS occurrence_count
                     FROM library_expansion_posts discovered
                     JOIN library_expansion_executions execution
                       USING(library_expansion_execution_id)
                     JOIN posts p USING(post_id)
                     JOIN platforms platform USING(platform_id)
                LEFT JOIN media_occurrences mo USING(post_id)
                    WHERE execution.library_expansion_plan_id = ? AND p.post_id > ?
                    GROUP BY p.post_id, platform.platform_key, p.native_post_id, p.availability
                    ORDER BY p.post_id LIMIT ?""",
                (plan_id, cursor, limit + 1),
            )
        )
        shown = rows[:limit]
        has_more = len(rows) > limit
        results = [
            {
                "post_id": int(row["post_id"]),
                "platform": str(row["platform_key"]),
                "native_post_id": str(row["native_post_id"]),
                "availability": str(row["availability"]),
                "details_required": bool(row["details_required"]),
                "media_occurrence_count": int(row["occurrence_count"]),
            }
            for row in shown
        ]
        return {
            "library_expansion_plan_id": plan_id,
            "limit": limit,
            "after": after,
            "count": len(results),
            "has_more": has_more,
            "continuation": int(shown[-1]["post_id"]) if has_more and shown else None,
            "incomplete_detail_count": sum(
                1 for item in results if item["details_required"] is True
            ),
            "media_filter": {"expansion_plan_id": plan_id},
            "results": results,
        }
    finally:
        connection.close()


class LibraryExpansionQueryService:
    def __init__(self, database: DatabaseSource) -> None:
        self.database = database

    def runs(self, *, limit: int = 100, after: int | None = None) -> dict[str, Any]:
        return list_library_expansions(self.database, limit=limit, after=after)

    def show(self, execution_id: int) -> dict[str, Any] | None:
        return get_library_expansion(self.database, execution_id)

    def posts(self, plan_id: int, *, limit: int = 100, after: int | None = None) -> dict[str, Any]:
        return list_expansion_posts(self.database, plan_id, limit=limit, after=after)

    def media(self, plan_id: int, *, limit: int = 100, after: int | None = None) -> dict[str, Any]:
        return list_media_occurrences(
            self.database,
            expansion_plan_id=plan_id,
            limit=limit,
            after=after,
        )


__all__ = [
    "LibraryExpansionQueryService",
    "get_library_expansion",
    "list_expansion_posts",
    "list_library_expansions",
]
