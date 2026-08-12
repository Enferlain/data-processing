"""Public bounded candidate-lookup facade and durable executor."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from media_catalog.adapters import (
    AdapterFailure,
    AdapterOutcome,
    LookupAdapter,
    LookupContinuation,
    LookupQueryMaterial,
    LookupRequest,
    NormalizedLookupPage,
    NormalizedPage,
    ResponseEnvelope,
)
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    CandidateLookupCheckpointRecord,
    CandidateLookupRequestRecord,
    CandidateLookupResultRecord,
    CandidateLookupRunRecord,
    RawRecord,
)
from media_catalog.remote_sync.budget import BudgetExhausted, BudgetTracker, SyncLimits
from media_catalog.remote_sync.executor import BoundedRemoteExecutor, RetainedPage
from media_catalog.remote_sync.persistence import NormalizedPageWriter
from media_catalog.writer import CatalogWriter

from .interpretation import LookupInterpreter
from .planning import CandidateLookupPlan, LookupLimits, PlannedLookup, plan_candidate_lookup


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class LookupExecutionResult:
    candidate_lookup_run_id: int
    provider: str
    strategy: str
    seed: str
    status: str
    outcome: str
    request_count: int
    page_count: int
    result_count: int
    predecessor_run_id: int | None = None
    budget_boundary: str | None = None
    retry_after: str | None = None
    diagnostic: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_lookup_run_id": self.candidate_lookup_run_id,
            "provider": self.provider,
            "strategy": self.strategy,
            "seed": self.seed,
            "status": self.status,
            "outcome": self.outcome,
            "request_count": self.request_count,
            "page_count": self.page_count,
            "result_count": self.result_count,
            "predecessor_run_id": self.predecessor_run_id,
            "budget_boundary": self.budget_boundary,
            "retry_after": self.retry_after,
            "diagnostic": self.diagnostic,
        }


class CandidateLookupService:
    """Plan and explicitly execute finite provider lookups without automatic review."""

    def __init__(
        self,
        database: CatalogDatabase,
        adapter: LookupAdapter,
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
        self.interpreter = LookupInterpreter(database.connection)
        self.minimum_interval_seconds = minimum_interval_seconds
        self.maximum_retries = maximum_retries
        self.monotonic = monotonic
        self.sleep = sleep
        self.clock = clock

    def plan(self, seed: str, strategies, *, limits=None, search_term=None):
        return plan_candidate_lookup(
            self.database,
            seed,
            self.adapter.instance,
            tuple(strategies),
            limits=limits,
            search_term=search_term,
        )

    def execute(self, plan: CandidateLookupPlan) -> tuple[LookupExecutionResult, ...]:
        return tuple(self._execute_item(plan.seed, item) for item in plan.items)

    def execute_item(
        self,
        seed: str,
        item: PlannedLookup,
        *,
        predecessor_run_id: int | None = None,
    ) -> LookupExecutionResult:
        return self._execute_item(seed, item, predecessor_run_id=predecessor_run_id)

    def resume(
        self,
        predecessor_run_id: int,
        *,
        limits: LookupLimits,
    ) -> LookupExecutionResult:
        if predecessor_run_id <= 0:
            raise ValueError("predecessor lookup run id must be positive")
        row = self.database.connection.execute(
            """SELECT clr.*, platform.platform_key, checkpoint.continuation_json
               FROM candidate_lookup_runs clr JOIN platforms platform USING(platform_id)
               LEFT JOIN candidate_lookup_checkpoints checkpoint USING(candidate_lookup_run_id)
               WHERE clr.candidate_lookup_run_id = ?""",
            (predecessor_run_id,),
        ).fetchone()
        if row is None or row["status"] != "paused":
            raise ValueError("lookup predecessor is not resumable")
        if (
            row["platform_key"] != self.adapter.instance_key
            or row["adapter_version"] != self.adapter.adapter_version
            or row["schema_version"] != self.adapter.schema_version
        ):
            raise ValueError("lookup predecessor is incompatible with this adapter")
        material = LookupQueryMaterial.from_json(row["private_query_json"])
        seed_kind = "account" if row["seed_account_id"] is not None else "post"
        seed_id = row["seed_account_id"] or row["seed_post_id"]
        seed = f"{seed_kind}:{seed_id}"
        search_term = material.value if material.strategy.value.startswith("artist_") else None
        replanned = self.plan(
            seed,
            (material.strategy,),
            limits=limits,
            search_term=search_term,
        )
        compatible = next(
            (
                item
                for item in replanned.items
                if item.material.digest == row["material_digest"]
                and item.seed_revision == row["seed_revision"]
            ),
            None,
        )
        if compatible is None:
            raise ValueError("lookup predecessor material is stale")
        continuation = (
            LookupContinuation.from_json(row["continuation_json"])
            if row["continuation_json"] is not None
            else None
        )
        return self._execute_item(
            seed,
            compatible,
            predecessor_run_id=predecessor_run_id,
            initial_continuation=continuation,
        )

    def _execute_item(
        self,
        seed: str,
        item: PlannedLookup,
        *,
        predecessor_run_id: int | None = None,
        initial_continuation: LookupContinuation | None = None,
    ) -> LookupExecutionResult:
        contract = item.item
        if contract.instance != self.adapter.instance_key:
            raise ValueError("lookup plan belongs to another provider instance")
        if contract.adapter_version != self.adapter.adapter_version:
            raise ValueError("lookup plan adapter version is stale")
        if contract.schema_version != self.adapter.schema_version:
            raise ValueError("lookup plan schema version is stale")
        limits = LookupLimits(**dict(contract.limits))
        search_term = (
            item.material.value
            if item.item.strategy.value.startswith("artist_")
            else None
        )
        refreshed = self.plan(
            seed,
            (item.item.strategy,),
            limits=limits,
            search_term=search_term,
        )
        if not any(
            current.plan_digest == item.plan_digest
            and current.material.digest == item.material.digest
            and current.seed_revision == item.seed_revision
            for current in refreshed.items
        ):
            raise ValueError("lookup plan material is stale")
        seed_account_id = item.seed_database_id if contract.seed_kind == "account" else None
        seed_post_id = item.seed_database_id if contract.seed_kind == "post" else None
        started_at = self.clock()
        with self.database.transaction():
            run_id = self.writer.begin_candidate_lookup(
                CandidateLookupRunRecord(
                    platform=contract.instance,
                    instance_host="",
                    strategy=contract.strategy.value,
                    strategy_version=contract.strategy_version,
                    adapter_version=contract.adapter_version,
                    schema_version=contract.schema_version,
                    seed_account_id=seed_account_id,
                    seed_post_id=seed_post_id,
                    seed_revision=item.seed_revision,
                    plan_digest=item.plan_digest,
                    query_kind=item.query_kind,
                    material_digest=item.material.digest,
                    private_query_json=item.material.to_json(),
                    predecessor_run_id=predecessor_run_id,
                    request_limit=limits.requests,
                    page_limit=limits.pages,
                    result_limit=limits.results,
                    time_limit_seconds=limits.seconds,
                    started_at=started_at,
                )
            )
        sync_limits = SyncLimits(
            limits.requests, limits.pages, limits.results, limits.seconds
        )
        executor = BoundedRemoteExecutor(
            self.adapter,
            LookupRequest(contract.strategy, item.material).operation,
            item.material.digest,
            limits=sync_limits,
            continuation=initial_continuation,
            retain_response=lambda response, attempt: self._retain_response(
                run_id, attempt, response
            ),
            commit_page=lambda retained_page, budget: self._commit_retained_page(
                run_id,
                item,
                retained_page,
                budget,
                seed_post_id=seed_post_id,
            ),
            continue_pages=lambda _request, _page: True,
            request_factory=lambda continuation: LookupRequest(
                contract.strategy,
                item.material,
                continuation=continuation,
                limit=min(200, limits.results),
            ),
            fetch_page=lambda request: self.adapter.fetch_lookup(request),
            normalize_page=lambda response, request: self.adapter.normalize_lookup(
                response, request
            ),
            minimum_interval_seconds=self.minimum_interval_seconds,
            maximum_retries=self.maximum_retries,
            monotonic=self.monotonic,
            sleep=self.sleep,
        )
        try:
            execution = executor.execute()
            return self._finish(
                run_id,
                seed,
                contract.strategy.value,
                execution.budget,
                "complete",
                "success",
                predecessor_run_id=predecessor_run_id,
            )
        except BudgetExhausted as error:
            boundary = "result" if error.boundary == "record" else error.boundary
            return self._finish(
                run_id,
                seed,
                contract.strategy.value,
                executor.budget,
                "paused",
                "budget_exhausted",
                predecessor_run_id=predecessor_run_id,
                budget_boundary=boundary,
                diagnostic="candidate lookup budget exhausted",
            )
        except AdapterFailure as error:
            paused = error.outcome in {
                AdapterOutcome.RATE_LIMITED,
                AdapterOutcome.TRANSIENT_PROVIDER,
            }
            return self._finish(
                run_id,
                seed,
                contract.strategy.value,
                executor.budget,
                "paused" if paused else "failed",
                error.outcome.value,
                predecessor_run_id=predecessor_run_id,
                retry_after=error.retry_at,
                diagnostic=error.public_message,
            )
        except (KeyboardInterrupt, SystemExit):
            self._finish(
                run_id,
                seed,
                contract.strategy.value,
                executor.budget,
                "paused",
                "local_persistence",
                predecessor_run_id=predecessor_run_id,
                diagnostic="candidate lookup interrupted before the next committed page",
            )
            raise
        except Exception as error:
            self._finish(
                run_id,
                seed,
                contract.strategy.value,
                executor.budget,
                "failed",
                "local_persistence",
                predecessor_run_id=predecessor_run_id,
                diagnostic=f"local candidate lookup failed ({type(error).__name__})",
            )
            raise

    def _retain_response(
        self, run_id: int, attempt: int, response: ResponseEnvelope
    ) -> int:
        outcome = _response_outcome(response.status_code)
        with self.database.transaction():
            raw_id = self.writer.store_raw(
                RawRecord(
                    payload=response.payload,
                    media_type=response.headers.get("content-type", "application/json").split(
                        ";", 1
                    )[0],
                    object_kind="candidate_lookup",
                    native_id=response.lookup_query_digest,
                    observed_at=response.observed_at,
                    platform=self.adapter.instance_key,
                    adapter_version=response.adapter_version,
                    schema_version=response.schema_version,
                    status=str(response.status_code),
                )
            )
            self.writer.record_candidate_lookup_request(
                CandidateLookupRequestRecord(
                    candidate_lookup_run_id=run_id,
                    attempt_number=attempt,
                    request_identity=response.request_identity,
                    state="complete" if outcome == "success" else "failed",
                    outcome=outcome,
                    status_code=response.status_code,
                    response_size=len(response.payload),
                    raw_observation_id=raw_id,
                    started_at=response.observed_at,
                    observed_at=response.observed_at,
                    finished_at=response.observed_at,
                )
            )
        return raw_id

    def _commit_page(
        self,
        run_id: int,
        item: PlannedLookup,
        page: NormalizedLookupPage,
        response: ResponseEnvelope,
        raw_id: int,
        budget: BudgetTracker,
        *,
        seed_post_id: int | None,
    ) -> None:
        page_number = budget.pages + 1
        with self.database.transaction():
            self.page_writer.write(
                NormalizedPage(page.items),
                observed_at=response.observed_at,
                raw_observation_id=raw_id,
                adapter_version=response.adapter_version,
            )
            for result in page.results:
                interpreted = self.interpreter.interpret(
                    result,
                    seed_post_id=seed_post_id,
                    seed_account_id=(
                        item.seed_database_id if item.item.seed_kind == "account" else None
                    ),
                    strategy=item.item.strategy,
                    raw_observation_id=raw_id,
                    observed_at=response.observed_at,
                    seed_material_digest=item.material.digest,
                    query_values=item.material.values,
                )
                self.writer.record_candidate_lookup_result(
                    CandidateLookupResultRecord(
                        candidate_lookup_run_id=run_id,
                        result_kind=interpreted.result_kind,
                        result_digest=interpreted.result_digest,
                        page_number=page_number,
                        result_order=result.rank,
                        raw_observation_id=raw_id,
                        observed_at=response.observed_at,
                        normalized_post_id=interpreted.normalized_post_id,
                        attribution_entity_id=interpreted.attribution_entity_id,
                        platform_reference_id=interpreted.platform_reference_id,
                        post_candidate_id=interpreted.post_candidate_id,
                        account_candidate_id=interpreted.account_candidate_id,
                        match_evidence_id=interpreted.match_evidence_id,
                        normalized_name=interpreted.normalized_name,
                        match_mode=interpreted.match_mode,
                        explanation=interpreted.explanation,
                    )
                )
            budget.commit_page(page.record_count or 0)
            if page.continuation is not None:
                self.writer.save_candidate_lookup_checkpoint(
                    CandidateLookupCheckpointRecord(
                        candidate_lookup_run_id=run_id,
                        continuation_adapter=page.continuation.adapter,
                        continuation_version=page.continuation.version,
                        continuation_json=page.continuation.to_json(),
                        last_page_identity=response.request_identity,
                        page_count=budget.pages,
                        result_count=budget.records,
                        committed_at=self.clock(),
                    )
                )

    def _commit_retained_page(
        self,
        run_id: int,
        item: PlannedLookup,
        retained_page: RetainedPage,
        budget: BudgetTracker,
        *,
        seed_post_id: int | None,
    ) -> None:
        if not isinstance(retained_page.page, NormalizedLookupPage):
            raise TypeError("lookup executor returned an incompatible normalized page")
        self._commit_page(
            run_id,
            item,
            retained_page.page,
            retained_page.response,
            retained_page.raw_observation_id,
            budget,
            seed_post_id=seed_post_id,
        )

    def _finish(
        self,
        run_id: int,
        seed: str,
        strategy: str,
        budget: BudgetTracker,
        status: str,
        outcome: str,
        *,
        predecessor_run_id: int | None,
        budget_boundary: str | None = None,
        retry_after: str | None = None,
        diagnostic: str | None = None,
    ) -> LookupExecutionResult:
        with self.database.transaction():
            self.writer.finish_candidate_lookup(
                run_id,
                status=status,
                outcome=outcome,
                request_count=budget.requests,
                page_count=budget.pages,
                result_count=budget.records,
                finished_at=self.clock(),
                budget_boundary=budget_boundary,
                retry_after=retry_after,
                diagnostic=diagnostic,
            )
        return LookupExecutionResult(
            run_id,
            self.adapter.instance_key,
            strategy,
            seed,
            status,
            outcome,
            budget.requests,
            budget.pages,
            budget.records,
            predecessor_run_id,
            budget_boundary,
            retry_after,
            diagnostic,
        )


def _response_outcome(status: int) -> str:
    if 200 <= status < 300:
        return "success"
    return {
        401: "authentication_required",
        403: "authorization_denied",
        404: "unavailable",
        410: "deleted",
        429: "rate_limited",
    }.get(status, "transient_provider" if status >= 500 else "malformed_response")
