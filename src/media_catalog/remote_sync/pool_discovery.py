"""Danbooru pool search: discovery plus membership in one request (bead
``data-processing-rip``, change ``add-danbooru-pool-discovery``).

``GET /pools.json?search[name_matches]=<name>`` returns full pool objects
with complete ordered ``post_ids`` (verified by live capture 2026-11-15), so
one bounded search per name both discovers pools and delivers their ordered
membership.  Recording follows the fetch_pool contract: the run commits
before the request, the response stays as a raw report, and every parsed
pool becomes one digest-deduplicated observation anchored to that raw.
Re-running a name is skipped when a complete prior run exists.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from media_catalog.adapters import AdapterOperation, AdapterRequest, ResponseEnvelope
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    PoolObservationRecord,
    RawRecord,
    RemoteRequestRecord,
    RemoteRunRecord,
    validate_remote_outcome,
)
from media_catalog.remote_sync.service import _response_outcome
from media_catalog.writer import CatalogWriter

POOL_SCHEMA_VERSION = "danbooru-pools-v1"


def search_pools(
    database: CatalogDatabase,
    adapter: Any,
    name: str,
    *,
    clock: Any,
    time_budget_seconds: int = 60,
) -> dict[str, Any]:
    """Search pools by name and record every matching pool's membership."""
    name = name.strip()
    if not 1 <= len(name) <= 100:
        raise ValueError("pool name must be 1-100 characters")
    now = str(clock())
    writer = CatalogWriter(database)
    with database.transaction():
        run_id = writer.begin_remote_run(
            RemoteRunRecord(
                platform=adapter.instance_key,
                operation=AdapterOperation.SEARCH_POOLS.value,
                target=name,
                adapter_version=str(adapter.adapter_version),
                schema_version=POOL_SCHEMA_VERSION,
                request_budget=1,
                page_budget=1,
                record_budget=1,
                time_budget_seconds=time_budget_seconds,
                started_at=now,
            )
        )
    try:
        response: ResponseEnvelope = adapter.fetch(
            AdapterRequest(operation=AdapterOperation.SEARCH_POOLS, target=name)
        )
    except BaseException:
        with database.transaction():
            writer.finish_remote_run(
                run_id,
                status="failed",
                outcome="local_persistence",
                request_count=0,
                page_count=0,
                record_count=0,
                diagnostic="adapter fetch raised",
                finished_at=str(clock()),
            )
        raise
    outcome = _response_outcome(response.status_code)
    pools = _parse_pool_search(response.payload) if outcome.value == "success" else None
    outcome_name = (
        "malformed_response" if pools is None and outcome.value == "success" else outcome.value
    )
    validate_remote_outcome(outcome_name)
    media_type = response.headers.get("content-type", "application/json").split(";", 1)[0]
    recorded: list[dict[str, Any]] = []
    with database.transaction():
        request_id = writer.record_remote_request(
            RemoteRequestRecord(
                remote_run_id=run_id,
                attempt_number=1,
                request_identity=response.request_identity,
                operation=AdapterOperation.SEARCH_POOLS.value,
                target=name,
                outcome=outcome_name,
                request_started_at=response.observed_at,
                status_code=response.status_code,
                response_adapter_version=response.adapter_version,
                response_schema_version=response.schema_version,
                object_kind="pool_search",
                native_id=None,
                media_type=media_type,
                response_size=len(response.payload),
                response_observed_at=response.observed_at,
                request_finished_at=response.observed_at,
                transport_key=response.transport_key,
                transport_version=response.transport_version,
            )
        )
        raw_observation_id = writer.store_raw(
            RawRecord(
                payload=response.payload,
                media_type=media_type,
                object_kind="pool_search",
                native_id=name,
                observed_at=response.observed_at,
                platform=adapter.instance_key,
                adapter_version=response.adapter_version,
                schema_version=POOL_SCHEMA_VERSION,
                transport_key=response.transport_key,
                transport_version=response.transport_version,
                status=str(response.status_code),
            ),
            remote_run_id=run_id,
            remote_request_id=request_id,
        )
        for pool in pools or ():
            result = writer.record_pool_observation(
                PoolObservationRecord(
                    platform=adapter.instance_key,
                    pool_native_id=pool["pool_native_id"],
                    post_native_ids=pool["post_native_ids"],
                    observed_at=response.observed_at,
                ),
                raw_observation_id=raw_observation_id,
            )
            recorded.append(
                {
                    "pool_native_id": pool["pool_native_id"],
                    "name": pool["name"],
                    "members": len(pool["post_native_ids"]),
                    "outcome_kind": result.outcome,
                }
            )
        writer.finish_remote_run(
            run_id,
            status="complete" if outcome_name == "success" else "failed",
            outcome=outcome_name,
            request_count=1,
            page_count=1,
            record_count=len(recorded),
            finished_at=str(clock()),
        )
    return {
        "remote_run_id": run_id,
        "name": name,
        "outcome": outcome_name,
        "pools": recorded,
        "pools_found": len(pools or ()),
    }


def _parse_pool_search(payload: bytes) -> list[dict[str, Any]] | None:
    """Every pool object must carry a positive id and a list of member ids."""
    try:
        document = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(document, list):
        return None
    pools: list[dict[str, Any]] = []
    for entry in document:
        if not isinstance(entry, dict):
            return None
        native_id = entry.get("id")
        post_ids = entry.get("post_ids")
        if isinstance(native_id, bool) or not isinstance(native_id, int) or native_id <= 0:
            return None
        if not isinstance(post_ids, list):
            return None
        members: list[str] = []
        for member in post_ids:
            if isinstance(member, bool) or not isinstance(member, int) or member <= 0:
                return None
            members.append(str(member))
        name = entry.get("name")
        pools.append(
            {
                "pool_native_id": str(native_id),
                "name": name if isinstance(name, str) else "",
                "post_native_ids": tuple(members),
            }
        )
    return pools


def _searched_names(connection: sqlite3.Connection, platform_key: str) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            """SELECT DISTINCT rr.target FROM remote_runs rr
                 JOIN platforms pl ON pl.platform_id = rr.platform_id
                WHERE pl.platform_key = ? AND rr.operation = 'search_pools'
                  AND rr.status = 'complete'""",
            (platform_key,),
        )
    }


def ranked_artist_names(
    connection: sqlite3.Connection, platform_key: str, *, limit: int
) -> list[tuple[str, int]]:
    """Artist names by how many of their posts the catalog holds."""
    return [
        (str(row[0]), int(row[1]))
        for row in connection.execute(
            """SELECT t.name, count(DISTINCT p.post_id) AS held
                 FROM tags t
                 JOIN post_tags pt ON pt.tag_id = t.tag_id
                 JOIN posts p ON p.post_id = pt.post_id
                 JOIN platforms pl ON pl.platform_id = p.platform_id
                WHERE pl.platform_key = ? AND t.category = 'artist'
                GROUP BY t.name
               HAVING held >= 3
                ORDER BY held DESC, t.name
                LIMIT ?""",
            (platform_key, limit),
        )
    ]


def discover_pools(
    database: CatalogDatabase,
    adapter_factory: Any,
    platform_key: str,
    *,
    clock: Any,
    names_limit: int = 50,
    request_budget: int = 50,
    client_factory: Any = None,
    minimum_interval_seconds: float = 0.0,
) -> dict[str, Any]:
    """Search pools for the catalog's top artist names, skipping prior runs.

    One live request per not-yet-searched name; pool recording reuses the
    per-pool digest so unchanged pools stay deduplicated across runs.
    """
    import httpx

    connection = database.connection
    names = ranked_artist_names(connection, platform_key, limit=names_limit)
    already = _searched_names(connection, platform_key)
    client_factory = client_factory or httpx.Client
    results: list[dict[str, Any]] = []
    requests_used = 0
    skipped = 0
    with client_factory() as client:
        adapter = adapter_factory(client)
        for name, held in names:
            if name in already:
                skipped += 1
                continue
            if requests_used >= request_budget:
                break
            if requests_used and minimum_interval_seconds > 0:
                time.sleep(minimum_interval_seconds)
            result = search_pools(database, adapter, name, clock=clock)
            result["artist_held_posts"] = held
            results.append(result)
            requests_used += 1
    return {
        "platform": platform_key,
        "names_considered": len(names),
        "names_skipped_already_searched": skipped,
        "names_searched": len(results),
        "requests_used": requests_used,
        "pools_recorded": sum(entry["pools_found"] for entry in results),
        "results": results,
    }
