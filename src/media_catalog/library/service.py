"""Bounded metadata-only execution for explicit artist-library plans."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from media_catalog.adapters import Adapter, AdapterOperation
from media_catalog.adapters.e621.config import PROVIDER_KEY as E621_PROVIDER_KEY
from media_catalog.database import CatalogDatabase
from media_catalog.library.contracts import ExpansionTarget, LibraryExpansionPlan
from media_catalog.library.planning import (
    e621_tag_provider_id,
    plan_library_expansion,
    replan_library_execution,
)
from media_catalog.library.probes import materialize_expansion_plan
from media_catalog.records import LibraryExpansionExecutionRecord, LibraryExpansionPostRecord
from media_catalog.remote_sync import MetadataSyncService, SyncLimits, SyncResult
from media_catalog.remote_sync.executor import RetainedPage
from media_catalog.remote_sync.persistence import NormalizedWriteResult
from media_catalog.remote_sync.service import RemoteSyncOrigin
from media_catalog.writer import CatalogWriter


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class LibraryExpansionResult:
    library_expansion_plan_id: int
    library_expansion_execution_id: int
    target_reference: str
    sync: SyncResult

    def as_dict(self) -> dict[str, object]:
        public_sync = self.sync.as_dict()
        public_sync.pop("target", None)
        return {
            "library_expansion_plan_id": self.library_expansion_plan_id,
            "library_expansion_execution_id": self.library_expansion_execution_id,
            "target": self.target_reference,
            **public_sync,
        }


class ArtistLibraryExpansionService:
    """Validate a saved offline plan, then reuse the metadata page loop."""

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
        self.clock = clock
        self.sync_service = MetadataSyncService(
            database,
            adapter,
            minimum_interval_seconds=minimum_interval_seconds,
            maximum_retries=maximum_retries,
            monotonic=monotonic,
            sleep=sleep,
            clock=clock,
        )

    def run(self, plan: LibraryExpansionPlan) -> LibraryExpansionResult:
        return self._execute(plan, predecessor_execution_id=None)

    def resume(
        self, plan: LibraryExpansionPlan, predecessor_execution_id: int
    ) -> LibraryExpansionResult:
        if predecessor_execution_id <= 0:
            raise ValueError("predecessor expansion execution ID must be positive")
        return self._execute(plan, predecessor_execution_id=predecessor_execution_id)

    def _execute(
        self,
        plan: LibraryExpansionPlan,
        *,
        predecessor_execution_id: int | None,
    ) -> LibraryExpansionResult:
        fresh = self._fresh_plan(plan)
        if fresh.execution_revision != plan.execution_revision:
            raise ValueError("stale library expansion plan; create a new offline plan")
        selected = plan.selected
        if selected is None:
            raise ValueError("library expansion plan has no selected target")
        target = selected.target
        if self.adapter.instance_key != target.provider:
            raise ValueError("library expansion adapter does not match the selected provider")
        if self.adapter.adapter_version != target.capability.adapter_version:
            raise ValueError("library expansion adapter version does not match the plan")
        if self.adapter.schema_version != target.capability.schema_version:
            raise ValueError("library expansion schema version does not match the plan")
        created_at = self.clock()
        parent_run_id: int | None = None
        origin_reference = plan.digest
        if predecessor_execution_id is not None:
            predecessor = self.database.connection.execute(
                """SELECT execution.library_expansion_plan_id, execution.remote_run_id,
                          run.status
                     FROM library_expansion_executions execution
                     JOIN remote_runs run USING(remote_run_id)
                    WHERE execution.library_expansion_execution_id = ?""",
                (predecessor_execution_id,),
            ).fetchone()
            if predecessor is None:
                raise ValueError("predecessor expansion execution is incompatible with the plan")
            predecessor_plan = replan_library_execution(self.database, predecessor_execution_id)
            if predecessor_plan.execution_revision != plan.execution_revision:
                raise ValueError("predecessor expansion execution is incompatible with the plan")
            if predecessor["status"] != "paused":
                raise ValueError("only a paused library expansion execution can be resumed")
            plan_id = int(predecessor["library_expansion_plan_id"])
            parent_run_id = int(predecessor["remote_run_id"])
            origin_reference = predecessor_plan.digest
        else:
            with self.database.transaction():
                plan_id = materialize_expansion_plan(self.writer, plan, created_at=created_at)

        execution_ids: list[int] = []

        def bind_run(writer: CatalogWriter, remote_run_id: int, created_at: str) -> object:
            execution_id = writer.record_library_expansion_execution(
                LibraryExpansionExecutionRecord(
                    plan_id,
                    remote_run_id,
                    "resume" if predecessor_execution_id is not None else "initial",
                    created_at,
                    predecessor_execution_id,
                )
            )
            execution_ids.append(execution_id)
            return execution_id

        def record_page(
            writer: CatalogWriter,
            binding: object,
            retained_page: RetainedPage,
            write_result: NormalizedWriteResult,
        ) -> None:
            if not isinstance(binding, int):
                raise TypeError("library expansion origin binding must be an execution ID")
            execution_id = binding
            for post_id in write_result.post_ids:
                has_media = writer.connection.execute(
                    """SELECT 1 FROM media_occurrences
                        WHERE post_id = ? AND raw_observation_id = ? LIMIT 1""",
                    (post_id, retained_page.raw_observation_id),
                ).fetchone()
                writer.record_library_expansion_post(
                    LibraryExpansionPostRecord(
                        execution_id,
                        post_id,
                        retained_page.response.observed_at,
                        raw_observation_id=retained_page.raw_observation_id,
                        details_required=has_media is None,
                    )
                )

        origin = RemoteSyncOrigin(
            "library_expansion",
            origin_reference,
            bind_run,
            record_page,
        )
        rendered_target = self._render_target(plan)
        sync = self.sync_service.synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            rendered_target,
            limits=SyncLimits(
                plan.limits.requests,
                plan.limits.pages,
                plan.limits.records,
                float(plan.limits.seconds),
            ),
            resume_from_run_id=parent_run_id,
            origin=origin,
        )
        if len(execution_ids) != 1:
            raise RuntimeError("library expansion run association was not created atomically")
        return LibraryExpansionResult(
            plan_id,
            execution_ids[0],
            target.reference,
            sync,
        )

    def _render_target(self, plan: LibraryExpansionPlan) -> str:
        selected = plan.selected
        if selected is None:
            raise ValueError("library expansion plan has no selected target")
        target = selected.target
        if target.kind.value == "account":
            return target.native_id
        if target.provider == E621_PROVIDER_KEY:
            return self._render_e621_attribution_target(target)
        row = self.database.connection.execute(
            """SELECT name FROM attribution_names
                WHERE attribution_entity_id = ? AND name_kind = 'primary'
                ORDER BY observed_at DESC, attribution_name_id DESC LIMIT 1""",
            (target.catalog_id,),
        ).fetchone()
        if row is None:
            raise ValueError("attribution expansion target has no current primary name")
        return str(row["name"])

    def _render_e621_attribution_target(self, target: ExpansionTarget) -> str:
        # Re-resolve the stable tag id from the durable plan material, verify the
        # retained tag is still a current artist tag, and privately return the
        # exact canonical tag name.  Target revision/freshness is already enforced
        # by _fresh_plan before rendering; this re-resolution is the source of the
        # canonical name and a defensive current-category check.
        tag_provider_id = e621_tag_provider_id(target.native_id)
        row = self.database.connection.execute(
            """SELECT tag.name, tag.category, tag.native_category
                 FROM tags tag JOIN platforms platform USING(platform_id)
                WHERE platform.platform_key = ? AND tag.provider_tag_id = ?""",
            (E621_PROVIDER_KEY, tag_provider_id),
        ).fetchone()
        if row is None:
            raise ValueError("e621 expansion target has no current artist tag")
        if str(row["category"]) != "artist" or str(row["native_category"]) != "artist":
            raise ValueError("e621 expansion target tag is no longer a current artist tag")
        return str(row["name"])

    def _fresh_plan(self, plan: LibraryExpansionPlan) -> LibraryExpansionPlan:
        selected = plan.selected
        explicit = selected is not None and selected.source_kind == "explicit_selection"
        return plan_library_expansion(
            self.database,
            plan.seed,
            target=selected.target.reference if explicit else None,
            selection_note=selected.authority.note if explicit else None,
            limits=plan.limits,
        )
