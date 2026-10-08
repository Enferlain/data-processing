"""Offline reprocessing: replay retained raw through the current normalizer.

The reprocessing contract (OpenSpec ``add-reprocessing-contract``): a
normalization attempt is identified by (source payload, adapter version,
schema version); replaying a retained raw never contacts the provider, never
mutates the retained payload or prior interpretations, lands new facts as
observations under the current-projection policy, and is idempotent per
(raw, adapter version, schema version). Facts keep the retained raw's
original observation time so the current-projection policy keeps ranking by
when the source reported a fact; the replay's own wall-clock time is run
provenance only.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Any

from media_catalog.adapters.contracts import (
    AdapterFailure,
    AdapterOperation,
    ResponseEnvelope,
)
from media_catalog.database import CatalogDatabase
from media_catalog.records.remote import RemoteRunRecord
from media_catalog.remote_sync.persistence import NormalizedPageWriter
from media_catalog.writer import CatalogWriter

REPROCESS_ORIGIN_KIND = "reprocess"
_MAX_BATCH = 10_000


def _reprocess_reference(raw_id: int, adapter_version: str, schema_version: str) -> str:
    """Deterministic origin reference: sha256 over the replay identity.

    Remote-run origin references are 64-hex digests by record contract, so a
    reprocess run is keyed by the same composite that idempotency checks
    reconstruct: the raw observation, the replay adapter version, and the
    schema version.
    """

    payload = f"reprocess:{raw_id}:{adapter_version}:{schema_version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ReprocessCandidate:
    raw_observation_id: int
    platform: str
    operation: str
    target: str
    raw_adapter_version: str
    raw_schema_version: str
    already_reprocessed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_observation_id": self.raw_observation_id,
            "platform": self.platform,
            "operation": self.operation,
            "target": self.target,
            "raw_adapter_version": self.raw_adapter_version,
            "raw_schema_version": self.raw_schema_version,
            "already_reprocessed": self.already_reprocessed,
        }


@dataclass(frozen=True, slots=True)
class ReprocessItemResult:
    raw_observation_id: int
    status: str
    outcome: str
    record_count: int
    remote_run_id: int | None
    diagnostic: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_observation_id": self.raw_observation_id,
            "status": self.status,
            "outcome": self.outcome,
            "record_count": self.record_count,
            "remote_run_id": self.remote_run_id,
            **({"diagnostic": self.diagnostic} if self.diagnostic else {}),
        }


def _completed_reprocess_references(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT origin_reference FROM remote_runs "
            "WHERE origin_kind = ? AND status = 'complete'",
            (REPROCESS_ORIGIN_KIND,),
        )
    }


def plan_reprocess(
    database: CatalogDatabase | sqlite3.Connection,
    *,
    adapter: Any,
    limit: int = 100,
) -> dict[str, Any]:
    """List retained raw observations that are stale under ``adapter``.

    Read-only: a candidate is a raw observation with a remote run for the
    adapter's platform whose recorded adapter version or schema version
    differs from the replay adapter's (either drift changes the
    normalization identity, so both count as stale); replays already
    completed under the current versions are reported as skips.
    """

    connection = database.connection if isinstance(database, CatalogDatabase) else database
    if not 0 < limit <= _MAX_BATCH:
        raise ValueError(f"reprocess limit must be between 1 and {_MAX_BATCH}")
    rows = connection.execute(
        """SELECT ro.raw_observation_id, pl.platform_key, rr.operation, rr.target,
                  ro.adapter_version AS raw_adapter_version,
                  ro.schema_version AS raw_schema_version
             FROM raw_observations ro
             JOIN remote_runs rr USING (remote_run_id)
             JOIN platforms pl ON pl.platform_id = ro.platform_id
            WHERE pl.platform_key = ?
              AND ro.adapter_version IS NOT NULL
              AND (ro.adapter_version != ?
                   OR ro.schema_version IS NULL
                   OR ro.schema_version != ?)
            ORDER BY ro.raw_observation_id
            LIMIT ?""",
        (adapter.instance_key, adapter.adapter_version, adapter.schema_version, limit),
    ).fetchall()
    done = _completed_reprocess_references(connection)
    candidates = [
        ReprocessCandidate(
            int(row["raw_observation_id"]),
            row["platform_key"],
            row["operation"],
            row["target"],
            row["raw_adapter_version"],
            row["raw_schema_version"],
            _reprocess_reference(
                int(row["raw_observation_id"]), adapter.adapter_version, adapter.schema_version
            )
            in done,
        )
        for row in rows
    ]
    return {
        "provider": adapter.provider_key,
        "adapter_version": adapter.adapter_version,
        "schema_version": adapter.schema_version,
        "count": len(candidates),
        "results": [candidate.as_dict() for candidate in candidates],
    }


def execute_reprocess(
    database: CatalogDatabase,
    adapter: Any,
    *,
    raw_observation_ids: list[int] | tuple[int, ...],
    clock: Any,
) -> dict[str, Any]:
    """Replay retained raws offline through the current adapter normalizer.

    Each replay commits independently: the reconstructed envelope is
    normalized and written through the shared page writer under a
    reprocess-origin remote run with zero provider requests.  The retained
    payload is never modified, and a raw already replayed under the current
    adapter/schema versions is skipped.  Facts land at the retained raw's
    original observation time; ``clock`` timestamps only the run itself.
    """

    if not raw_observation_ids:
        raise ValueError("reprocessing requires at least one raw observation id")
    if len(raw_observation_ids) > _MAX_BATCH:
        raise ValueError(f"reprocessing batches are bounded to {_MAX_BATCH} raws")
    results = [
        _replay_one(database, adapter, int(raw_id), clock)
        for raw_id in dict.fromkeys(raw_observation_ids)
    ]
    counts: dict[str, int] = {}
    for item in results:
        counts[item.status] = counts.get(item.status, 0) + 1
    return {
        "provider": adapter.provider_key,
        "adapter_version": adapter.adapter_version,
        "schema_version": adapter.schema_version,
        "count": len(results),
        "counts": dict(sorted(counts.items())),
        "results": [item.as_dict() for item in results],
    }


def _replay_one(
    database: CatalogDatabase, adapter: Any, raw_id: int, clock: Any
) -> ReprocessItemResult:
    connection = database.connection
    row = connection.execute(
        """SELECT ro.raw_observation_id, ro.status, ro.observed_at,
                  ro.adapter_version, ro.schema_version, ro.object_kind,
                  ro.native_id, ro.transport_key, ro.transport_version,
                  rr.operation, rr.target, pl.platform_key, rp.payload
             FROM raw_observations ro
             JOIN remote_runs rr USING (remote_run_id)
             JOIN platforms pl ON pl.platform_id = ro.platform_id
             JOIN raw_payloads rp ON rp.raw_payload_id = ro.raw_payload_id
            WHERE ro.raw_observation_id = ?""",
        (raw_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"raw observation {raw_id} not found or has no remote run")
    if row["platform_key"] != adapter.instance_key:
        raise ValueError(f"raw observation {raw_id} belongs to platform {row['platform_key']!r}")
    reference = _reprocess_reference(raw_id, adapter.adapter_version, adapter.schema_version)
    already = connection.execute(
        "SELECT 1 FROM remote_runs "
        "WHERE origin_kind = ? AND origin_reference = ? AND status = 'complete' LIMIT 1",
        (REPROCESS_ORIGIN_KIND, reference),
    ).fetchone()
    if already is not None:
        return ReprocessItemResult(raw_id, "skipped", "already_reprocessed", 0, None)

    operation = AdapterOperation(row["operation"])
    status_code = int(row["status"]) if str(row["status"] or "").isdecimal() else 200
    # Source chronology: replayed facts carry the retained raw's original
    # observation time so current-value resolution keeps ranking by when the
    # source reported a fact. The replay's own wall-clock time is recorded on
    # the run (replay provenance), never on the facts.
    source_observed_at = str(row["observed_at"])
    replayed_at = str(clock())
    envelope = ResponseEnvelope(
        provider=adapter.provider_key,
        instance=adapter.instance_key,
        operation=operation,
        request_identity=f"reprocess:raw_observation:{raw_id}",
        status_code=status_code,
        headers={},
        payload=bytes(row["payload"]),
        observed_at=source_observed_at,
        adapter_version=adapter.adapter_version,
        schema_version=adapter.schema_version,
        transport_key=row["transport_key"],
        transport_version=row["transport_version"],
    )
    try:
        page = adapter.normalize(envelope)
    except AdapterFailure as failure:
        run_id = _record_run(
            database,
            adapter,
            raw_id=raw_id,
            operation=operation,
            target=str(row["target"]),
            observed_at=replayed_at,
            status="failed",
            outcome=failure.outcome.value,
            record_count=0,
            diagnostic=str(failure),
        )
        return ReprocessItemResult(
            raw_id, "failed", failure.outcome.value, 0, run_id, diagnostic=str(failure)
        )
    with database.transaction():
        writer = CatalogWriter(database)
        run_id = _begin_run(
            writer,
            adapter,
            raw_id=raw_id,
            operation=operation,
            target=str(row["target"]),
            started_at=replayed_at,
            origin_reference=reference,
        )
        record_count = NormalizedPageWriter(writer).write(
            page,
            observed_at=source_observed_at,
            raw_observation_id=raw_id,
            adapter_version=adapter.adapter_version,
        )
        _finish_run(
            writer,
            run_id,
            finished_at=replayed_at,
            status="complete",
            outcome="success",
            record_count=record_count,
        )
    return ReprocessItemResult(raw_id, "complete", "success", record_count, run_id)


def _begin_run(
    writer: CatalogWriter,
    adapter: Any,
    *,
    raw_id: int,
    operation: AdapterOperation,
    target: str,
    started_at: str,
    origin_reference: str,
) -> int:
    return writer.begin_remote_run(
        RemoteRunRecord(
            platform=adapter.instance_key,
            operation=operation.value,
            target=target,
            adapter_version=adapter.adapter_version,
            schema_version=adapter.schema_version,
            # A reprocess makes zero provider requests; budgets stay positive
            # because the run contract requires it.
            request_budget=1,
            page_budget=1,
            record_budget=100_000,
            time_budget_seconds=1,
            started_at=started_at,
            origin_kind=REPROCESS_ORIGIN_KIND,
            origin_reference=origin_reference,
            transport_key=getattr(adapter, "transport_key", None),
            transport_version=getattr(adapter, "transport_version", None),
        )
    )


def _finish_run(
    writer: CatalogWriter,
    run_id: int,
    *,
    finished_at: str,
    status: str,
    outcome: str,
    record_count: int,
    diagnostic: str | None = None,
) -> None:
    writer.finish_remote_run(
        run_id,
        status=status,
        outcome=outcome,
        request_count=0,
        page_count=1,
        record_count=record_count,
        finished_at=finished_at,
        diagnostic=diagnostic,
    )


def _record_run(
    database: CatalogDatabase,
    adapter: Any,
    *,
    raw_id: int,
    operation: AdapterOperation,
    target: str,
    observed_at: str,
    status: str,
    outcome: str,
    record_count: int,
    diagnostic: str | None = None,
) -> int:
    with database.transaction():
        writer = CatalogWriter(database)
        run_id = _begin_run(
            writer,
            adapter,
            raw_id=raw_id,
            operation=operation,
            target=target,
            started_at=observed_at,
            origin_reference=_reprocess_reference(
                raw_id, adapter.adapter_version, adapter.schema_version
            ),
        )
        _finish_run(
            writer,
            run_id,
            finished_at=observed_at,
            status=status,
            outcome=outcome,
            record_count=record_count,
            diagnostic=diagnostic,
        )
    return run_id
