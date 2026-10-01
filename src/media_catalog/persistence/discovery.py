from __future__ import annotations

from media_catalog.database import CatalogDatabase
from media_catalog.persistence.support import (
    WriteResult,
    caller_connection,
    inserted_id,
    platform_id,
)
from media_catalog.records import LinkOccurrence, PlatformReferenceRecord


class DiscoveryWrites:
    def __init__(self, database: CatalogDatabase) -> None:
        self.connection = caller_connection(database)

    def begin_discovery(
        self,
        *,
        extractor_version: str,
        canonicalizer_version: str,
        recognizer_version: str,
        scoring_version: str,
        started_at: str,
    ) -> int:
        cursor = self.connection.execute(
            """INSERT INTO discovery_runs
               (extractor_version, canonicalizer_version, recognizer_version, scoring_version,
                started_at, status)
               VALUES (?, ?, ?, ?, ?, 'running')""",
            (
                extractor_version,
                canonicalizer_version,
                recognizer_version,
                scoring_version,
                started_at,
            ),
        )
        return inserted_id(cursor)

    def finish_discovery(
        self,
        run_id: int,
        *,
        status: str,
        finished_at: str,
        counts: dict[str, int],
        diagnostic: str | None = None,
    ) -> None:
        if status not in {"complete", "failed"}:
            raise ValueError(f"invalid terminal discovery status: {status}")
        self.connection.execute(
            """UPDATE discovery_runs SET finished_at = ?, status = ?, scanned_count = ?,
                   observed_count = ?, recognized_count = ?, unresolved_count = ?,
                   existing_count = ?, failed_count = ?, diagnostic = ?
               WHERE discovery_run_id = ? AND status = 'running'""",
            (
                finished_at,
                status,
                counts.get("scanned", 0),
                counts.get("observed", 0),
                counts.get("recognized", 0),
                counts.get("unresolved", 0),
                counts.get("existing", 0),
                counts.get("failed", 0),
                diagnostic[:1000] if diagnostic else None,
                run_id,
            ),
        )

    def store_link_observation(
        self,
        run_id: int,
        occurrence: LinkOccurrence,
        *,
        canonical_url: str,
        canonicalization_version: str,
        resolution_state: str,
        resolution_reason: str | None,
        extractor_version: str,
        occurrence_digest: str,
        original_query: str,
        original_fragment: str,
        reference: PlatformReferenceRecord | None,
    ) -> tuple[WriteResult, int | None]:
        self.connection.execute(
            """INSERT INTO external_links
               (canonical_url, canonicalization_version, resolution_state, resolution_reason)
               VALUES (?, ?, ?, ?) ON CONFLICT(canonical_url, canonicalization_version)
               DO UPDATE SET resolution_state = excluded.resolution_state,
                             resolution_reason = excluded.resolution_reason""",
            (canonical_url, canonicalization_version, resolution_state, resolution_reason),
        )
        link_id = int(
            self.connection.execute(
                """SELECT external_link_id FROM external_links
                   WHERE canonical_url = ? AND canonicalization_version = ?""",
                (canonical_url, canonicalization_version),
            ).fetchone()[0]
        )
        existing = self.connection.execute(
            """SELECT link_observation_id FROM link_observations
               WHERE occurrence_digest = ? AND extractor_version = ?""",
            (occurrence_digest, extractor_version),
        ).fetchone()
        self.connection.execute(
            """INSERT INTO link_observations
               (external_link_id, discovery_run_id, subject_kind, subject_account_id,
                subject_post_id, account_snapshot_id, raw_observation_id, source_context,
                json_path, original_url, original_query, original_fragment, observed_at,
                extractor_version, occurrence_digest)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (
                link_id,
                run_id,
                occurrence.subject_kind,
                occurrence.subject_id if occurrence.subject_kind == "account" else None,
                occurrence.subject_id if occurrence.subject_kind == "post" else None,
                occurrence.account_snapshot_id,
                occurrence.raw_observation_id,
                occurrence.source_context,
                occurrence.json_path,
                occurrence.original_url,
                original_query,
                original_fragment,
                occurrence.observed_at,
                extractor_version,
                occurrence_digest,
            ),
        )
        observation_id = int(
            self.connection.execute(
                """SELECT link_observation_id FROM link_observations
                   WHERE occurrence_digest = ? AND extractor_version = ?""",
                (occurrence_digest, extractor_version),
            ).fetchone()[0]
        )
        if existing is not None:
            self.connection.execute(
                """UPDATE link_observations SET external_link_id = ?
                   WHERE link_observation_id = ?""",
                (link_id, observation_id),
            )
        reference_id = None
        if reference is not None:
            record_platform_id = platform_id(self.connection, reference.platform)
            resolved_account_id = None
            resolved_post_id = None
            if reference.object_kind == "account" and not reference.instance_host:
                row = self.connection.execute(
                    """SELECT account_id FROM accounts
                       WHERE platform_id = ? AND native_account_id = ?""",
                    (record_platform_id, reference.native_id),
                ).fetchone()
                resolved_account_id = int(row[0]) if row else None
            elif reference.object_kind == "post" and not reference.instance_host:
                row = self.connection.execute(
                    """SELECT post_id FROM posts WHERE platform_id = ? AND native_post_id = ?""",
                    (record_platform_id, reference.native_id),
                ).fetchone()
                resolved_post_id = int(row[0]) if row else None
            self.connection.execute(
                """INSERT INTO platform_references
                   (platform_id, instance_host, object_kind, identifier_kind, native_identifier,
                    canonical_target_url, recognizer_name, recognizer_version,
                    resolved_account_id, resolved_post_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO UPDATE SET
                    canonical_target_url = excluded.canonical_target_url,
                    resolved_account_id = COALESCE(platform_references.resolved_account_id,
                                                   excluded.resolved_account_id),
                    resolved_post_id = COALESCE(platform_references.resolved_post_id,
                                                excluded.resolved_post_id)""",
                (
                    record_platform_id,
                    reference.instance_host,
                    reference.object_kind,
                    reference.identifier_kind,
                    reference.native_id,
                    reference.canonical_url,
                    reference.recognizer,
                    reference.recognizer_version,
                    resolved_account_id,
                    resolved_post_id,
                ),
            )
            reference_id = int(
                self.connection.execute(
                    """SELECT platform_reference_id FROM platform_references
                       WHERE platform_id = ? AND instance_host = ? AND object_kind = ?
                         AND identifier_kind = ? AND native_identifier = ?
                         AND recognizer_version = ?""",
                    (
                        record_platform_id,
                        reference.instance_host,
                        reference.object_kind,
                        reference.identifier_kind,
                        reference.native_id,
                        reference.recognizer_version,
                    ),
                ).fetchone()[0]
            )
            self.connection.execute(
                """INSERT INTO external_link_references
                   (external_link_id, platform_reference_id)
                   VALUES (?, ?) ON CONFLICT DO NOTHING""",
                (link_id, reference_id),
            )
        return WriteResult(observation_id, "existing" if existing else "inserted"), reference_id
