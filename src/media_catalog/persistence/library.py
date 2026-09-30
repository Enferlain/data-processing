from __future__ import annotations

import sqlite3

from media_catalog.database import CatalogDatabase
from media_catalog.persistence.support import caller_connection, inserted_id, platform_id
from media_catalog.records import (
    LibraryExpansionExecutionRecord,
    LibraryExpansionPlanRecord,
    LibraryExpansionPostRecord,
    LibraryExpansionProbeRecord,
)


class LibraryWrites:
    def __init__(self, database: CatalogDatabase) -> None:
        self.connection = caller_connection(database)

    def record_library_expansion_plan(self, record: LibraryExpansionPlanRecord) -> int:
        self.connection.execute(
            """INSERT INTO library_expansion_plans (
                   platform_id, instance_host, target_kind, target_account_id,
                   target_attribution_id, seed_account_id, seed_post_id, seed_revision,
                   authority_mode, authority_reference, selection_note, capability_key,
                   capability_version, target_native_id, target_revision, adapter_version,
                   schema_version, source_revision, request_limit, page_limit, record_limit,
                   time_limit_seconds, estimate_state, estimate_count, estimate_observed_at,
                   estimate_source, exclusions_json, plan_digest, material_digest, created_at
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?)
               ON CONFLICT(plan_digest) DO NOTHING""",
            (
                platform_id(self.connection, record.platform),
                record.instance_host,
                record.target_kind,
                record.target_account_id,
                record.target_attribution_id,
                record.seed_account_id,
                record.seed_post_id,
                record.seed_revision,
                record.authority_mode,
                record.authority_reference,
                record.selection_note,
                record.capability_key,
                record.capability_version,
                record.target_native_id,
                record.target_revision,
                record.adapter_version,
                record.schema_version,
                record.source_revision,
                record.request_limit,
                record.page_limit,
                record.record_limit,
                record.time_limit_seconds,
                record.estimate_state,
                record.estimate_count,
                record.estimate_observed_at,
                record.estimate_source,
                record.exclusions_json,
                record.plan_digest,
                record.material_digest,
                record.created_at,
            ),
        )
        row = self.connection.execute(
            "SELECT * FROM library_expansion_plans WHERE plan_digest = ?",
            (record.plan_digest,),
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("library expansion plan was not recorded")
        expected = {
            "platform_id": platform_id(self.connection, record.platform),
            "instance_host": record.instance_host,
            "target_kind": record.target_kind,
            "target_account_id": record.target_account_id,
            "target_attribution_id": record.target_attribution_id,
            "seed_account_id": record.seed_account_id,
            "seed_post_id": record.seed_post_id,
            "seed_revision": record.seed_revision,
            "authority_mode": record.authority_mode,
            "authority_reference": record.authority_reference,
            "selection_note": record.selection_note,
            "capability_key": record.capability_key,
            "capability_version": record.capability_version,
            "target_native_id": record.target_native_id,
            "target_revision": record.target_revision,
            "adapter_version": record.adapter_version,
            "schema_version": record.schema_version,
            "source_revision": record.source_revision,
            "request_limit": record.request_limit,
            "page_limit": record.page_limit,
            "record_limit": record.record_limit,
            "time_limit_seconds": record.time_limit_seconds,
            "estimate_state": record.estimate_state,
            "estimate_count": record.estimate_count,
            "estimate_observed_at": record.estimate_observed_at,
            "estimate_source": record.estimate_source,
            "exclusions_json": record.exclusions_json,
            "material_digest": record.material_digest,
            "created_at": record.created_at,
        }
        if any(row[name] != value for name, value in expected.items()):
            raise ValueError("library expansion plan digest already has different material")
        return int(row["library_expansion_plan_id"])

    def record_library_expansion_probe(self, record: LibraryExpansionProbeRecord) -> int:
        cursor = self.connection.execute(
            """INSERT INTO library_expansion_probes (
                   library_expansion_plan_id, capability_key, capability_version,
                   adapter_version, schema_version, request_limit, time_limit_seconds,
                   outcome, status_code, count_value, retry_after, request_identity,
                   raw_observation_id, diagnostic_summary, requested_at, observed_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.library_expansion_plan_id,
                record.capability_key,
                record.capability_version,
                record.adapter_version,
                record.schema_version,
                record.request_limit,
                record.time_limit_seconds,
                record.outcome,
                record.status_code,
                record.count_value,
                record.retry_after,
                record.request_identity,
                record.raw_observation_id,
                record.diagnostic_summary,
                record.requested_at,
                record.observed_at,
            ),
        )
        return inserted_id(cursor)

    def record_library_expansion_execution(self, record: LibraryExpansionExecutionRecord) -> int:
        cursor = self.connection.execute(
            """INSERT INTO library_expansion_executions (
                   library_expansion_plan_id, remote_run_id, predecessor_execution_id,
                   execution_kind, created_at
               ) VALUES (?, ?, ?, ?, ?)""",
            (
                record.library_expansion_plan_id,
                record.remote_run_id,
                record.predecessor_execution_id,
                record.execution_kind,
                record.created_at,
            ),
        )
        return inserted_id(cursor)

    def record_library_expansion_post(self, record: LibraryExpansionPostRecord) -> int:
        self.connection.execute(
            """INSERT INTO library_expansion_posts (
                   library_expansion_execution_id, post_id, raw_observation_id,
                   details_required, observed_at
               ) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(library_expansion_execution_id, post_id) DO NOTHING""",
            (
                record.library_expansion_execution_id,
                record.post_id,
                record.raw_observation_id,
                int(record.details_required),
                record.observed_at,
            ),
        )
        row = self.connection.execute(
            """SELECT * FROM library_expansion_posts
               WHERE library_expansion_execution_id = ? AND post_id = ?""",
            (record.library_expansion_execution_id, record.post_id),
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("library expansion post association was not recorded")
        expected = (
            record.raw_observation_id,
            int(record.details_required),
            record.observed_at,
        )
        actual = (row["raw_observation_id"], row["details_required"], row["observed_at"])
        if actual != expected:
            raise ValueError("library expansion post already has different provenance")
        return int(row[0])
