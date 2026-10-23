"""Bounded single-pool fetch for the danbooru family (Bead data-processing-cq0).

One pool by native id through the provider's pool endpoint, under the
standard run contract: declared budgets, a recorded remote request, a
retained raw report, and a typed outcome.  The provider-declared member
order lands as one digest-deduplicated pool observation with ordered
member observations -- ordering-bearing work-grouping evidence only; no
work, relationship, or grouping conclusion is created here.
"""

from __future__ import annotations

import json
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


def fetch_pool(
    database: CatalogDatabase,
    adapter: Any,
    pool_id: int,
    *,
    clock: Any,
    time_budget_seconds: int = 60,
) -> dict[str, Any]:
    """Fetch one pool by id and record its ordered membership observation.

    The run contract follows the metadata sync service shape: the run row
    commits before the fetch (the attempt is auditable even when the
    transport raises), the fetch happens outside any transaction, and the
    request, raw report, observation, and finish commit together -- no
    outside reader ever sees a half-finished pool run.
    """

    if pool_id <= 0:
        raise ValueError("pool id must be positive")
    now = str(clock())
    writer = CatalogWriter(database)
    with database.transaction():
        run_id = writer.begin_remote_run(
            RemoteRunRecord(
                platform=adapter.instance_key,
                operation=AdapterOperation.FETCH_POOL.value,
                target=str(pool_id),
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
            AdapterRequest(operation=AdapterOperation.FETCH_POOL, target=str(pool_id))
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
                finished_at=str(clock()),
                diagnostic="adapter fetch raised",
            )
        raise
    outcome = _response_outcome(response.status_code)
    record_count = 0
    pool_result: dict[str, Any] | None = None
    if outcome.value == "success":
        document = _parse_pool(response.payload, pool_id)
        outcome_name = "malformed_response" if document is None else "success"
    else:
        document = None
        outcome_name = outcome.value
    validate_remote_outcome(outcome_name)
    media_type = response.headers.get("content-type", "application/json").split(";", 1)[0]
    with database.transaction():
        request_id = writer.record_remote_request(
            RemoteRequestRecord(
                remote_run_id=run_id,
                attempt_number=1,
                request_identity=response.request_identity,
                operation=AdapterOperation.FETCH_POOL.value,
                target=str(pool_id),
                outcome=outcome_name,
                request_started_at=response.observed_at,
                status_code=response.status_code,
                response_adapter_version=response.adapter_version,
                response_schema_version=response.schema_version,
                object_kind="pool",
                native_id=str(pool_id),
                media_type=media_type,
                response_size=len(response.payload),
                response_observed_at=response.observed_at,
                request_finished_at=response.observed_at,
                transport_key=response.transport_key,
                transport_version=response.transport_version,
            )
        )
        # Every 2xx response retains its raw report, malformed or not; the
        # observation exists only when the document parses.
        raw_observation_id = writer.store_raw(
            RawRecord(
                payload=response.payload,
                media_type=media_type,
                object_kind="pool",
                native_id=str(pool_id),
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
        if document is not None:
            result = writer.record_pool_observation(
                PoolObservationRecord(
                    platform=adapter.instance_key,
                    pool_native_id=document["pool_native_id"],
                    post_native_ids=document["post_native_ids"],
                    observed_at=response.observed_at,
                ),
                raw_observation_id=raw_observation_id,
            )
            record_count = 1
            pool_result = {
                "pool_observation_id": result.id,
                "outcome_kind": result.outcome,
                "members": len(document["post_native_ids"]),
            }
        writer.finish_remote_run(
            run_id,
            status="complete" if outcome_name == "success" else "failed",
            outcome=outcome_name,
            request_count=1,
            page_count=1,
            record_count=record_count,
            finished_at=str(clock()),
        )
    return {
        "remote_run_id": run_id,
        "pool_id": pool_id,
        "outcome": outcome_name,
        "pool_observation": pool_result,
    }


def _parse_pool(payload: bytes, pool_id: int) -> dict[str, Any] | None:
    """Return the pool identity and ordered members, or None when malformed."""

    try:
        document = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(document, dict):
        return None
    native_id = document.get("id")
    post_ids = document.get("post_ids")
    if isinstance(native_id, bool) or not isinstance(native_id, int) or native_id <= 0:
        return None
    if not isinstance(post_ids, list):
        return None
    members: list[str] = []
    for member in post_ids:
        if isinstance(member, bool) or not isinstance(member, int) or member <= 0:
            return None
        members.append(str(member))
    if native_id != pool_id:
        return None
    return {"pool_native_id": str(native_id), "post_native_ids": tuple(members)}
