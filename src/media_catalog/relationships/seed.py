"""Deterministic relationship seeding from retained evidence.

Four kinds are already provable without any fuzzy judgment and seed
offline: ``same_bytes`` from verified content deduplication (SHA-256),
``thumbnail_of`` from provider-declared occurrence variant roles,
``reposted_from`` from provider-declared source-URL references that resolve
to another catalog post, and ``parent_of`` from retained provider-declared
post parent relations.  Every seeded relationship carries evidence naming
its detector and version; none of them establishes identity, authorship, or
same-work beyond what the evidence proves.
"""

from __future__ import annotations

from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.records import RelationshipRecord
from media_catalog.writer import CatalogWriter

SEEDER_VERSION = "relationship-seeder-v1"


def _add(
    writer: CatalogWriter,
    record: RelationshipRecord,
    *,
    evidence_kind: str,
    direction: str,
    strength: str,
    detector: str,
    observed_at: str,
    explanation: str,
    components: dict[str, Any] | None = None,
    platform_reference_id: int | None = None,
) -> str:
    result = writer.insert_relationship(record)
    evidence_id = writer.insert_relationship_evidence_row(
        evidence_kind=evidence_kind,
        direction=direction,
        strength=strength,
        detector=detector,
        detector_version=SEEDER_VERSION,
        observed_at=observed_at,
        explanation=explanation,
        components=components,
        platform_reference_id=platform_reference_id,
    )
    writer.attach_relationship_evidence(result.id, evidence_id, observed_at)
    return result.outcome


def _seed_same_bytes(database: CatalogDatabase, writer: CatalogWriter, now: str) -> dict[str, int]:
    materialized = existing = 0
    rows = database.connection.execute(
        """SELECT oa1.media_occurrence_id AS first_id, oa2.media_occurrence_id AS second_id,
                  lower(a.verified_sha256) AS sha256
             FROM occurrence_assets oa1
             JOIN occurrence_assets oa2
               ON oa1.asset_id = oa2.asset_id
              AND oa1.media_occurrence_id < oa2.media_occurrence_id
             JOIN assets a ON a.asset_id = oa1.asset_id
         ORDER BY oa1.media_occurrence_id, oa2.media_occurrence_id"""
    ).fetchall()
    for row in rows:
        outcome = _add(
            writer,
            RelationshipRecord(
                subject_kind="media_occurrence",
                subject_id=int(row["first_id"]),
                relation_kind="same_bytes",
                target_kind="media_occurrence",
                target_id=int(row["second_id"]),
                epistemic_status="verified",
                created_at=now,
            ),
            evidence_kind="hash_equality",
            direction="symmetric",
            strength="exact",
            detector="asset-sha256",
            observed_at=now,
            explanation=(
                "Both representations resolve to the same verified bytes "
                f"(sha256 {str(row['sha256'])[:16]}...)."
            ),
            components={"sha256": str(row["sha256"])},
        )
        materialized += outcome == "inserted"
        existing += outcome == "existing"
    return {"materialized": materialized, "existing": existing}


def _seed_thumbnail_of(
    database: CatalogDatabase, writer: CatalogWriter, now: str
) -> dict[str, int]:
    materialized = existing = skipped = 0
    # Occurrence-level roles only: e621 declares original/sample/preview per
    # occurrence, while danbooru carries role NULL with variant roles inside
    # variants_json below occurrence level.  Variant-level thumbnail linking
    # waits for Phase D occurrence-variant objects; do not flatten
    # sub-occurrence variants into occurrence relations here.
    rows = database.connection.execute(
        """SELECT t.media_occurrence_id AS thumbnail_id, t.role AS role,
                  o.media_occurrence_id AS original_id
             FROM media_occurrences t
             JOIN media_occurrences o
               ON o.post_id = t.post_id AND o.role = 'original'
            WHERE t.role IN ('sample', 'preview')
         ORDER BY t.media_occurrence_id"""
    ).fetchall()
    for row in rows:
        if row["thumbnail_id"] == row["original_id"]:
            skipped += 1
            continue
        outcome = _add(
            writer,
            RelationshipRecord(
                subject_kind="media_occurrence",
                subject_id=int(row["thumbnail_id"]),
                relation_kind="thumbnail_of",
                target_kind="media_occurrence",
                target_id=int(row["original_id"]),
                epistemic_status="observed",
                created_at=now,
            ),
            evidence_kind="provider_variant_role",
            direction="subject_to_target",
            strength="moderate",
            detector="occurrence-role",
            observed_at=now,
            explanation=(
                f"The provider declares this occurrence as {row['role']!s} "
                "alongside an original within the same post."
            ),
            components={"role": str(row["role"])},
        )
        materialized += outcome == "inserted"
        existing += outcome == "existing"
    # Sample/preview occurrences whose post declares no original are skipped.
    skipped += int(
        database.connection.execute(
            """SELECT COUNT(*) FROM media_occurrences t
                WHERE t.role IN ('sample', 'preview')
                  AND NOT EXISTS (SELECT 1 FROM media_occurrences o
                                   WHERE o.post_id = t.post_id AND o.role = 'original')"""
        ).fetchone()[0]
    )
    return {"materialized": materialized, "existing": existing, "skipped": skipped}


def _seed_reposted_from(
    database: CatalogDatabase, writer: CatalogWriter, now: str
) -> dict[str, Any]:
    # Source URLs retained only as external links (no platform reference, or
    # one that does not name a post) can never resolve to a catalog post; the
    # JOIN below drops them silently, so count them as skippable up front.
    reasons = {
        "source_url_unresolved": int(
            database.connection.execute(
                """SELECT COUNT(*) FROM post_external_references per
                    LEFT JOIN platform_references pr
                      ON pr.platform_reference_id = per.platform_reference_id
                   WHERE per.reference_kind = 'source_url'
                     AND (per.platform_reference_id IS NULL OR pr.object_kind != 'post')"""
            ).fetchone()[0]
        ),
        "target_post_unresolved": 0,
        "self_reference": 0,
    }
    materialized = existing = 0
    rows = database.connection.execute(
        """SELECT per.post_id AS citing_post_id,
                  COALESCE(pr.resolved_post_id,
                           (SELECT p.post_id FROM posts p
                             WHERE p.platform_id = pr.platform_id
                               AND p.native_post_id = pr.native_identifier)) AS cited_post_id,
                  per.platform_reference_id AS platform_reference_id,
                  per.observed_at AS observed_at
             FROM post_external_references per
             JOIN platform_references pr
               ON pr.platform_reference_id = per.platform_reference_id
            WHERE per.reference_kind = 'source_url'
              AND pr.object_kind = 'post'
         ORDER BY per.post_external_reference_id"""
    ).fetchall()
    for row in rows:
        cited = row["cited_post_id"]
        if cited is None:
            reasons["target_post_unresolved"] += 1
            continue
        if int(cited) == int(row["citing_post_id"]):
            reasons["self_reference"] += 1
            continue
        outcome = _add(
            writer,
            RelationshipRecord(
                subject_kind="post",
                subject_id=int(row["citing_post_id"]),
                relation_kind="reposted_from",
                target_kind="post",
                target_id=int(cited),
                epistemic_status="observed",
                created_at=now,
            ),
            evidence_kind="provider_source_url",
            direction="subject_to_target",
            strength="moderate",
            detector="source-url-reference",
            observed_at=str(row["observed_at"]),
            explanation="The provider declares the cited post's URL as this post's source.",
            platform_reference_id=int(row["platform_reference_id"]),
        )
        materialized += outcome == "inserted"
        existing += outcome == "existing"
    return {
        "materialized": materialized,
        "existing": existing,
        "skipped": sum(reasons.values()),
        "skipped_reasons": reasons,
    }


def _seed_parent_of(database: CatalogDatabase, writer: CatalogWriter, now: str) -> dict[str, int]:
    materialized = existing = skipped = 0
    rows = database.connection.execute(
        """SELECT pr.source_post_id, pr.target_post_id, pr.raw_observation_id
             FROM post_relations pr
            WHERE pr.relation_type = 'parent_of'
         ORDER BY pr.source_post_id, pr.target_post_id"""
    ).fetchall()
    for row in rows:
        if row["source_post_id"] == row["target_post_id"]:
            skipped += 1
            continue
        outcome = _add(
            writer,
            RelationshipRecord(
                subject_kind="post",
                subject_id=int(row["source_post_id"]),
                relation_kind="parent_of",
                target_kind="post",
                target_id=int(row["target_post_id"]),
                epistemic_status="observed",
                created_at=now,
            ),
            evidence_kind="provider_parent_relation",
            direction="subject_to_target",
            strength="moderate",
            detector="provider-parent-relation",
            observed_at=now,
            explanation="The provider declares the subject post as the parent of the target.",
            components={"raw_observation_id": row["raw_observation_id"]},
        )
        materialized += outcome == "inserted"
        existing += outcome == "existing"
    return {"materialized": materialized, "existing": existing, "skipped": skipped}


def seed_relationships(database: CatalogDatabase, *, clock: Any) -> dict[str, Any]:
    """Materialize the deterministic relationship kinds offline and idempotently."""

    now = str(clock())
    with database.transaction():
        writer = CatalogWriter(database)
        same_bytes = _seed_same_bytes(database, writer, now)
        thumbnails = _seed_thumbnail_of(database, writer, now)
        reposts = _seed_reposted_from(database, writer, now)
        parents = _seed_parent_of(database, writer, now)
    return {
        "seeder_version": SEEDER_VERSION,
        "same_bytes": same_bytes,
        "thumbnail_of": thumbnails,
        "reposted_from": reposts,
        "parent_of": parents,
    }
