from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from media_catalog.acquisition.planning import (
    AcquisitionPlanPreview,
    AcquisitionSelection,
    check_planned_item_current,
    plan_acquisition,
)
from media_catalog.acquisition.policies import (
    CredentialResolver,
    RequestPolicyError,
    media_request_policy_for_platform,
    safe_failure_diagnostic,
)
from media_catalog.acquisition.publication import verify_publish_and_persist
from media_catalog.acquisition.transfer import (
    AttemptTransition,
    HTTPTransferEngine,
    ResumeState,
    TransferBudget,
    TransferLimits,
)
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    AcquisitionAttemptRecord,
    AcquisitionLimits,
    AcquisitionPartialRecord,
    AcquisitionRunItemRecord,
    AcquisitionRunRecord,
    ManagedRootRecord,
)
from media_catalog.storage.cas import (
    AssetStorage,
    AssetStorageError,
    InspectionLimits,
    RemotePartialState,
)
from media_catalog.writer import CatalogWriter


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class AcquisitionExecutionSummary:
    acquisition_plan_id: int
    acquisition_run_id: int
    status: str
    outcome: str
    planned_count: int
    completed_count: int
    failed_count: int
    deferred_count: int
    received_bytes: int
    quarantined_bytes: int
    counts: dict[str, int]
    items: tuple[dict[str, Any], ...]

    @property
    def complete(self) -> bool:
        return self.status == "complete"

    def as_dict(self) -> dict[str, Any]:
        return {
            "acquisition_plan_id": self.acquisition_plan_id,
            "acquisition_run_id": self.acquisition_run_id,
            "status": self.status,
            "outcome": self.outcome,
            "planned_count": self.planned_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "deferred_count": self.deferred_count,
            "received_bytes": self.received_bytes,
            "quarantined_bytes": self.quarantined_bytes,
            "counts": dict(sorted(self.counts.items())),
            "items": list(self.items),
        }


@dataclass(frozen=True, slots=True)
class _RetryResume:
    resume: ResumeState
    source_record: AcquisitionPartialRecord


def _materialize_plan(
    database: CatalogDatabase,
    writer: CatalogWriter,
    preview: AcquisitionPlanPreview,
) -> tuple[int, dict[str, int]]:
    row = database.connection.execute(
        """SELECT * FROM media_acquisition_plans
           WHERE plan_version = ? AND selection_digest = ?
           ORDER BY acquisition_plan_id LIMIT 1""",
        (preview.plan_version, preview.selection_digest),
    ).fetchone()
    if row is None:
        plan_id = writer.create_acquisition_plan(preview.to_record())
        item_created_at = preview.created_at
    else:
        plan_id = int(row["acquisition_plan_id"])
        expected = preview.counts
        actual = {
            "requested": int(row["requested_count"]),
            "eligible": int(row["eligible_count"]),
            "already_satisfied": int(row["satisfied_count"]),
            "excluded": int(row["excluded_count"]),
            "duplicates": preview.duplicate_count,
        }
        if expected != actual:
            raise ValueError("existing acquisition plan digest has different counts")
        item_created_at = str(row["created_at"])
    item_ids: dict[str, int] = {}
    for item in preview.items:
        item_ids[item.item_key] = writer.add_acquisition_plan_item(
            item.to_record(plan_id, item_created_at)
        )
    return plan_id, item_ids


def _platform_for_occurrence(database: CatalogDatabase, occurrence_id: int) -> str:
    row = database.connection.execute(
        """SELECT platform.platform_key FROM media_occurrences occurrence
           JOIN posts post USING(post_id)
           JOIN platforms platform USING(platform_id)
           WHERE occurrence.media_occurrence_id = ?""",
        (occurrence_id,),
    ).fetchone()
    if row is None:
        raise ValueError("media occurrence is missing")
    return str(row[0])


def _terminal_item_state(outcome: str, transfer_state: str) -> str:
    if outcome == "hash_mismatch":
        return "quarantined"
    if outcome == "stale_target":
        return "stale"
    if transfer_state == "interrupted":
        return "interrupted"
    return "failed"


def _storage_outcome(error: BaseException) -> str:
    category = getattr(error, "category", "storage_failure")
    return {
        "inspection_failed": "inspection_failure",
        "storage_integrity_failed": "storage_integrity_failure",
        "limit_exceeded": "response_too_large",
    }.get(category, category if category in {"hash_mismatch"} else "storage_failure")


class _DurableTransferState:
    def __init__(
        self,
        database: CatalogDatabase,
        writer: CatalogWriter,
        *,
        run_item_id: int,
        managed_root_id: int,
        managed_root_identity: str,
        policy_key: str,
        policy_version: str,
        clock: Callable[[], str],
    ) -> None:
        self.database = database
        self.writer = writer
        self.run_item_id = run_item_id
        self.managed_root_id = managed_root_id
        self.managed_root_identity = managed_root_identity
        self.policy_key = policy_key
        self.policy_version = policy_version
        self.clock = clock
        self.started_attempts: dict[int, str] = {}
        self.attempt_ids: dict[int, int] = {}
        self.partial_record: AcquisitionPartialRecord | None = None

    def observe_attempt(self, transition: AttemptTransition) -> None:
        timestamp = self.clock()
        if transition.state == "running":
            self.started_attempts[transition.attempt_number] = timestamp
        record = AcquisitionAttemptRecord(
            self.run_item_id,
            transition.attempt_number,
            transition.state,
            transition.request_identity,
            self.policy_key,
            self.policy_version,
            self.started_attempts[transition.attempt_number],
            outcome=transition.outcome,
            retryable=transition.retryable,
            status_code=transition.status_code,
            redirect_count=transition.redirect_count,
            response_etag=transition.response_etag,
            received_bytes=transition.received_bytes,
            response_size=transition.response_size,
            diagnostic=transition.diagnostic,
            finished_at=timestamp if transition.state != "running" else None,
        )
        with self.database.transaction():
            self.attempt_ids[transition.attempt_number] = self.writer.record_acquisition_attempt(
                record
            )

    def _finish_current_partial(self, state: str, timestamp: str) -> None:
        current = self.partial_record
        if current is None:
            return
        with self.database.transaction():
            self.writer.save_acquisition_partial(
                AcquisitionPartialRecord(
                    current.acquisition_run_item_id,
                    current.managed_root_id,
                    current.staging_name,
                    current.request_identity,
                    current.byte_count,
                    current.prefix_sha256,
                    current.prefix_md5,
                    state,
                    current.created_at,
                    timestamp,
                    current.managed_root_identity,
                    current.staging_device,
                    current.staging_inode,
                    current.strong_etag,
                    current.acquisition_partial_id,
                )
            )

    def observe_partial(self, _attempt_number: int, resume: ResumeState) -> None:
        timestamp = self.clock()
        state = resume.partial
        if (
            self.partial_record is not None
            and self.partial_record.staging_name != state.staging_name
        ):
            self._finish_current_partial("discarded", timestamp)
            self.partial_record = None
        current = self.partial_record
        record = AcquisitionPartialRecord(
            self.run_item_id,
            self.managed_root_id,
            state.staging_name,
            state.request_identity,
            state.byte_count,
            state.prefix_sha256,
            state.prefix_md5,
            "active",
            current.created_at if current else timestamp,
            timestamp,
            self.managed_root_identity,
            state.staging_identity[0],
            state.staging_identity[1],
            resume.strong_etag,
            current.acquisition_partial_id if current else None,
        )
        with self.database.transaction():
            partial_id = self.writer.save_acquisition_partial(record)
        self.partial_record = AcquisitionPartialRecord(
            record.acquisition_run_item_id,
            record.managed_root_id,
            record.staging_name,
            record.request_identity,
            record.byte_count,
            record.prefix_sha256,
            record.prefix_md5,
            record.state,
            record.created_at,
            record.updated_at,
            record.managed_root_identity,
            record.staging_device,
            record.staging_inode,
            record.strong_etag,
            partial_id,
        )

    def claim_resume(
        self,
        resume: ResumeState,
        source_record: AcquisitionPartialRecord,
    ) -> None:
        timestamp = self.clock()
        with self.database.transaction():
            self.writer.save_acquisition_partial(
                AcquisitionPartialRecord(
                    source_record.acquisition_run_item_id,
                    source_record.managed_root_id,
                    source_record.staging_name,
                    source_record.request_identity,
                    source_record.byte_count,
                    source_record.prefix_sha256,
                    source_record.prefix_md5,
                    "consumed",
                    source_record.created_at,
                    timestamp,
                    source_record.managed_root_identity,
                    source_record.staging_device,
                    source_record.staging_inode,
                    source_record.strong_etag,
                    source_record.acquisition_partial_id,
                )
            )
            claimed = AcquisitionPartialRecord(
                self.run_item_id,
                self.managed_root_id,
                resume.partial.staging_name,
                resume.partial.request_identity,
                resume.partial.byte_count,
                resume.partial.prefix_sha256,
                resume.partial.prefix_md5,
                "active",
                timestamp,
                timestamp,
                self.managed_root_identity,
                resume.partial.staging_identity[0],
                resume.partial.staging_identity[1],
                resume.strong_etag,
            )
            partial_id = self.writer.save_acquisition_partial(claimed)
        self.partial_record = AcquisitionPartialRecord(
            claimed.acquisition_run_item_id,
            claimed.managed_root_id,
            claimed.staging_name,
            claimed.request_identity,
            claimed.byte_count,
            claimed.prefix_sha256,
            claimed.prefix_md5,
            claimed.state,
            claimed.created_at,
            claimed.updated_at,
            claimed.managed_root_identity,
            claimed.staging_device,
            claimed.staging_inode,
            claimed.strong_etag,
            partial_id,
        )

    def finish_partial(self, *, complete: bool, retained: bool) -> None:
        if self.partial_record is not None and not retained:
            self._finish_current_partial("consumed" if complete else "discarded", self.clock())

    @property
    def last_attempt_id(self) -> int | None:
        return self.attempt_ids[max(self.attempt_ids)] if self.attempt_ids else None


class AcquisitionService:
    """Public serial facade for explicit remote-media acquisition."""

    def __init__(
        self,
        database: CatalogDatabase,
        transfer_engine: HTTPTransferEngine,
        managed_root: str | Path,
        *,
        inspection_limits: InspectionLimits | None = None,
        credential_resolver: CredentialResolver | None = None,
        transfer_chunk_size: int = 64 * 1024,
        clock: Callable[[], str] = _now,
    ) -> None:
        self.database = database
        self.transfer_engine = transfer_engine
        self.managed_root = Path(managed_root).absolute()
        self.inspection_limits = inspection_limits or InspectionLimits()
        self.credential_resolver = credential_resolver
        if transfer_chunk_size <= 0:
            raise ValueError("transfer chunk size must be positive")
        self.transfer_chunk_size = transfer_chunk_size
        self.clock = clock

    def execute(
        self,
        preview: AcquisitionPlanPreview,
        limits: AcquisitionLimits,
        *,
        resumed_from_run_id: int | None = None,
        _resumes: dict[str, _RetryResume] | None = None,
    ) -> AcquisitionExecutionSummary:
        if limits.concurrency != 1:
            raise ValueError("the initial acquisition executor requires concurrency one")
        if limits.max_redirects <= 0:
            raise ValueError("maximum redirects must be positive")
        if len(preview.items) > limits.max_items:
            raise ValueError("acquisition preview exceeds the execution item limit")
        writer = CatalogWriter(self.database)
        with (
            AssetStorage.for_remote(
                self.managed_root,
                limits=self.inspection_limits,
            ) as storage,
            storage.lock(),
        ):
            root_identity = f"{storage.media.identity[0]}:{storage.media.identity[1]}"
            started_at = self.clock()
            with self.database.transaction():
                managed_root_id = writer.register_managed_root(
                    ManagedRootRecord(
                        "managed",
                        root_identity,
                        self.managed_root.name or "managed",
                        str(self.managed_root),
                        started_at,
                    )
                )
                plan_id, item_ids = _materialize_plan(self.database, writer, preview)
                run_id = writer.begin_acquisition_run(
                    AcquisitionRunRecord(
                        plan_id,
                        managed_root_id,
                        limits,
                        len(preview.items),
                        started_at,
                        resumed_from_run_id,
                    )
                )

            budget = TransferBudget(limits.max_total_bytes)
            run_deadline = self.transfer_engine.clock() + limits.max_seconds
            counts: Counter[str] = Counter()
            result_items: list[dict[str, Any]] = []
            completed = failed = deferred = quarantined_bytes = 0

            for item in preview.items:
                created_at = self.clock()
                plan_item_id = item_ids[item.item_key]
                with self.database.transaction():
                    run_item_id = writer.record_acquisition_run_item(
                        AcquisitionRunItemRecord(
                            run_id, plan_item_id, "pending", created_at, created_at
                        )
                    )

                prior = self.database.connection.execute(
                    """SELECT asset_id FROM media_acquisition_run_items
                       WHERE acquisition_plan_item_id = ?
                         AND state IN ('complete', 'satisfied') AND asset_id IS NOT NULL
                       ORDER BY acquisition_run_item_id LIMIT 1""",
                    (plan_item_id,),
                ).fetchone()
                satisfied_asset = (
                    int(prior[0])
                    if prior is not None
                    else item.satisfied_asset_id
                    if item.eligibility == "already_satisfied"
                    else None
                )
                if satisfied_asset is not None:
                    with self.database.transaction():
                        writer.record_acquisition_run_item(
                            AcquisitionRunItemRecord(
                                run_id,
                                plan_item_id,
                                "satisfied",
                                created_at,
                                self.clock(),
                                outcome="already_satisfied",
                                asset_id=satisfied_asset,
                            )
                        )
                    completed += 1
                    counts["already_satisfied"] += 1
                    result_items.append(
                        {
                            "item_key": item.item_key,
                            "state": "satisfied",
                            "outcome": "already_satisfied",
                            "asset_id": satisfied_asset,
                        }
                    )
                    continue
                if item.eligibility != "eligible":
                    outcome = (
                        "unavailable"
                        if item.exclusion_reason == "unavailable_occurrence"
                        else "policy_failure"
                    )
                    with self.database.transaction():
                        writer.record_acquisition_run_item(
                            AcquisitionRunItemRecord(
                                run_id,
                                plan_item_id,
                                "failed",
                                created_at,
                                self.clock(),
                                outcome=outcome,
                                diagnostic=safe_failure_diagnostic("catalog", outcome),
                            )
                        )
                    failed += 1
                    counts[outcome] += 1
                    result_items.append(
                        {"item_key": item.item_key, "state": "failed", "outcome": outcome}
                    )
                    continue
                if budget.remaining_bytes == 0 or self.transfer_engine.clock() >= run_deadline:
                    with self.database.transaction():
                        writer.record_acquisition_run_item(
                            AcquisitionRunItemRecord(
                                run_id,
                                plan_item_id,
                                "deferred",
                                created_at,
                                self.clock(),
                                outcome="budget_exhausted",
                                retryable=True,
                                diagnostic=safe_failure_diagnostic("catalog", "budget_exhausted"),
                            )
                        )
                    deferred += 1
                    counts["budget_exhausted"] += 1
                    result_items.append(
                        {
                            "item_key": item.item_key,
                            "state": "deferred",
                            "outcome": "budget_exhausted",
                        }
                    )
                    continue
                current, _reason = check_planned_item_current(self.database, item)
                if not current:
                    with self.database.transaction():
                        writer.record_acquisition_run_item(
                            AcquisitionRunItemRecord(
                                run_id,
                                plan_item_id,
                                "stale",
                                created_at,
                                self.clock(),
                                outcome="stale_target",
                                diagnostic=safe_failure_diagnostic("catalog", "stale_target"),
                            )
                        )
                    failed += 1
                    counts["stale_target"] += 1
                    result_items.append(
                        {
                            "item_key": item.item_key,
                            "state": "stale",
                            "outcome": "stale_target",
                        }
                    )
                    continue

                platform = _platform_for_occurrence(self.database, item.media_occurrence_id)
                policy = media_request_policy_for_platform(platform)
                if (
                    policy is None
                    or item.request_policy != policy.identity
                    or item.selected_url is None
                ):
                    outcome = "policy_failure"
                    with self.database.transaction():
                        writer.record_acquisition_run_item(
                            AcquisitionRunItemRecord(
                                run_id,
                                plan_item_id,
                                "failed",
                                created_at,
                                self.clock(),
                                outcome=outcome,
                                diagnostic=safe_failure_diagnostic(platform, outcome),
                            )
                        )
                    failed += 1
                    counts[outcome] += 1
                    continue
                try:
                    recipe = policy.recipe(
                        media_occurrence_id=item.media_occurrence_id,
                        variant_key=item.variant_key,
                        selected_url=item.selected_url,
                    )
                except RequestPolicyError:
                    # A plan may have been created before a provider URL was
                    # found to violate its installed policy. Keep the failure
                    # bounded and durable, and never let the untrusted target
                    # escape through an exception or reach the transport.
                    outcome = "policy_failure"
                    with self.database.transaction():
                        writer.record_acquisition_run_item(
                            AcquisitionRunItemRecord(
                                run_id,
                                plan_item_id,
                                "failed",
                                created_at,
                                self.clock(),
                                outcome=outcome,
                                diagnostic=safe_failure_diagnostic(platform, outcome),
                            )
                        )
                    failed += 1
                    counts[outcome] += 1
                    result_items.append(
                        {"item_key": item.item_key, "state": "failed", "outcome": outcome}
                    )
                    continue
                with self.database.transaction():
                    writer.record_acquisition_run_item(
                        AcquisitionRunItemRecord(
                            run_id, plan_item_id, "running", created_at, self.clock()
                        )
                    )
                orphan = self.database.connection.execute(
                    """SELECT sha256, md5 FROM media_acquisition_run_items
                       WHERE acquisition_plan_item_id = ?
                         AND acquisition_run_item_id != ? AND asset_id IS NULL
                         AND sha256 IS NOT NULL
                       ORDER BY acquisition_run_item_id DESC LIMIT 1""",
                    (plan_item_id, run_item_id),
                ).fetchone()
                if orphan is not None:
                    try:
                        reconciled = storage.stage_existing_cas(
                            str(orphan["sha256"]), expected_md5=orphan["md5"]
                        )
                    except AssetStorageError as error:
                        outcome = _storage_outcome(error)
                        with self.database.transaction():
                            writer.record_acquisition_run_item(
                                AcquisitionRunItemRecord(
                                    run_id,
                                    plan_item_id,
                                    "failed",
                                    created_at,
                                    self.clock(),
                                    outcome=outcome,
                                    sha256=orphan["sha256"],
                                    md5=orphan["md5"],
                                    diagnostic=safe_failure_diagnostic(platform, outcome),
                                )
                            )
                        failed += 1
                        counts[outcome] += 1
                        result_items.append(
                            {
                                "item_key": item.item_key,
                                "state": "failed",
                                "outcome": outcome,
                            }
                        )
                        continue
                    if reconciled is not None:
                        publication = verify_publish_and_persist(
                            self.database,
                            storage,
                            item=item,
                            staged=reconciled,
                            run_item_id=run_item_id,
                            acquisition_attempt_id=None,
                            managed_root_id=managed_root_id,
                            request_identity=recipe.request_identity,
                            max_quarantine_bytes=max(
                                0, limits.max_quarantine_bytes - quarantined_bytes
                            ),
                            clock=self.clock,
                        )
                        outcome = (
                            publication.outcome
                            if publication.outcome == "hash_mismatch"
                            else "existing"
                        )
                        state = "quarantined" if outcome == "hash_mismatch" else "complete"
                        if state == "complete":
                            completed += 1
                        else:
                            failed += 1
                            quarantined_bytes += publication.quarantined_bytes
                        with self.database.transaction():
                            writer.record_acquisition_run_item(
                                AcquisitionRunItemRecord(
                                    run_id,
                                    plan_item_id,
                                    state,
                                    created_at,
                                    self.clock(),
                                    outcome=outcome,
                                    asset_id=publication.asset_id,
                                    sha256=publication.inspection.sha256,
                                    md5=publication.inspection.md5,
                                )
                            )
                        counts[outcome] += 1
                        result_items.append(
                            {
                                "item_key": item.item_key,
                                "state": state,
                                "outcome": outcome,
                                "asset_id": publication.asset_id,
                                "sha256": publication.inspection.sha256,
                            }
                        )
                        continue
                durable = _DurableTransferState(
                    self.database,
                    writer,
                    run_item_id=run_item_id,
                    managed_root_id=managed_root_id,
                    managed_root_identity=root_identity,
                    policy_key=recipe.policy.key,
                    policy_version=recipe.policy.version,
                    clock=self.clock,
                )
                retry_resume = (_resumes or {}).get(item.item_key)
                if retry_resume is not None:
                    durable.claim_resume(retry_resume.resume, retry_resume.source_record)

                remaining_seconds = max(0.001, run_deadline - self.transfer_engine.clock())
                transfer = self.transfer_engine.transfer(
                    recipe,
                    storage,
                    limits=TransferLimits(
                        limits.max_item_bytes,
                        limits.max_attempts_per_item,
                        remaining_seconds,
                        limits.max_redirects,
                        chunk_size=self.transfer_chunk_size,
                    ),
                    budget=budget,
                    credential_resolver=self.credential_resolver,
                    observer=durable.observe_attempt,
                    partial_observer=durable.observe_partial,
                    resume=retry_resume.resume if retry_resume else None,
                )
                durable.finish_partial(
                    complete=transfer.complete, retained=transfer.resume is not None
                )

                if not transfer.complete or transfer.staged is None:
                    state = _terminal_item_state(transfer.outcome, transfer.state)
                    with self.database.transaction():
                        writer.record_acquisition_run_item(
                            AcquisitionRunItemRecord(
                                run_id,
                                plan_item_id,
                                state,
                                created_at,
                                self.clock(),
                                outcome=transfer.outcome,
                                retryable=transfer.retryable,
                                attempt_count=len(transfer.attempts),
                                received_bytes=transfer.received_bytes,
                                diagnostic=transfer.diagnostic,
                            )
                        )
                    if state == "interrupted":
                        deferred += 1
                    else:
                        failed += 1
                    counts[transfer.outcome] += 1
                    result_items.append(
                        {
                            "item_key": item.item_key,
                            "state": state,
                            "outcome": transfer.outcome,
                        }
                    )
                    continue

                try:
                    publication = verify_publish_and_persist(
                        self.database,
                        storage,
                        item=item,
                        staged=transfer.staged,
                        run_item_id=run_item_id,
                        acquisition_attempt_id=durable.last_attempt_id,
                        managed_root_id=managed_root_id,
                        request_identity=recipe.request_identity,
                        max_quarantine_bytes=max(
                            0, limits.max_quarantine_bytes - quarantined_bytes
                        ),
                        clock=self.clock,
                    )
                except (AssetStorageError, OSError) as error:
                    staged = getattr(error, "staged", transfer.staged)
                    with suppress(Exception):
                        storage.cleanup_staging(staged)
                    outcome = _storage_outcome(error)
                    with self.database.transaction():
                        row = self.database.connection.execute(
                            "SELECT sha256, md5 FROM media_acquisition_run_items "
                            "WHERE acquisition_run_item_id = ?",
                            (run_item_id,),
                        ).fetchone()
                        writer.record_acquisition_run_item(
                            AcquisitionRunItemRecord(
                                run_id,
                                plan_item_id,
                                "failed",
                                created_at,
                                self.clock(),
                                outcome=outcome,
                                attempt_count=len(transfer.attempts),
                                received_bytes=transfer.received_bytes,
                                sha256=row["sha256"],
                                md5=row["md5"],
                                diagnostic=safe_failure_diagnostic(platform, outcome),
                            )
                        )
                    failed += 1
                    counts[outcome] += 1
                    continue

                if publication.outcome == "hash_mismatch":
                    state = "quarantined"
                    failed += 1
                    quarantined_bytes += publication.quarantined_bytes
                else:
                    state = "complete"
                    completed += 1
                with self.database.transaction():
                    writer.record_acquisition_run_item(
                        AcquisitionRunItemRecord(
                            run_id,
                            plan_item_id,
                            state,
                            created_at,
                            self.clock(),
                            outcome=publication.outcome,
                            attempt_count=len(transfer.attempts),
                            received_bytes=transfer.received_bytes,
                            asset_id=publication.asset_id,
                            sha256=publication.inspection.sha256,
                            md5=publication.inspection.md5,
                        )
                    )
                counts[publication.outcome] += 1
                result_items.append(
                    {
                        "item_key": item.item_key,
                        "state": state,
                        "outcome": publication.outcome,
                        "asset_id": publication.asset_id,
                        "sha256": publication.inspection.sha256,
                    }
                )

            if failed == 0 and deferred == 0:
                status, outcome = "complete", "success"
            elif completed > 0:
                status, outcome = "partial", "partial"
            elif deferred > 0 and failed == 0:
                status, outcome = "partial", "interrupted"
            elif counts["stale_target"]:
                status, outcome = "failed", "stale"
            elif counts["hash_mismatch"]:
                status, outcome = "failed", "quarantined"
            elif counts["budget_exhausted"]:
                status, outcome = "failed", "budget_exhausted"
            else:
                status, outcome = "failed", "failed"
            with self.database.transaction():
                writer.finish_acquisition_run(
                    run_id,
                    status=status,
                    outcome=outcome,
                    completed_count=completed,
                    failed_count=failed,
                    deferred_count=deferred,
                    received_bytes=budget.used_bytes,
                    quarantined_bytes=quarantined_bytes,
                    finished_at=self.clock(),
                )
            return AcquisitionExecutionSummary(
                plan_id,
                run_id,
                status,
                outcome,
                len(preview.items),
                completed,
                failed,
                deferred,
                budget.used_bytes,
                quarantined_bytes,
                dict(counts),
                tuple(result_items),
            )

    def retry(
        self,
        acquisition_run_id: int,
        *,
        limits: AcquisitionLimits | None = None,
        include_nonretryable: bool = False,
    ) -> AcquisitionExecutionSummary:
        if acquisition_run_id <= 0:
            raise ValueError("acquisition run id must be positive")
        self.recover_interrupted(acquisition_run_id)
        run = self.database.connection.execute(
            "SELECT * FROM media_acquisition_runs WHERE acquisition_run_id = ?",
            (acquisition_run_id,),
        ).fetchone()
        if run is None:
            raise ValueError("acquisition run does not exist")
        if limits is None:
            limits = AcquisitionLimits(
                int(run["max_items"]),
                int(run["max_item_bytes"]),
                int(run["max_total_bytes"]),
                int(run["max_attempts_per_item"]),
                int(run["max_seconds"]),
                int(run["max_redirects"]),
                int(run["max_quarantine_bytes"]),
                int(run["concurrency"]),
            )
        condition = (
            "ari.state NOT IN ('complete', 'satisfied')"
            if include_nonretryable
            else "ari.retryable = 1 AND ari.state IN ('failed', 'interrupted', 'deferred')"
        )
        rows = list(
            self.database.connection.execute(
                f"""SELECT ari.*, api.item_key, api.media_occurrence_id, api.variant_key
                    FROM media_acquisition_run_items ari
                    JOIN media_acquisition_plan_items api USING(acquisition_plan_item_id)
                    WHERE ari.acquisition_run_id = ? AND {condition}
                    ORDER BY ari.acquisition_run_item_id""",
                (acquisition_run_id,),
            )
        )
        if not rows:
            raise ValueError("acquisition run has no selected retry items")
        selections = [
            AcquisitionSelection(int(row["media_occurrence_id"]), str(row["variant_key"]))
            for row in rows
        ]
        preview = plan_acquisition(
            self.database,
            selections,
            max_items=limits.max_items,
            clock=self.clock,
        )
        resumes: dict[str, _RetryResume] = {}
        retry_rows = {int(row["acquisition_run_item_id"]): row for row in rows}
        for source_run_item_id, source_item in retry_rows.items():
            partial = self.database.connection.execute(
                """SELECT p.*,
                          (SELECT response_size FROM media_acquisition_attempts a
                           WHERE a.acquisition_run_item_id = p.acquisition_run_item_id
                           ORDER BY attempt_number DESC LIMIT 1) AS response_size
                   FROM media_acquisition_partials p
                   WHERE p.acquisition_run_item_id = ? AND p.state = 'active'
                     AND p.strong_etag IS NOT NULL
                   ORDER BY p.acquisition_partial_id DESC LIMIT 1""",
                (source_run_item_id,),
            ).fetchone()
            if partial is None:
                continue
            managed_identity = str(partial["managed_root_identity"])
            try:
                managed_device, managed_inode = (
                    int(value) for value in managed_identity.split(":", 1)
                )
            except (TypeError, ValueError) as error:
                raise ValueError("persisted partial managed-root identity is invalid") from error
            remote = RemotePartialState(
                str(partial["staging_name"]),
                str(partial["request_identity"]),
                (managed_device, managed_inode),
                (int(partial["staging_device"]), int(partial["staging_inode"])),
                int(partial["byte_count"]),
                str(partial["prefix_sha256"]),
                str(partial["prefix_md5"]),
            )
            resume = ResumeState(
                remote,
                str(partial["strong_etag"]),
                int(partial["response_size"]) if partial["response_size"] is not None else None,
            )
            record = AcquisitionPartialRecord(
                source_run_item_id,
                int(partial["managed_root_id"]),
                str(partial["staging_name"]),
                str(partial["request_identity"]),
                int(partial["byte_count"]),
                str(partial["prefix_sha256"]),
                str(partial["prefix_md5"]),
                str(partial["state"]),
                str(partial["created_at"]),
                str(partial["updated_at"]),
                managed_identity,
                int(partial["staging_device"]),
                int(partial["staging_inode"]),
                str(partial["strong_etag"]),
                int(partial["acquisition_partial_id"]),
            )
            resumes[str(source_item["item_key"])] = _RetryResume(resume, record)
        return self.execute(
            preview,
            limits,
            resumed_from_run_id=acquisition_run_id,
            _resumes=resumes,
        )

    def recover_interrupted(self, acquisition_run_id: int) -> bool:
        """Durably close a run left active by process interruption."""

        if acquisition_run_id <= 0:
            raise ValueError("acquisition run id must be positive")
        run = self.database.connection.execute(
            "SELECT * FROM media_acquisition_runs WHERE acquisition_run_id = ?",
            (acquisition_run_id,),
        ).fetchone()
        if run is None:
            raise ValueError("acquisition run does not exist")
        if run["status"] != "running":
            return False
        writer = CatalogWriter(self.database)
        timestamp = self.clock()
        with self.database.transaction():
            running_attempts = list(
                self.database.connection.execute(
                    """SELECT attempt.* FROM media_acquisition_attempts attempt
                       JOIN media_acquisition_run_items item USING(acquisition_run_item_id)
                       WHERE item.acquisition_run_id = ? AND attempt.state = 'running'
                       ORDER BY attempt.acquisition_attempt_id""",
                    (acquisition_run_id,),
                )
            )
            for attempt in running_attempts:
                writer.record_acquisition_attempt(
                    AcquisitionAttemptRecord(
                        int(attempt["acquisition_run_item_id"]),
                        int(attempt["attempt_number"]),
                        "interrupted",
                        str(attempt["request_identity"]),
                        str(attempt["request_policy_key"]),
                        str(attempt["request_policy_version"]),
                        str(attempt["started_at"]),
                        outcome="interrupted",
                        retryable=True,
                        status_code=attempt["status_code"],
                        redirect_count=int(attempt["redirect_count"]),
                        response_etag=attempt["response_etag"],
                        received_bytes=int(attempt["received_bytes"]),
                        response_size=attempt["response_size"],
                        diagnostic=safe_failure_diagnostic("catalog", "interrupted"),
                        finished_at=timestamp,
                    )
                )
            active_items = list(
                self.database.connection.execute(
                    """SELECT item.*,
                              (SELECT MAX(byte_count) FROM media_acquisition_partials p
                               WHERE p.acquisition_run_item_id = item.acquisition_run_item_id
                                 AND p.state = 'active') AS partial_bytes
                       FROM media_acquisition_run_items item
                       WHERE item.acquisition_run_id = ?
                         AND item.state IN ('pending', 'running')""",
                    (acquisition_run_id,),
                )
            )
            for item in active_items:
                received = max(int(item["received_bytes"]), int(item["partial_bytes"] or 0))
                attempt_count = int(
                    self.database.connection.execute(
                        "SELECT COUNT(*) FROM media_acquisition_attempts "
                        "WHERE acquisition_run_item_id = ?",
                        (item["acquisition_run_item_id"],),
                    ).fetchone()[0]
                )
                writer.record_acquisition_run_item(
                    AcquisitionRunItemRecord(
                        acquisition_run_id,
                        int(item["acquisition_plan_item_id"]),
                        "interrupted",
                        str(item["created_at"]),
                        timestamp,
                        outcome="interrupted",
                        retryable=True,
                        attempt_count=attempt_count,
                        received_bytes=received,
                        sha256=item["sha256"],
                        md5=item["md5"],
                        diagnostic=safe_failure_diagnostic("catalog", "interrupted"),
                    )
                )
            states = list(
                self.database.connection.execute(
                    "SELECT state, received_bytes FROM media_acquisition_run_items "
                    "WHERE acquisition_run_id = ?",
                    (acquisition_run_id,),
                )
            )
            completed = sum(row["state"] in {"complete", "satisfied"} for row in states)
            deferred = sum(row["state"] in {"interrupted", "deferred"} for row in states)
            failed = len(states) - completed - deferred
            writer.finish_acquisition_run(
                acquisition_run_id,
                status="partial" if completed or deferred else "failed",
                outcome="interrupted",
                completed_count=completed,
                failed_count=failed,
                deferred_count=deferred,
                received_bytes=sum(int(row["received_bytes"]) for row in states),
                quarantined_bytes=int(run["quarantined_bytes"]),
                finished_at=timestamp,
                diagnostic=safe_failure_diagnostic("catalog", "interrupted"),
            )
        return True
