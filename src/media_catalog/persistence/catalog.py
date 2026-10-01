from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from media_catalog.database import CatalogDatabase
from media_catalog.persistence.support import WriteResult, caller_connection, platform_id
from media_catalog.records import (
    AccountRecord,
    AssetRecord,
    MediaOccurrenceRecord,
    PostRecord,
    normalize_timestamp,
    validate_event_type,
    validate_role,
)


class CatalogWrites:
    def __init__(self, database: CatalogDatabase) -> None:
        self.connection = caller_connection(database)

    def upsert_account(
        self, record: AccountRecord, *, raw_observation_id: int | None = None
    ) -> WriteResult:
        record_platform_id = platform_id(self.connection, record.platform)
        prior = self.connection.execute(
            """SELECT account_id, canonical_url, availability, last_seen_at FROM accounts
               WHERE platform_id = ? AND native_account_id = ?""",
            (record_platform_id, record.native_id),
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
                record_platform_id,
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
                (record_platform_id, record.native_id),
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
        record_platform_id = platform_id(self.connection, record.platform)
        prior = self.connection.execute(
            """SELECT * FROM posts WHERE platform_id = ? AND native_post_id = ?""",
            (record_platform_id, record.native_id),
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
                record_platform_id,
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
                (record_platform_id, record.native_id),
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
