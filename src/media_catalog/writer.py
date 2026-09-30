from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from media_catalog.database import CatalogDatabase
from media_catalog.persistence.acquisition import AcquisitionWrites
from media_catalog.persistence.library import LibraryWrites
from media_catalog.persistence.lookup import LookupWrites
from media_catalog.persistence.metadata import MetadataWrites
from media_catalog.persistence.remote import RemoteWrites
from media_catalog.persistence.storage import StorageWrites
from media_catalog.persistence.support import (
    WriteResult,
    platform_id,
)
from media_catalog.persistence.support import (
    inserted_id as _inserted_id,
)
from media_catalog.records import (
    AccountRecord,
    AcquisitionAttemptRecord,
    AcquisitionPartialRecord,
    AcquisitionPlanItemRecord,
    AcquisitionPlanRecord,
    AcquisitionQuarantineRecord,
    AcquisitionRunItemRecord,
    AcquisitionRunRecord,
    AcquisitionVerificationRecord,
    AdoptionAttemptRecord,
    AdoptionItemRecord,
    AdoptionRunRecord,
    AssetFingerprintRecord,
    AssetLocationRecord,
    AssetRecord,
    AttributionRecord,
    CandidateLookupCheckpointRecord,
    CandidateLookupRequestRecord,
    CandidateLookupResultRecord,
    CandidateLookupRunRecord,
    LibraryExpansionExecutionRecord,
    LibraryExpansionPlanRecord,
    LibraryExpansionPostRecord,
    LibraryExpansionProbeRecord,
    LinkOccurrence,
    ManagedRootRecord,
    MediaOccurrenceRecord,
    OccurrenceSourceRecord,
    PlatformReferenceRecord,
    PostExternalReferenceRecord,
    PostFlagObservationRecord,
    PostMetadataObservationRecord,
    PostPoolObservationRecord,
    PostRecord,
    RawRecord,
    RemoteCheckpointRecord,
    RemoteRequestRecord,
    RemoteRunRecord,
    TagAliasObservationRecord,
    TagObservationRecord,
    normalize_timestamp,
    validate_event_type,
    validate_role,
)


class CatalogWriter:
    def __init__(self, database: CatalogDatabase) -> None:
        self.database = database
        self.connection = database.connection
        self._storage = StorageWrites(database)
        self._acquisition = AcquisitionWrites(database)
        self._lookup = LookupWrites(database)
        self._library = LibraryWrites(database)
        self._remote = RemoteWrites(database)
        self._metadata = MetadataWrites(database)

    def platform_id(self, platform: str) -> int:
        return platform_id(self.connection, platform)

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
        return _inserted_id(cursor)

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
            platform_id = self.platform_id(reference.platform)
            resolved_account_id = None
            resolved_post_id = None
            if reference.object_kind == "account" and not reference.instance_host:
                row = self.connection.execute(
                    """SELECT account_id FROM accounts
                       WHERE platform_id = ? AND native_account_id = ?""",
                    (platform_id, reference.native_id),
                ).fetchone()
                resolved_account_id = int(row[0]) if row else None
            elif reference.object_kind == "post" and not reference.instance_host:
                row = self.connection.execute(
                    """SELECT post_id FROM posts WHERE platform_id = ? AND native_post_id = ?""",
                    (platform_id, reference.native_id),
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
                    platform_id,
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
                        platform_id,
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

    def store_raw(
        self,
        record: RawRecord,
        *,
        import_run_id: int | None = None,
        remote_run_id: int | None = None,
        remote_request_id: int | None = None,
    ) -> int:
        return self._remote.store_raw(
            record,
            import_run_id=import_run_id,
            remote_run_id=remote_run_id,
            remote_request_id=remote_request_id,
        )

    def begin_remote_run(self, record: RemoteRunRecord) -> int:
        return self._remote.begin_remote_run(record)

    def finish_remote_run(
        self,
        remote_run_id: int,
        *,
        status: str,
        outcome: str,
        request_count: int,
        page_count: int,
        record_count: int,
        finished_at: str,
        budget_boundary: str | None = None,
        retry_after: str | None = None,
        diagnostic: str | None = None,
    ) -> None:
        self._remote.finish_remote_run(
            remote_run_id,
            status=status,
            outcome=outcome,
            request_count=request_count,
            page_count=page_count,
            record_count=record_count,
            finished_at=finished_at,
            budget_boundary=budget_boundary,
            retry_after=retry_after,
            diagnostic=diagnostic,
        )

    def record_remote_request(self, record: RemoteRequestRecord) -> int:
        return self._remote.record_remote_request(record)

    def save_remote_checkpoint(self, record: RemoteCheckpointRecord) -> int:
        return self._remote.save_remote_checkpoint(record)

    def upsert_tag(
        self,
        post_id: int,
        record: TagObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        return self._metadata.upsert_tag(post_id, record, raw_observation_id=raw_observation_id)

    def upsert_tag_record(
        self,
        record: TagObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        """Persist a standalone provider tag observation without inventing a post link."""
        return self._metadata.upsert_tag_record(record, raw_observation_id=raw_observation_id)

    def upsert_tag_alias(
        self,
        record: TagAliasObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        return self._metadata.upsert_tag_alias(record, raw_observation_id=raw_observation_id)

    def record_post_metadata(
        self,
        post_id: int,
        record: PostMetadataObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        return self._metadata.record_post_metadata(
            post_id, record, raw_observation_id=raw_observation_id
        )

    def record_post_pool(
        self,
        post_id: int,
        record: PostPoolObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        return self._metadata.record_post_pool(
            post_id, record, raw_observation_id=raw_observation_id
        )

    def record_post_flag(
        self,
        post_id: int,
        record: PostFlagObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        return self._metadata.record_post_flag(
            post_id, record, raw_observation_id=raw_observation_id
        )

    def upsert_attribution(
        self,
        record: AttributionRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        return self._metadata.upsert_attribution(record, raw_observation_id=raw_observation_id)

    def add_post_external_reference(
        self,
        post_id: int,
        record: PostExternalReferenceRecord,
        *,
        raw_observation_id: int,
    ) -> int:
        return self._metadata.add_post_external_reference(
            post_id, record, raw_observation_id=raw_observation_id
        )

    def add_account_external_link(
        self,
        account_id: int,
        url: str,
        source_context: str,
        observed_at: str,
        *,
        raw_observation_id: int,
    ) -> int:
        return self._metadata.add_account_external_link(
            account_id,
            url,
            source_context,
            observed_at,
            raw_observation_id=raw_observation_id,
        )

    def upsert_account(
        self, record: AccountRecord, *, raw_observation_id: int | None = None
    ) -> WriteResult:
        platform_id = self.platform_id(record.platform)
        prior = self.connection.execute(
            """SELECT account_id, canonical_url, availability, last_seen_at FROM accounts
               WHERE platform_id = ? AND native_account_id = ?""",
            (platform_id, record.native_id),
        ).fetchone()
        self.connection.execute(
            """INSERT INTO accounts (
                   platform_id, native_account_id, canonical_url, availability,
                   first_seen_at, last_seen_at
               ) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(platform_id, native_account_id) DO UPDATE SET
                   canonical_url = CASE WHEN excluded.last_seen_at >= accounts.last_seen_at
                       THEN COALESCE(excluded.canonical_url, accounts.canonical_url)
                       ELSE accounts.canonical_url END,
                   availability = CASE WHEN excluded.last_seen_at >= accounts.last_seen_at
                       THEN excluded.availability ELSE accounts.availability END,
                   first_seen_at = MIN(accounts.first_seen_at, excluded.first_seen_at),
                   last_seen_at = MAX(accounts.last_seen_at, excluded.last_seen_at)""",
            (
                platform_id,
                record.native_id,
                record.canonical_url,
                record.availability,
                record.observed_at,
                record.observed_at,
            ),
        )
        account_id = int(
            self.connection.execute(
                "SELECT account_id FROM accounts WHERE platform_id = ? AND native_account_id = ?",
                (platform_id, record.native_id),
            ).fetchone()[0]
        )
        snapshot = asdict(record)
        for key in ("platform", "native_id", "observed_at", "canonical_url", "availability"):
            snapshot.pop(key)
        snapshot_digest = hashlib.sha256(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = self.connection.execute(
            """SELECT account_snapshot_id FROM account_snapshots
               WHERE account_id = ? AND snapshot_digest = ? AND raw_observation_id IS ?""",
            (account_id, snapshot_digest, raw_observation_id),
        ).fetchone()
        normalized_existing = self.connection.execute(
            """SELECT 1 FROM account_snapshots
               WHERE account_id = ? AND snapshot_digest = ? LIMIT 1""",
            (account_id, snapshot_digest),
        ).fetchone()
        if existing is None:
            self.connection.execute(
                """INSERT INTO account_snapshots (
                       account_id, observed_at, handle, display_name, bio, location, website_url,
                       profile_url, avatar_url, banner_url, followers, following, verified,
                       verification_type, snapshot_digest, raw_observation_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    account_id,
                    record.observed_at,
                    record.handle,
                    record.display_name,
                    record.bio,
                    record.location,
                    record.website_url,
                    record.profile_url,
                    record.avatar_url,
                    record.banner_url,
                    record.followers,
                    record.following,
                    record.verified,
                    record.verification_type,
                    snapshot_digest,
                    raw_observation_id,
                ),
            )
        outcome = "inserted" if prior is None else "existing"
        if prior is not None and normalized_existing is None:
            outcome = "updated"
        if prior is not None and record.observed_at >= prior["last_seen_at"]:
            desired_url = record.canonical_url or prior["canonical_url"]
            if (
                desired_url != prior["canonical_url"]
                or record.availability != prior["availability"]
            ):
                outcome = "updated"
        return WriteResult(account_id, outcome)

    def upsert_post(
        self, record: PostRecord, *, raw_observation_id: int | None = None
    ) -> WriteResult:
        platform_id = self.platform_id(record.platform)
        prior = self.connection.execute(
            """SELECT * FROM posts WHERE platform_id = ? AND native_post_id = ?""",
            (platform_id, record.native_id),
        ).fetchone()
        self.connection.execute(
            """INSERT INTO posts (
                   platform_id, native_post_id, canonical_url, text_content, language, created_at,
                   updated_at, rating, availability, status, title, provider_post_type,
                   first_seen_at, last_seen_at, raw_observation_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(platform_id, native_post_id) DO UPDATE SET
                   canonical_url = CASE WHEN excluded.last_seen_at >= posts.last_seen_at
                       THEN COALESCE(excluded.canonical_url, posts.canonical_url)
                       ELSE posts.canonical_url END,
                   text_content = CASE WHEN excluded.last_seen_at >= posts.last_seen_at
                       THEN COALESCE(excluded.text_content, posts.text_content)
                       ELSE posts.text_content END,
                   language = CASE WHEN excluded.last_seen_at >= posts.last_seen_at
                       THEN COALESCE(excluded.language, posts.language) ELSE posts.language END,
                   created_at = COALESCE(posts.created_at, excluded.created_at),
                   updated_at = CASE WHEN excluded.last_seen_at >= posts.last_seen_at
                       THEN COALESCE(excluded.updated_at, posts.updated_at)
                       ELSE posts.updated_at END,
                   rating = CASE WHEN excluded.last_seen_at >= posts.last_seen_at
                       THEN COALESCE(excluded.rating, posts.rating) ELSE posts.rating END,
                   availability = CASE WHEN excluded.last_seen_at >= posts.last_seen_at
                       THEN excluded.availability ELSE posts.availability END,
                   status = CASE WHEN excluded.last_seen_at >= posts.last_seen_at
                       THEN COALESCE(excluded.status, posts.status) ELSE posts.status END,
                   title = CASE WHEN excluded.last_seen_at >= posts.last_seen_at
                       THEN COALESCE(excluded.title, posts.title) ELSE posts.title END,
                   provider_post_type = CASE WHEN excluded.last_seen_at >= posts.last_seen_at
                       THEN COALESCE(excluded.provider_post_type, posts.provider_post_type)
                       ELSE posts.provider_post_type END,
                   first_seen_at = MIN(posts.first_seen_at, excluded.first_seen_at),
                   last_seen_at = MAX(posts.last_seen_at, excluded.last_seen_at),
                   raw_observation_id = CASE WHEN excluded.last_seen_at >= posts.last_seen_at
                       THEN COALESCE(excluded.raw_observation_id, posts.raw_observation_id)
                       ELSE posts.raw_observation_id END""",
            (
                platform_id,
                record.native_id,
                record.canonical_url,
                record.text,
                record.language,
                record.created_at,
                record.updated_at,
                record.rating,
                record.availability,
                record.status,
                record.title,
                record.provider_post_type,
                record.observed_at,
                record.observed_at,
                raw_observation_id,
            ),
        )
        post_id = int(
            self.connection.execute(
                "SELECT post_id FROM posts WHERE platform_id = ? AND native_post_id = ?",
                (platform_id, record.native_id),
            ).fetchone()[0]
        )
        if prior is None:
            return WriteResult(post_id, "inserted")
        comparable = {
            "canonical_url": record.canonical_url or prior["canonical_url"],
            "text_content": record.text or prior["text_content"],
            "language": record.language or prior["language"],
            "updated_at": record.updated_at or prior["updated_at"],
            "rating": record.rating or prior["rating"],
            "availability": record.availability,
            "status": record.status or prior["status"],
            "title": record.title or prior["title"],
            "provider_post_type": record.provider_post_type or prior["provider_post_type"],
        }
        changed = record.observed_at >= prior["last_seen_at"] and any(
            comparable[key] != prior[key] for key in comparable
        )
        return WriteResult(post_id, "updated" if changed else "existing")

    def add_participant(
        self, post_id: int, account_id: int, role: str, *, raw_observation_id: int | None = None
    ) -> None:
        validate_role(role)
        self.connection.execute(
            """INSERT INTO post_participants (post_id, account_id, role, raw_observation_id)
               VALUES (?, ?, ?, ?) ON CONFLICT(post_id, account_id, role) DO UPDATE SET
               raw_observation_id = COALESCE(excluded.raw_observation_id,
                                             post_participants.raw_observation_id)""",
            (post_id, account_id, role, raw_observation_id),
        )

    def add_observation(
        self,
        post_id: int,
        event_type: str,
        source_kind: str,
        source_event_key: str,
        observed_at: str,
        *,
        import_run_id: int | None = None,
        raw_observation_id: int | None = None,
        collection_data: str | None = None,
    ) -> WriteResult:
        validate_event_type(event_type)
        if not source_kind or not source_event_key:
            raise ValueError("observation source kind and event key must not be empty")

        observed_at = normalize_timestamp(observed_at)
        existing = self.connection.execute(
            """SELECT observation_id, subject_id, observed_at, collection_data,
                      import_run_id, raw_observation_id FROM observations
               WHERE source_kind = ? AND source_event_key = ? AND event_type = ?""",
            (source_kind, source_event_key, event_type),
        ).fetchone()
        if existing is not None and int(existing["subject_id"]) != post_id:
            key = f"{source_kind}:{source_event_key}:{event_type}"
            raise ValueError(f"observation key {key} belongs to another post")
        self.connection.execute(
            """INSERT INTO observations (
                   subject_kind, subject_id, event_type, source_kind, source_event_key,
                   observed_at, collection_data, import_run_id, raw_observation_id
               ) VALUES ('post', ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_kind, source_event_key, event_type) DO UPDATE SET
                   observed_at = MAX(observations.observed_at, excluded.observed_at),
                   collection_data = CASE WHEN excluded.observed_at >= observations.observed_at
                       THEN excluded.collection_data ELSE observations.collection_data END,
                   import_run_id = CASE WHEN excluded.observed_at >= observations.observed_at
                       THEN excluded.import_run_id ELSE observations.import_run_id END,
                   raw_observation_id = CASE WHEN excluded.observed_at >= observations.observed_at
                       THEN excluded.raw_observation_id ELSE observations.raw_observation_id END""",
            (
                post_id,
                event_type,
                source_kind,
                source_event_key,
                observed_at,
                collection_data,
                import_run_id,
                raw_observation_id,
            ),
        )
        observation_id = int(
            self.connection.execute(
                """SELECT observation_id FROM observations
                   WHERE source_kind = ? AND source_event_key = ? AND event_type = ?""",
                (source_kind, source_event_key, event_type),
            ).fetchone()[0]
        )
        self.connection.execute(
            """INSERT INTO observation_revisions (
                   observation_id, observed_at, collection_data, import_run_id, raw_observation_id
               ) VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (observation_id, observed_at, collection_data, import_run_id, raw_observation_id),
        )
        if existing is None:
            outcome = "inserted"
        elif (
            collection_data != existing["collection_data"]
            or raw_observation_id != existing["raw_observation_id"]
        ):
            outcome = "updated"
        else:
            outcome = "existing"
        return WriteResult(observation_id, outcome)

    def add_relation(
        self,
        source_post_id: int,
        target_post_id: int,
        relation_type: str,
        *,
        raw_observation_id: int | None = None,
    ) -> None:
        self.connection.execute(
            """INSERT INTO post_relations (
                   source_post_id, target_post_id, relation_type, raw_observation_id
               ) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (source_post_id, target_post_id, relation_type, raw_observation_id),
        )

    def upsert_media(
        self,
        post_id: int,
        record: MediaOccurrenceRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        if record.observed_at is None:
            raise ValueError("media occurrence observed_at is required for persistence")
        prior = self.connection.execute(
            """SELECT * FROM media_occurrences WHERE post_id = ? AND source_key = ?""",
            (post_id, record.source_key),
        ).fetchone()
        self.connection.execute(
            """INSERT INTO media_occurrences (
                   post_id, source_key, media_index, media_type, role, remote_url, preview_url,
                   mime_type, width, height, duration_ms, variants_json, alt_text, availability,
                   declared_md5, declared_sha256, declared_file_size, raw_observation_id,
                   observed_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(post_id, source_key) DO UPDATE SET
                   media_index = CASE WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN excluded.media_index ELSE media_occurrences.media_index END,
                   media_type = CASE WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN excluded.media_type ELSE media_occurrences.media_type END,
                   role = CASE WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN COALESCE(excluded.role, media_occurrences.role)
                       ELSE media_occurrences.role END,
                   remote_url = CASE WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN COALESCE(excluded.remote_url, media_occurrences.remote_url)
                       ELSE media_occurrences.remote_url END,
                   preview_url = CASE WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN COALESCE(excluded.preview_url, media_occurrences.preview_url)
                       ELSE media_occurrences.preview_url END,
                   mime_type = CASE WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN COALESCE(excluded.mime_type, media_occurrences.mime_type)
                       ELSE media_occurrences.mime_type END,
                   width = CASE WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN COALESCE(excluded.width, media_occurrences.width)
                       ELSE media_occurrences.width END,
                   height = CASE WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN COALESCE(excluded.height, media_occurrences.height)
                       ELSE media_occurrences.height END,
                   duration_ms = CASE WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN COALESCE(excluded.duration_ms, media_occurrences.duration_ms)
                       ELSE media_occurrences.duration_ms END,
                   variants_json = CASE WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN COALESCE(excluded.variants_json, media_occurrences.variants_json)
                       ELSE media_occurrences.variants_json END,
                   alt_text = CASE WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN COALESCE(excluded.alt_text, media_occurrences.alt_text)
                       ELSE media_occurrences.alt_text END,
                   availability = CASE WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN excluded.availability ELSE media_occurrences.availability END,
                   declared_md5 = COALESCE(media_occurrences.declared_md5, excluded.declared_md5),
                   declared_sha256 = COALESCE(
                       media_occurrences.declared_sha256, excluded.declared_sha256
                   ),
                   declared_file_size = CASE
                       WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN COALESCE(excluded.declared_file_size,
                                     media_occurrences.declared_file_size)
                       ELSE media_occurrences.declared_file_size END,
                   raw_observation_id = CASE
                       WHEN excluded.observed_at >= media_occurrences.observed_at
                       THEN COALESCE(excluded.raw_observation_id,
                                     media_occurrences.raw_observation_id)
                       ELSE media_occurrences.raw_observation_id END,
                   observed_at = MAX(media_occurrences.observed_at, excluded.observed_at)""",
            (
                post_id,
                record.source_key,
                record.index,
                record.media_type,
                record.role,
                record.remote_url,
                record.preview_url,
                record.mime_type,
                record.width,
                record.height,
                record.duration_ms,
                record.variants_json,
                record.alt_text,
                record.availability,
                record.declared_md5,
                record.declared_sha256,
                record.declared_file_size,
                raw_observation_id,
                record.observed_at,
            ),
        )
        occurrence_id = int(
            self.connection.execute(
                """SELECT media_occurrence_id FROM media_occurrences
                   WHERE post_id = ? AND source_key = ?""",
                (post_id, record.source_key),
            ).fetchone()[0]
        )
        if prior is None:
            return WriteResult(occurrence_id, "inserted")
        comparable = {
            "media_index": record.index,
            "media_type": record.media_type,
            "role": record.role or prior["role"],
            "remote_url": record.remote_url or prior["remote_url"],
            "preview_url": record.preview_url or prior["preview_url"],
            "mime_type": record.mime_type or prior["mime_type"],
            "width": record.width if record.width is not None else prior["width"],
            "height": record.height if record.height is not None else prior["height"],
            "duration_ms": (
                record.duration_ms if record.duration_ms is not None else prior["duration_ms"]
            ),
            "variants_json": record.variants_json or prior["variants_json"],
            "alt_text": record.alt_text or prior["alt_text"],
            "availability": record.availability,
            "declared_file_size": (
                record.declared_file_size
                if record.declared_file_size is not None
                else prior["declared_file_size"]
            ),
        }
        changed = record.observed_at >= prior["observed_at"] and any(
            comparable[key] != prior[key] for key in comparable
        )
        return WriteResult(occurrence_id, "updated" if changed else "existing")

    def link_asset(
        self, occurrence_id: int, record: AssetRecord, *, relationship: str = "reference"
    ) -> int:
        self.connection.execute(
            """INSERT INTO assets (
                   verified_sha256, verified_md5, phash, byte_size, storage_kind, storage_path,
                   verified_at, verification_method, detected_mime_type, detected_width,
                   detected_height, detected_frame_count
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(verified_sha256) DO UPDATE SET
                   -- A legacy assertion must not downgrade a managed asset
                   -- whose bytes have already been verified from storage.
                   verified_md5 = CASE
                       WHEN assets.storage_kind = 'managed'
                            AND excluded.storage_kind <> 'managed'
                       THEN assets.verified_md5
                       ELSE COALESCE(excluded.verified_md5, assets.verified_md5)
                   END,
                   phash = CASE
                       WHEN assets.storage_kind = 'managed'
                            AND excluded.storage_kind <> 'managed'
                       THEN assets.phash
                       ELSE COALESCE(excluded.phash, assets.phash)
                   END,
                   byte_size = CASE
                       WHEN assets.storage_kind = 'managed'
                            AND excluded.storage_kind <> 'managed'
                       THEN assets.byte_size
                       ELSE COALESCE(excluded.byte_size, assets.byte_size)
                   END,
                   storage_kind = CASE
                       WHEN assets.storage_kind = 'managed'
                            AND excluded.storage_kind <> 'managed'
                       THEN assets.storage_kind
                       ELSE excluded.storage_kind
                   END,
                   storage_path = CASE
                       WHEN assets.storage_kind = 'managed'
                            AND excluded.storage_kind <> 'managed'
                       THEN assets.storage_path
                       ELSE COALESCE(excluded.storage_path, assets.storage_path)
                   END,
                   verified_at = CASE
                       WHEN assets.storage_kind = 'managed'
                            AND excluded.storage_kind <> 'managed'
                       THEN assets.verified_at
                       ELSE COALESCE(excluded.verified_at, assets.verified_at)
                   END,
                   verification_method = CASE
                       WHEN assets.storage_kind = 'managed'
                            AND excluded.storage_kind <> 'managed'
                       THEN assets.verification_method
                       ELSE excluded.verification_method
                   END,
                   detected_mime_type = COALESCE(excluded.detected_mime_type,
                                                 assets.detected_mime_type),
                   detected_width = COALESCE(excluded.detected_width, assets.detected_width),
                   detected_height = COALESCE(excluded.detected_height, assets.detected_height),
                   detected_frame_count = COALESCE(excluded.detected_frame_count,
                                                   assets.detected_frame_count)""",
            (
                record.sha256,
                record.md5,
                record.phash,
                record.byte_size,
                record.storage_kind,
                record.storage_path,
                record.verified_at,
                record.verification_method,
                record.detected_mime_type,
                record.detected_width,
                record.detected_height,
                record.detected_frame_count,
            ),
        )
        asset_id = int(
            self.connection.execute(
                "SELECT asset_id FROM assets WHERE verified_sha256 = ?", (record.sha256,)
            ).fetchone()[0]
        )
        self.connection.execute(
            """INSERT INTO occurrence_assets (
                   media_occurrence_id, asset_id, relationship, verification_source
               ) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (occurrence_id, asset_id, relationship, record.verification_method),
        )
        return asset_id

    def register_managed_root(self, record: ManagedRootRecord) -> int:
        """Insert or retrieve a stable source/managed root identity."""
        return self._storage.register_managed_root(record)

    # Compatibility spelling used by callers that treat roots as an upsert.
    upsert_managed_root = register_managed_root

    def add_asset_location(self, record: AssetLocationRecord) -> int:
        return self._storage.add_asset_location(record)

    def add_occurrence_source(self, record: OccurrenceSourceRecord) -> int:
        return self._storage.add_occurrence_source(record)

    def add_asset_fingerprint(self, record: AssetFingerprintRecord) -> int:
        return self._storage.add_asset_fingerprint(record)

    def begin_adoption_run(self, record: AdoptionRunRecord) -> int:
        return self._storage.begin_adoption_run(record)

    def finish_adoption_run(
        self,
        run_id: int,
        *,
        status: str,
        finished_at: str,
        completed_count: int | None = None,
        failed_count: int | None = None,
        diagnostic: str | None = None,
    ) -> None:
        self._storage.finish_adoption_run(
            run_id,
            status=status,
            finished_at=finished_at,
            completed_count=completed_count,
            failed_count=failed_count,
            diagnostic=diagnostic,
        )

    def record_adoption_item(self, record: AdoptionItemRecord) -> int:
        return self._storage.record_adoption_item(record)

    def record_adoption_attempt(self, record: AdoptionAttemptRecord) -> int:
        return self._storage.record_adoption_attempt(record)

    def adoption_items(self, run_id: int | None = None) -> list[dict[str, object]]:
        if run_id is None:
            rows = self.connection.execute("SELECT * FROM adoption_items ORDER BY adoption_item_id")
        else:
            rows = self.connection.execute(
                "SELECT * FROM adoption_items WHERE adoption_run_id = ? ORDER BY adoption_item_id",
                (run_id,),
            )
        return [dict(row) for row in rows]

    def create_acquisition_plan(self, record: AcquisitionPlanRecord) -> int:
        return self._acquisition.create_acquisition_plan(record)

    def add_acquisition_plan_item(self, record: AcquisitionPlanItemRecord) -> int:
        return self._acquisition.add_acquisition_plan_item(record)

    def begin_acquisition_run(self, record: AcquisitionRunRecord) -> int:
        return self._acquisition.begin_acquisition_run(record)

    def finish_acquisition_run(
        self,
        acquisition_run_id: int,
        *,
        status: str,
        outcome: str,
        completed_count: int,
        failed_count: int,
        deferred_count: int,
        received_bytes: int,
        quarantined_bytes: int,
        finished_at: str,
        diagnostic: str | None = None,
    ) -> None:
        self._acquisition.finish_acquisition_run(
            acquisition_run_id,
            status=status,
            outcome=outcome,
            completed_count=completed_count,
            failed_count=failed_count,
            deferred_count=deferred_count,
            received_bytes=received_bytes,
            quarantined_bytes=quarantined_bytes,
            finished_at=finished_at,
            diagnostic=diagnostic,
        )

    def record_acquisition_run_item(self, record: AcquisitionRunItemRecord) -> int:
        return self._acquisition.record_acquisition_run_item(record)

    def record_acquisition_attempt(self, record: AcquisitionAttemptRecord) -> int:
        return self._acquisition.record_acquisition_attempt(record)

    def save_acquisition_partial(self, record: AcquisitionPartialRecord) -> int:
        return self._acquisition.save_acquisition_partial(record)

    def record_acquisition_verification(self, record: AcquisitionVerificationRecord) -> int:
        return self._acquisition.record_acquisition_verification(record)

    def record_acquisition_quarantine(self, record: AcquisitionQuarantineRecord) -> int:
        return self._acquisition.record_acquisition_quarantine(record)

    def begin_candidate_lookup(self, record: CandidateLookupRunRecord) -> int:
        return self._lookup.begin_candidate_lookup(record)

    def finish_candidate_lookup(
        self,
        run_id: int,
        *,
        status: str,
        outcome: str,
        request_count: int,
        page_count: int,
        result_count: int,
        finished_at: str,
        budget_boundary: str | None = None,
        retry_after: str | None = None,
        diagnostic: str | None = None,
    ) -> None:
        self._lookup.finish_candidate_lookup(
            run_id,
            status=status,
            outcome=outcome,
            request_count=request_count,
            page_count=page_count,
            result_count=result_count,
            finished_at=finished_at,
            budget_boundary=budget_boundary,
            retry_after=retry_after,
            diagnostic=diagnostic,
        )

    def record_candidate_lookup_request(self, record: CandidateLookupRequestRecord) -> int:
        return self._lookup.record_candidate_lookup_request(record)

    def save_candidate_lookup_checkpoint(self, record: CandidateLookupCheckpointRecord) -> int:
        return self._lookup.save_candidate_lookup_checkpoint(record)

    def record_candidate_lookup_result(self, record: CandidateLookupResultRecord) -> int:
        return self._lookup.record_candidate_lookup_result(record)

    def record_library_expansion_plan(self, record: LibraryExpansionPlanRecord) -> int:
        return self._library.record_library_expansion_plan(record)

    def record_library_expansion_probe(self, record: LibraryExpansionProbeRecord) -> int:
        return self._library.record_library_expansion_probe(record)

    def record_library_expansion_execution(self, record: LibraryExpansionExecutionRecord) -> int:
        return self._library.record_library_expansion_execution(record)

    def record_library_expansion_post(self, record: LibraryExpansionPostRecord) -> int:
        return self._library.record_library_expansion_post(record)
