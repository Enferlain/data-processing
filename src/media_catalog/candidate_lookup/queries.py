"""Bounded, redacted read-only inspection of candidate lookup history."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from media_catalog.database import CatalogDatabase

DatabaseSource = CatalogDatabase | Path | str


@contextmanager
def _connection(database: DatabaseSource) -> Iterator[sqlite3.Connection]:
    if isinstance(database, CatalogDatabase):
        snapshot = sqlite3.connect(":memory:")
        snapshot.row_factory = sqlite3.Row
        database.connection.backup(snapshot)
        snapshot.execute("PRAGMA query_only = ON")
        try:
            yield snapshot
        finally:
            snapshot.close()
        return
    with CatalogDatabase.open_read_only(Path(database)) as opened:
        yield opened.connection


def list_lookup_runs(
    database: DatabaseSource,
    *,
    limit: int = 50,
    after: int | None = None,
    status: str | None = None,
) -> dict[str, object]:
    if not 0 < limit <= 200:
        raise ValueError("lookup run limit must be between 1 and 200")
    if after is not None and after <= 0:
        raise ValueError("lookup run continuation must be positive")
    clauses = ["clr.candidate_lookup_run_id > ?"]
    params: list[object] = [after or 0]
    if status is not None:
        if status not in {"running", "complete", "paused", "failed"}:
            raise ValueError("unsupported lookup run status")
        clauses.append("clr.status = ?")
        params.append(status)
    with _connection(database) as connection:
        rows = connection.execute(
            f"""SELECT clr.*, platform.platform_key
                FROM candidate_lookup_runs clr JOIN platforms platform USING(platform_id)
                WHERE {' AND '.join(clauses)}
                ORDER BY clr.candidate_lookup_run_id LIMIT ?""",
            (*params, limit + 1),
        ).fetchall()
    has_more = len(rows) > limit
    visible = rows[:limit]
    results = [_public_run(row) for row in visible]
    return {
        "count": len(results),
        "has_more": has_more,
        "continuation": int(visible[-1]["candidate_lookup_run_id"])
        if has_more and visible
        else None,
        "results": results,
    }


def get_lookup_run(
    database: DatabaseSource,
    run_id: int,
    *,
    result_limit: int = 100,
    result_after: int | None = None,
) -> dict[str, object] | None:
    if run_id <= 0:
        raise ValueError("lookup run id must be positive")
    if not 0 < result_limit <= 500:
        raise ValueError("lookup result limit must be between 1 and 500")
    if result_after is not None and result_after <= 0:
        raise ValueError("lookup result continuation must be positive")
    with _connection(database) as connection:
        run = connection.execute(
            """SELECT clr.*, platform.platform_key
               FROM candidate_lookup_runs clr JOIN platforms platform USING(platform_id)
               WHERE clr.candidate_lookup_run_id = ?""",
            (run_id,),
        ).fetchone()
        if run is None:
            return None
        rows = connection.execute(
            """SELECT candidate_lookup_result_id, result_kind, result_digest,
                      page_number, result_order,
                      normalized_post_id, attribution_entity_id, platform_reference_id,
                      post_candidate_id, account_candidate_id, match_evidence_id,
                      raw_observation_id, normalized_name, match_mode, explanation, observed_at
               FROM candidate_lookup_results
               WHERE candidate_lookup_run_id = ? AND candidate_lookup_result_id > ?
               ORDER BY candidate_lookup_result_id LIMIT ?""",
            (run_id, result_after or 0, result_limit + 1),
        ).fetchall()
        attempts = connection.execute(
            """SELECT candidate_lookup_request_id, attempt_number, request_identity, state,
                      outcome, status_code, retry_after, response_size, raw_observation_id,
                      started_at, observed_at, finished_at
               FROM candidate_lookup_requests WHERE candidate_lookup_run_id = ?
               ORDER BY attempt_number LIMIT 201""",
            (run_id,),
        ).fetchall()
    has_more = len(rows) > result_limit
    visible = rows[:result_limit]
    results = [dict(row) for row in visible]
    return {
        "run": _public_run(run),
        "result_count": len(results),
        "results_truncated": has_more,
        "result_continuation": int(visible[-1]["candidate_lookup_result_id"])
        if has_more and visible
        else None,
        "results": results,
        "attempts": [dict(row) for row in attempts[:200]],
        "attempts_truncated": len(attempts) > 200,
    }


def _public_run(row: sqlite3.Row) -> dict[str, object]:
    seed_kind = "account" if row["seed_account_id"] is not None else "post"
    seed_id = row["seed_account_id"] or row["seed_post_id"]
    return {
        "candidate_lookup_run_id": int(row["candidate_lookup_run_id"]),
        "provider": row["platform_key"],
        "instance_host": row["instance_host"],
        "strategy": row["strategy"],
        "strategy_version": row["strategy_version"],
        "adapter_version": row["adapter_version"],
        "schema_version": row["schema_version"],
        "seed": f"{seed_kind}:{seed_id}",
        "seed_revision": row["seed_revision"],
        "plan_digest": row["plan_digest"],
        "query_kind": row["query_kind"],
        "material_digest": row["material_digest"],
        "predecessor_run_id": row["predecessor_run_id"],
        "status": row["status"],
        "limits": {
            "requests": row["request_limit"],
            "pages": row["page_limit"],
            "results": row["result_limit"],
            "seconds": row["time_limit_seconds"],
        },
        "counts": {
            "requests": row["request_count"],
            "pages": row["page_count"],
            "results": row["result_count"],
        },
        "outcome": row["termination_outcome"],
        "budget_boundary": row["budget_boundary"],
        "retry_after": row["retry_after"],
        "diagnostic": row["diagnostic_summary"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


class CandidateLookupQueryService:
    def __init__(self, database: DatabaseSource) -> None:
        self.database = database

    def runs(self, **filters) -> dict[str, object]:
        return list_lookup_runs(self.database, **filters)

    def show(self, run_id: int, **pagination) -> dict[str, object] | None:
        return get_lookup_run(self.database, run_id, **pagination)
