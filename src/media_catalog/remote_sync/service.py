from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from media_catalog.adapters import (
    Adapter,
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    AdapterRequest,
    Continuation,
    ResponseEnvelope,
)
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    RawRecord,
    RemoteCheckpointRecord,
    RemoteRequestRecord,
    RemoteRunRecord,
)
from media_catalog.writer import CatalogWriter

from .budget import BudgetExhausted, BudgetTracker, SyncLimits
from .persistence import NormalizedPageWriter
from .request_gate import RequestGate


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class SyncResult:
    remote_run_id: int
    platform: str
    operation: str
    target: str
    status: str
    outcome: str
    request_count: int
    page_count: int
    record_count: int
    resumed_from_run_id: int | None = None
    budget_boundary: str | None = None
    retry_after: str | None = None
    diagnostic: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "remote_run_id": self.remote_run_id,
            "platform": self.platform,
            "operation": self.operation,
            "target": self.target,
            "status": self.status,
            "outcome": self.outcome,
            "request_count": self.request_count,
            "page_count": self.page_count,
            "record_count": self.record_count,
            "resumed_from_run_id": self.resumed_from_run_id,
            "budget_boundary": self.budget_boundary,
            "retry_after": self.retry_after,
            "diagnostic": self.diagnostic,
        }


class MetadataSyncService:
    """Bounded metadata-only synchronization facade."""

    def __init__(
        self,
        database: CatalogDatabase,
        adapter: Adapter,
        *,
        minimum_interval_seconds: float = 1.0,
        maximum_retries: int = 2,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], str] = _now,
    ) -> None:
        self.database = database
        self.adapter = adapter
        self.writer = CatalogWriter(database)
        self.page_writer = NormalizedPageWriter(self.writer)
        self.minimum_interval_seconds = minimum_interval_seconds
        self.maximum_retries = maximum_retries
        self.monotonic = monotonic
        self.sleep = sleep
        self.clock = clock

    def synchronize(
        self,
        operation: AdapterOperation,
        target: str,
        *,
        limits: SyncLimits,
        resume_from_run_id: int | None = None,
    ) -> SyncResult:
        continuation = self._resume_continuation(
            resume_from_run_id, operation=operation, target=target
        )
        started_at = self.clock()
        with self.database.transaction():
            run_id = self.writer.begin_remote_run(
                RemoteRunRecord(
                    platform=self.adapter.instance_key,
                    operation=operation.value,
                    target=target,
                    adapter_version=self.adapter.adapter_version,
                    schema_version=self.adapter.schema_version,
                    request_budget=limits.requests,
                    page_budget=limits.pages,
                    record_budget=limits.records,
                    time_budget_seconds=max(1, int(limits.elapsed_seconds)),
                    started_at=started_at,
                    resumed_from_run_id=resume_from_run_id,
                )
            )
        budget = BudgetTracker(limits, monotonic=self.monotonic)
        gate = RequestGate(
            budget,
            minimum_interval_seconds=self.minimum_interval_seconds,
            maximum_retries=self.maximum_retries,
            monotonic=self.monotonic,
            sleep=self.sleep,
        )
        try:
            while True:
                request = AdapterRequest(operation, target, continuation)
                captured: list[tuple[ResponseEnvelope, int]] = []

                def retain(
                    response: ResponseEnvelope,
                    captured_responses: list[tuple[ResponseEnvelope, int]] = captured,
                ) -> None:
                    raw_id = self._retain_response(run_id, budget.requests, response, target)
                    captured_responses.append((response, raw_id))

                response = gate.execute(
                    lambda current_request=request: self.adapter.fetch(current_request), retain
                )
                raw_id = next(
                    raw_id for retained, raw_id in reversed(captured) if retained is response
                )
                page = self.adapter.normalize(response)
                budget.admit_page(page.record_count)
                with self.database.transaction():
                    self.page_writer.write(
                        page,
                        observed_at=response.observed_at,
                        raw_observation_id=raw_id,
                        adapter_version=response.adapter_version,
                    )
                    budget.commit_page(page.record_count)
                    if page.continuation is not None:
                        self.writer.save_remote_checkpoint(
                            RemoteCheckpointRecord(
                                remote_run_id=run_id,
                                operation=operation.value,
                                target=target,
                                continuation_adapter=page.continuation.adapter,
                                continuation_version=page.continuation.version,
                                continuation_json=page.continuation.to_json(),
                                last_page_identity=response.request_identity,
                                page_count=budget.pages,
                                committed_at=self.clock(),
                            )
                        )
                continuation = page.continuation
                if continuation is None or operation is not AdapterOperation.LIST_ACCOUNT_POSTS:
                    return self._finish(
                        run_id,
                        operation,
                        target,
                        budget,
                        status="complete",
                        outcome=AdapterOutcome.SUCCESS,
                        resumed_from_run_id=resume_from_run_id,
                    )
        except BudgetExhausted as error:
            return self._finish(
                run_id,
                operation,
                target,
                budget,
                status="paused",
                outcome=error.outcome,
                resumed_from_run_id=resume_from_run_id,
                budget_boundary=error.boundary,
                diagnostic=error.public_message,
            )
        except AdapterFailure as error:
            return self._finish(
                run_id,
                operation,
                target,
                budget,
                status="failed",
                outcome=error.outcome,
                resumed_from_run_id=resume_from_run_id,
                retry_after=error.retry_at,
                diagnostic=error.public_message,
            )
        except Exception as error:
            result = self._finish(
                run_id,
                operation,
                target,
                budget,
                status="failed",
                outcome=AdapterOutcome.LOCAL_PERSISTENCE,
                resumed_from_run_id=resume_from_run_id,
                diagnostic=f"local metadata persistence failed ({type(error).__name__})",
            )
            raise RuntimeError(result.diagnostic) from error

    def _retain_response(
        self,
        run_id: int,
        attempt: int,
        response: ResponseEnvelope,
        target: str,
    ) -> int:
        outcome = _response_outcome(response.status_code)
        with self.database.transaction():
            request_id = self.writer.record_remote_request(
                RemoteRequestRecord(
                    remote_run_id=run_id,
                    attempt_number=attempt,
                    request_identity=response.request_identity,
                    operation=response.operation.value,
                    target=target,
                    outcome=outcome.value,
                    request_started_at=response.observed_at,
                    status_code=response.status_code,
                    response_adapter_version=response.adapter_version,
                    response_schema_version=response.schema_version,
                    media_type=response.headers.get("content-type", "application/json").split(
                        ";", 1
                    )[0],
                    response_size=len(response.payload),
                    response_observed_at=response.observed_at,
                    request_finished_at=response.observed_at,
                )
            )
            return self.writer.store_raw(
                RawRecord(
                    payload=response.payload,
                    media_type=response.headers.get("content-type", "application/json").split(
                        ";", 1
                    )[0],
                    object_kind=_operation_object_kind(response.operation),
                    native_id=target,
                    observed_at=response.observed_at,
                    platform=self.adapter.instance_key,
                    adapter_version=response.adapter_version,
                    schema_version=response.schema_version,
                    status=str(response.status_code),
                ),
                remote_run_id=run_id,
                remote_request_id=request_id,
            )

    def _resume_continuation(
        self,
        parent_id: int | None,
        *,
        operation: AdapterOperation,
        target: str,
    ) -> Continuation | None:
        if parent_id is None:
            return None
        row = self.database.connection.execute(
            """SELECT rr.platform_id, rr.operation, rr.target, rr.adapter_version,
                      rr.schema_version, rr.status, rc.continuation_json
               FROM remote_runs rr
               JOIN remote_checkpoints rc ON rc.remote_run_id = rr.remote_run_id
               WHERE rr.remote_run_id = ?
               ORDER BY rc.remote_checkpoint_id DESC LIMIT 1""",
            (parent_id,),
        ).fetchone()
        if row is None or row["status"] not in {"paused", "complete"}:
            raise ValueError("resume run has no committed checkpoint")
        platform_id = self.writer.platform_id(self.adapter.instance_key)
        compatible = (
            int(row["platform_id"]) == platform_id
            and row["operation"] == operation.value
            and row["target"] == target
            and row["adapter_version"] == self.adapter.adapter_version
            and row["schema_version"] == self.adapter.schema_version
        )
        if not compatible:
            raise ValueError("resume checkpoint is incompatible with this adapter request")
        return Continuation.from_json(row["continuation_json"])

    def _finish(
        self,
        run_id: int,
        operation: AdapterOperation,
        target: str,
        budget: BudgetTracker,
        *,
        status: str,
        outcome: AdapterOutcome,
        resumed_from_run_id: int | None,
        budget_boundary: str | None = None,
        retry_after: str | None = None,
        diagnostic: str | None = None,
    ) -> SyncResult:
        with self.database.transaction():
            self.writer.finish_remote_run(
                run_id,
                status=status,
                outcome=outcome.value,
                request_count=budget.requests,
                page_count=budget.pages,
                record_count=budget.records,
                finished_at=self.clock(),
                budget_boundary=budget_boundary,
                retry_after=retry_after,
                diagnostic=diagnostic,
            )
        return SyncResult(
            remote_run_id=run_id,
            platform=self.adapter.instance_key,
            operation=operation.value,
            target=target,
            status=status,
            outcome=outcome.value,
            request_count=budget.requests,
            page_count=budget.pages,
            record_count=budget.records,
            resumed_from_run_id=resumed_from_run_id,
            budget_boundary=budget_boundary,
            retry_after=retry_after,
            diagnostic=diagnostic,
        )


def _response_outcome(status: int) -> AdapterOutcome:
    if 200 <= status < 300:
        return AdapterOutcome.SUCCESS
    if status == 401:
        return AdapterOutcome.AUTHENTICATION_REQUIRED
    if status == 403:
        return AdapterOutcome.AUTHORIZATION_DENIED
    if status == 404:
        return AdapterOutcome.UNAVAILABLE
    if status == 410:
        return AdapterOutcome.DELETED
    if status == 429:
        return AdapterOutcome.RATE_LIMITED
    if status >= 500:
        return AdapterOutcome.TRANSIENT_PROVIDER
    return AdapterOutcome.MALFORMED_RESPONSE


def _operation_object_kind(operation: AdapterOperation) -> str:
    return {
        AdapterOperation.FETCH_ACCOUNT: "account",
        AdapterOperation.FETCH_POST: "post",
        AdapterOperation.LIST_ACCOUNT_POSTS: "post",
        AdapterOperation.FETCH_ATTRIBUTION: "attribution",
    }[operation]
