from __future__ import annotations

import hashlib
import json

from media_catalog.database import CatalogDatabase
from media_catalog.persistence.support import WriteResult, caller_connection, platform_id
from media_catalog.records import (
    AttributionRecord,
    PostExternalReferenceRecord,
    PostFlagObservationRecord,
    PostMetadataObservationRecord,
    PostPoolObservationRecord,
    TagAliasObservationRecord,
    TagObservationRecord,
    normalize_timestamp,
)


def _reference_url(platform: str, object_kind: str, native_id: str) -> str:
    if platform == "pixiv" and object_kind == "post":
        return f"https://www.pixiv.net/artworks/{native_id}"
    if platform == "pixiv" and object_kind == "account":
        return f"https://www.pixiv.net/users/{native_id}"
    return f"urn:{platform}:{object_kind}:{native_id}"


class MetadataWrites:
    def __init__(self, database: CatalogDatabase) -> None:
        self.connection = caller_connection(database)

    def upsert_tag(
        self,
        post_id: int,
        record: TagObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        record_platform_id = platform_id(self.connection, record.platform)
        self.connection.execute(
            """INSERT INTO tags (
                   platform_id, category, name, normalization_version, provider_tag_id,
                   native_category, native_category_code, post_count, is_locked,
                   last_observed_at, raw_observation_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(platform_id, category, name, normalization_version) DO UPDATE SET
                   provider_tag_id = COALESCE(excluded.provider_tag_id, tags.provider_tag_id),
                   native_category = COALESCE(excluded.native_category, tags.native_category),
                   native_category_code = COALESCE(
                       excluded.native_category_code, tags.native_category_code
                   ),
                   post_count = COALESCE(excluded.post_count, tags.post_count),
                   is_locked = COALESCE(excluded.is_locked, tags.is_locked),
                   last_observed_at = CASE
                       WHEN excluded.last_observed_at IS NULL THEN tags.last_observed_at
                       WHEN tags.last_observed_at IS NULL THEN excluded.last_observed_at
                       WHEN excluded.last_observed_at >= tags.last_observed_at
                       THEN excluded.last_observed_at ELSE tags.last_observed_at END,
                   raw_observation_id = COALESCE(
                       excluded.raw_observation_id, tags.raw_observation_id
                   )""",
            (
                record_platform_id,
                record.category,
                record.normalized_name,
                record.normalization_version,
                record.provider_tag_id,
                record.native_category,
                record.native_category_code,
                record.post_count,
                record.is_locked,
                record.observed_at,
                raw_observation_id,
            ),
        )
        tag_id = int(
            self.connection.execute(
                """SELECT tag_id FROM tags
                   WHERE platform_id = ? AND category = ? AND name = ?
                     AND normalization_version = ?""",
                (
                    record_platform_id,
                    record.category,
                    record.normalized_name,
                    record.normalization_version,
                ),
            ).fetchone()[0]
        )
        prior = self.connection.execute(
            "SELECT post_tag_id FROM post_tags WHERE post_id = ? AND tag_id = ?",
            (post_id, tag_id),
        ).fetchone()
        self.connection.execute(
            """INSERT INTO post_tags (post_id, tag_id, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(post_id, tag_id) DO UPDATE SET
                   first_seen_at = MIN(post_tags.first_seen_at, excluded.first_seen_at),
                   last_seen_at = MAX(post_tags.last_seen_at, excluded.last_seen_at)""",
            (post_id, tag_id, record.observed_at, record.observed_at),
        )
        post_tag_id = int(
            self.connection.execute(
                "SELECT post_tag_id FROM post_tags WHERE post_id = ? AND tag_id = ?",
                (post_id, tag_id),
            ).fetchone()[0]
        )
        digest_value = {
            "provider_spelling": record.provider_spelling,
            "translated_label": record.translated_label,
            "position": record.position,
            "native_category": record.native_category,
            "native_category_code": record.native_category_code,
            "observed_at": record.observed_at,
        }
        digest = hashlib.sha256(
            json.dumps(
                digest_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        cursor = self.connection.execute(
            """INSERT INTO post_tag_observations (
                   post_tag_id, observed_at, provider_spelling, translated_label,
                   position, raw_observation_id, observation_digest,
                   native_category, native_category_code
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (
                post_tag_id,
                record.observed_at,
                record.provider_spelling,
                record.translated_label,
                record.position,
                raw_observation_id,
                digest,
                record.native_category,
                record.native_category_code,
            ),
        )
        outcome = "inserted" if prior is None else ("updated" if cursor.rowcount else "existing")
        return WriteResult(post_tag_id, outcome)

    def upsert_tag_record(
        self,
        record: TagObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        """Persist a standalone provider tag observation without inventing a post link."""

        if record.provider_tag_id is None:
            raise ValueError("standalone tag observations require a provider tag id")
        record_platform_id = platform_id(self.connection, record.platform)
        prior = self.connection.execute(
            """SELECT tag_id FROM tags
               WHERE platform_id = ? AND provider_tag_id = ?""",
            (record_platform_id, record.provider_tag_id),
        ).fetchone()
        if prior is None:
            name_identity = self.connection.execute(
                """SELECT provider_tag_id FROM tags
                   WHERE platform_id = ? AND category = ? AND name = ?
                     AND normalization_version = ?""",
                (
                    record_platform_id,
                    record.category,
                    record.normalized_name,
                    record.normalization_version,
                ),
            ).fetchone()
            if (
                name_identity is not None
                and name_identity[0] is not None
                and str(name_identity[0]) != record.provider_tag_id
            ):
                raise ValueError("normalized tag name is already bound to another provider tag id")
            self.connection.execute(
                """INSERT INTO tags (
                       platform_id, category, name, normalization_version, provider_tag_id,
                       native_category, native_category_code, post_count, is_locked,
                       last_observed_at, raw_observation_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(platform_id, category, name, normalization_version) DO UPDATE SET
                       provider_tag_id = COALESCE(excluded.provider_tag_id, tags.provider_tag_id),
                       native_category = COALESCE(excluded.native_category, tags.native_category),
                       native_category_code = COALESCE(
                           excluded.native_category_code, tags.native_category_code
                       ),
                       post_count = COALESCE(excluded.post_count, tags.post_count),
                       is_locked = COALESCE(excluded.is_locked, tags.is_locked),
                       last_observed_at = excluded.last_observed_at,
                       raw_observation_id = excluded.raw_observation_id""",
                (
                    record_platform_id,
                    record.category,
                    record.normalized_name,
                    record.normalization_version,
                    record.provider_tag_id,
                    record.native_category,
                    record.native_category_code,
                    record.post_count,
                    record.is_locked,
                    record.observed_at,
                    raw_observation_id,
                ),
            )
            row = self.connection.execute(
                "SELECT tag_id FROM tags WHERE platform_id = ? AND provider_tag_id = ?",
                (record_platform_id, record.provider_tag_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("failed to store standalone tag")
            tag_id = int(row[0])
        else:
            tag_id = int(prior[0])
            self.connection.execute(
                """UPDATE tags SET
                       category = ?, name = ?, native_category = ?, native_category_code = ?,
                       post_count = ?, is_locked = ?, last_observed_at = ?, raw_observation_id = ?
                   WHERE tag_id = ?""",
                (
                    record.category,
                    record.normalized_name,
                    record.native_category,
                    record.native_category_code,
                    record.post_count,
                    record.is_locked,
                    record.observed_at,
                    raw_observation_id,
                    tag_id,
                ),
            )
        digest_value = {
            "provider_tag_id": record.provider_tag_id,
            "native_category": record.native_category,
            "native_category_code": record.native_category_code,
            "post_count": record.post_count,
            "is_locked": record.is_locked,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "observed_at": record.observed_at,
        }
        digest = hashlib.sha256(
            json.dumps(digest_value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        cursor = self.connection.execute(
            """INSERT INTO tag_observations (
                   tag_id, observed_at, provider_tag_id, native_category,
                   native_category_code, post_count, is_locked, created_at, updated_at,
                   raw_observation_id, observation_digest
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (
                tag_id,
                record.observed_at,
                record.provider_tag_id,
                record.native_category,
                record.native_category_code,
                record.post_count,
                record.is_locked,
                record.created_at,
                record.updated_at,
                raw_observation_id,
                digest,
            ),
        )
        outcome = "inserted" if prior is None else ("updated" if cursor.rowcount else "existing")
        return WriteResult(tag_id, outcome)

    def upsert_tag_alias(
        self,
        record: TagAliasObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        record_platform_id = platform_id(self.connection, record.platform)
        digest_value = {
            "provider_alias_id": record.provider_alias_id,
            "antecedent_name": record.antecedent_name,
            "consequent_name": record.consequent_name,
            "status": record.status,
            "post_count": record.post_count,
            "creator_id": record.creator_id,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "reason": record.reason,
            "forum_topic_id": record.forum_topic_id,
            "observed_at": record.observed_at,
        }
        digest = hashlib.sha256(
            json.dumps(digest_value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        cursor = self.connection.execute(
            """INSERT INTO tag_alias_observations (
                   platform_id, provider_alias_id, antecedent_name, consequent_name,
                   status, post_count, creator_id, created_at, updated_at, reason,
                   forum_topic_id, observed_at, raw_observation_id, observation_digest
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(platform_id, provider_alias_id, observation_digest) DO NOTHING""",
            (
                record_platform_id,
                record.provider_alias_id,
                record.antecedent_name,
                record.consequent_name,
                record.status,
                record.post_count,
                record.creator_id,
                record.created_at,
                record.updated_at,
                record.reason,
                record.forum_topic_id,
                record.observed_at,
                raw_observation_id,
                digest,
            ),
        )
        row = self.connection.execute(
            """SELECT tag_alias_observation_id FROM tag_alias_observations
               WHERE platform_id = ? AND provider_alias_id = ? AND observation_digest = ?""",
            (record_platform_id, record.provider_alias_id, digest),
        ).fetchone()
        if row is None:
            raise RuntimeError("failed to store tag alias observation")
        return WriteResult(int(row[0]), "inserted" if cursor.rowcount else "existing")

    def record_post_metadata(
        self,
        post_id: int,
        record: PostMetadataObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        values = {
            "score_up": record.score_up,
            "score_down": record.score_down,
            "score_total": record.score_total,
            "favorite_count": record.favorite_count,
            "comment_count": record.comment_count,
            "flag_deleted": record.flag_deleted,
            "flag_pending": record.flag_pending,
            "flag_flagged": record.flag_flagged,
            "observed_at": record.observed_at,
        }
        digest = hashlib.sha256(
            json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        cursor = self.connection.execute(
            """INSERT INTO post_metadata_observations (
                   post_id, observed_at, score_up, score_down, score_total,
                   favorite_count, comment_count, flag_deleted, flag_pending,
                   flag_flagged, raw_observation_id, observation_digest
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(post_id, observation_digest) DO NOTHING""",
            (
                post_id,
                record.observed_at,
                record.score_up,
                record.score_down,
                record.score_total,
                record.favorite_count,
                record.comment_count,
                record.flag_deleted,
                record.flag_pending,
                record.flag_flagged,
                raw_observation_id,
                digest,
            ),
        )
        row = self.connection.execute(
            """SELECT post_metadata_observation_id FROM post_metadata_observations
               WHERE post_id = ? AND observation_digest = ?""",
            (post_id, digest),
        ).fetchone()
        if row is None:
            raise RuntimeError("failed to store post metadata observation")
        return WriteResult(int(row[0]), "inserted" if cursor.rowcount else "existing")

    def record_post_pool(
        self,
        post_id: int,
        record: PostPoolObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "pool_native_id": record.pool_native_id,
                    "observed_at": record.observed_at,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        cursor = self.connection.execute(
            """INSERT INTO post_pool_observations (
                   post_id, pool_native_id, observed_at, raw_observation_id, observation_digest
               ) VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (post_id, record.pool_native_id, record.observed_at, raw_observation_id, digest),
        )
        row = self.connection.execute(
            """SELECT post_pool_observation_id FROM post_pool_observations
               WHERE post_id = ? AND pool_native_id = ? AND observation_digest = ?""",
            (post_id, record.pool_native_id, digest),
        ).fetchone()
        if row is None:
            raise RuntimeError("failed to store post pool observation")
        return WriteResult(int(row[0]), "inserted" if cursor.rowcount else "existing")

    def record_post_flag(
        self,
        post_id: int,
        record: PostFlagObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "flag_name": record.flag_name,
                    "flag_value": record.flag_value,
                    "observed_at": record.observed_at,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        cursor = self.connection.execute(
            """INSERT INTO post_flag_observations (
                   post_id, flag_name, flag_value, observed_at, raw_observation_id,
                   observation_digest
               ) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (
                post_id,
                record.flag_name,
                record.flag_value,
                record.observed_at,
                raw_observation_id,
                digest,
            ),
        )
        row = self.connection.execute(
            """SELECT post_flag_observation_id FROM post_flag_observations
               WHERE post_id = ? AND flag_name = ? AND observation_digest = ?""",
            (post_id, record.flag_name, digest),
        ).fetchone()
        if row is None:
            raise RuntimeError("failed to store post flag observation")
        return WriteResult(int(row[0]), "inserted" if cursor.rowcount else "existing")

    def upsert_attribution(
        self,
        record: AttributionRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        record_platform_id = platform_id(self.connection, record.platform)
        prior = self.connection.execute(
            """SELECT attribution_entity_id FROM attribution_entities
               WHERE platform_id = ? AND instance_host = ?
                 AND provider_attribution_id = ?""",
            (record_platform_id, record.instance_host, record.native_id),
        ).fetchone()
        self.connection.execute(
            """INSERT INTO attribution_entities (
                   platform_id, instance_host, provider_attribution_id, adapter_version,
                   availability, first_seen_at, last_seen_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(platform_id, instance_host, provider_attribution_id) DO UPDATE SET
                   adapter_version = CASE
                       WHEN excluded.last_seen_at >= attribution_entities.last_seen_at
                       THEN excluded.adapter_version ELSE attribution_entities.adapter_version END,
                   availability = CASE
                       WHEN excluded.last_seen_at >= attribution_entities.last_seen_at
                       THEN excluded.availability ELSE attribution_entities.availability END,
                   first_seen_at = MIN(attribution_entities.first_seen_at, excluded.first_seen_at),
                   last_seen_at = MAX(attribution_entities.last_seen_at, excluded.last_seen_at)""",
            (
                record_platform_id,
                record.instance_host,
                record.native_id,
                record.adapter_version,
                record.availability,
                record.observed_at,
                record.observed_at,
            ),
        )
        entity_id = int(
            self.connection.execute(
                """SELECT attribution_entity_id FROM attribution_entities
                   WHERE platform_id = ? AND instance_host = ?
                     AND provider_attribution_id = ?""",
                (record_platform_id, record.instance_host, record.native_id),
            ).fetchone()[0]
        )
        snapshot = {
            "availability": record.availability,
            "primary_name": record.primary_name,
            "other_names": record.other_names,
            "urls": record.urls,
            "group_name": record.group_name,
            "is_deleted": record.is_deleted,
            "is_banned": record.is_banned,
            "is_locked": record.is_locked,
            "linked_user_id": record.linked_user_id,
            "domains": record.domains,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
        snapshot_digest = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        snapshot_cursor = self.connection.execute(
            """INSERT INTO attribution_snapshots (
                   attribution_entity_id, observed_at, availability, is_deleted, group_name,
                   is_banned, is_locked, linked_user_id, provider_created_at,
                   provider_updated_at, snapshot_digest, raw_observation_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (
                entity_id,
                record.observed_at,
                record.availability,
                record.is_deleted,
                record.group_name,
                record.is_banned,
                record.is_locked,
                record.linked_user_id,
                record.created_at,
                record.updated_at,
                snapshot_digest,
                raw_observation_id,
            ),
        )
        if record.primary_name is not None:
            self._store_attribution_name(
                entity_id, record.primary_name, "primary", record.observed_at, raw_observation_id
            )
        for alias in record.other_names:
            self._store_attribution_name(
                entity_id, alias, "alias", record.observed_at, raw_observation_id
            )
        for url in record.urls:
            self.connection.execute(
                """INSERT INTO attribution_urls (
                       attribution_entity_id, url, observed_at, raw_observation_id
                   ) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING""",
                (entity_id, url, record.observed_at, raw_observation_id),
            )
        for domain in record.domains:
            self.connection.execute(
                """INSERT INTO attribution_urls (
                       attribution_entity_id, url, url_kind, observed_at, raw_observation_id
                   ) VALUES (?, ?, 'domain', ?, ?) ON CONFLICT DO NOTHING""",
                (entity_id, domain, record.observed_at, raw_observation_id),
            )
        outcome = (
            "inserted" if prior is None else ("updated" if snapshot_cursor.rowcount else "existing")
        )
        return WriteResult(entity_id, outcome)

    def _store_attribution_name(
        self,
        entity_id: int,
        name: str,
        kind: str,
        observed_at: str,
        raw_observation_id: int | None,
    ) -> None:
        self.connection.execute(
            """INSERT INTO attribution_names (
                   attribution_entity_id, name, name_kind, observed_at, raw_observation_id
               ) VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (entity_id, name, kind, observed_at, raw_observation_id),
        )

    def add_post_external_reference(
        self,
        post_id: int,
        record: PostExternalReferenceRecord,
        *,
        raw_observation_id: int,
    ) -> int:
        link_id: int | None = None
        reference_id: int | None = None
        if record.url is not None:
            self.connection.execute(
                """INSERT INTO external_links (
                       canonical_url, canonicalization_version, resolution_state
                   ) VALUES (?, 'provider-metadata-v1', 'unresolved')
                   ON CONFLICT(canonical_url, canonicalization_version) DO NOTHING""",
                (record.url,),
            )
            link_id = int(
                self.connection.execute(
                    """SELECT external_link_id FROM external_links
                       WHERE canonical_url = ?
                         AND canonicalization_version = 'provider-metadata-v1'""",
                    (record.url,),
                ).fetchone()[0]
            )
        if record.target_platform is not None:
            record_platform_id = platform_id(self.connection, record.target_platform)
            target_id = record.target_native_id or ""
            target_kind = record.target_object_kind or ""
            identifier_kind = record.target_identifier_kind or ""
            canonical_url = record.url or _reference_url(
                record.target_platform, target_kind, target_id
            )
            self.connection.execute(
                """INSERT INTO platform_references (
                       platform_id, instance_host, object_kind, identifier_kind,
                       native_identifier, canonical_target_url, recognizer_name,
                       recognizer_version
                   ) VALUES (?, '', ?, ?, ?, ?, 'provider-metadata', 'provider-metadata-v1')
                   ON CONFLICT DO NOTHING""",
                (record_platform_id, target_kind, identifier_kind, target_id, canonical_url),
            )
            reference_id = int(
                self.connection.execute(
                    """SELECT platform_reference_id FROM platform_references
                       WHERE platform_id = ? AND instance_host = '' AND object_kind = ?
                         AND identifier_kind = ? AND native_identifier = ?
                         AND recognizer_version = 'provider-metadata-v1'""",
                    (record_platform_id, target_kind, identifier_kind, target_id),
                ).fetchone()[0]
            )
            if link_id is not None:
                self.connection.execute(
                    """INSERT INTO external_link_references (
                           external_link_id, platform_reference_id
                       ) VALUES (?, ?) ON CONFLICT DO NOTHING""",
                    (link_id, reference_id),
                )
        self.connection.execute(
            """INSERT INTO post_external_references (
                   post_id, external_link_id, platform_reference_id, reference_kind,
                   raw_observation_id, observed_at
               ) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (
                post_id,
                link_id,
                reference_id,
                record.reference_kind,
                raw_observation_id,
                record.observed_at,
            ),
        )
        return int(
            self.connection.execute(
                """SELECT post_external_reference_id FROM post_external_references
                   WHERE post_id = ? AND external_link_id IS ? AND platform_reference_id IS ?
                     AND reference_kind = ? AND raw_observation_id = ?""",
                (post_id, link_id, reference_id, record.reference_kind, raw_observation_id),
            ).fetchone()[0]
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
        observed_at = normalize_timestamp(observed_at)
        if not url or not source_context:
            raise ValueError("account external URL and source context are required")
        self.connection.execute(
            """INSERT INTO external_links (
                   canonical_url, canonicalization_version, resolution_state
               ) VALUES (?, 'provider-metadata-v1', 'unresolved')
               ON CONFLICT(canonical_url, canonicalization_version) DO NOTHING""",
            (url,),
        )
        link_id = int(
            self.connection.execute(
                """SELECT external_link_id FROM external_links
                   WHERE canonical_url = ?
                     AND canonicalization_version = 'provider-metadata-v1'""",
                (url,),
            ).fetchone()[0]
        )
        self.connection.execute(
            """INSERT INTO account_external_links (
                   account_id, external_link_id, source_context, raw_observation_id, observed_at
               ) VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (account_id, link_id, source_context, raw_observation_id, observed_at),
        )
        return int(
            self.connection.execute(
                """SELECT account_external_link_id FROM account_external_links
                   WHERE account_id = ? AND external_link_id = ? AND source_context = ?
                     AND raw_observation_id = ?""",
                (account_id, link_id, source_context, raw_observation_id),
            ).fetchone()[0]
        )
