from __future__ import annotations

import json
from typing import Any

from media_catalog.discovery.support import STRENGTH_SCORES, digest
from media_catalog.records import LinkOccurrence


class CandidateGenerator:
    """Generate and score match candidates from recognized link observations."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def generate(
        self,
        occurrence: LinkOccurrence,
        observation_id: int,
        reference_id: int,
        now: str,
        *,
        extractor_version: str,
        scoring_version: str,
    ) -> None:
        reference = self.connection.execute(
            """SELECT object_kind, identifier_kind, resolved_account_id, resolved_post_id
               FROM platform_references WHERE platform_reference_id = ?""",
            (reference_id,),
        ).fetchone()
        if occurrence.subject_kind == "account" and reference["object_kind"] == "account":
            if reference["identifier_kind"] != "stable_id":
                return
            if reference["resolved_account_id"] == occurrence.subject_id:
                return
            self.upsert(
                "account",
                occurrence.subject_id,
                reference_id,
                reference["resolved_account_id"],
                "same_identity",
                observation_id,
                now,
                extractor_version=extractor_version,
                scoring_version=scoring_version,
            )
        elif occurrence.subject_kind == "post" and reference["object_kind"] == "post":
            if reference["resolved_post_id"] == occurrence.subject_id:
                return
            self.upsert(
                "post",
                occurrence.subject_id,
                reference_id,
                reference["resolved_post_id"],
                "sourced_from",
                observation_id,
                now,
                extractor_version=extractor_version,
                scoring_version=scoring_version,
            )

    def upsert(
        self,
        kind: str,
        subject_id: int,
        reference_id: int,
        resolved_id: int | None,
        relation: str,
        observation_id: int,
        now: str,
        *,
        extractor_version: str,
        scoring_version: str,
    ) -> None:
        semantic_reference = self.connection.execute(
            """SELECT platform_id, instance_host, object_kind, identifier_kind, native_identifier
               FROM platform_references WHERE platform_reference_id = ?""",
            (reference_id,),
        ).fetchone()
        legacy_key = digest(
            kind,
            subject_id,
            relation,
            semantic_reference["platform_id"],
            semantic_reference["instance_host"],
            semantic_reference["object_kind"],
            semantic_reference["native_identifier"],
        )
        key = digest(
            kind,
            subject_id,
            relation,
            semantic_reference["platform_id"],
            semantic_reference["instance_host"],
            semantic_reference["object_kind"],
            semantic_reference["identifier_kind"],
            semantic_reference["native_identifier"],
        )
        table = f"{kind}_match_candidates"
        id_column = f"{kind}_candidate_id"
        subject_column = f"subject_{kind}_id"
        target_column = f"target_{kind}_id"
        legacy_candidate = self.connection.execute(
            f"SELECT {id_column} FROM {table} WHERE candidate_key = ?",
            (legacy_key,),
        ).fetchone()
        if legacy_candidate is not None:
            self.connection.execute(
                f"UPDATE {table} SET candidate_key = ? WHERE {id_column} = ?",
                (key, legacy_candidate[id_column]),
            )
        self.connection.execute(
            f"""INSERT INTO {table}
                (candidate_key, {subject_column}, {target_column}, target_reference_id,
                 relation_kind, score_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(candidate_key) DO UPDATE SET
                 {target_column} = COALESCE({table}.{target_column}, excluded.{target_column}),
                 target_reference_id = CASE WHEN excluded.{target_column} IS NOT NULL THEN NULL
                                            ELSE excluded.target_reference_id END,
                 updated_at = excluded.updated_at""",
            (
                key,
                subject_id,
                resolved_id,
                None if resolved_id else reference_id,
                relation,
                scoring_version,
                now,
                now,
            ),
        )
        candidate_id = int(
            self.connection.execute(
                f"SELECT {id_column} FROM {table} WHERE candidate_key = ?", (key,)
            ).fetchone()[0]
        )
        occurrence_digest = self.connection.execute(
            """SELECT occurrence_digest FROM link_observations
               WHERE link_observation_id = ?""",
            (observation_id,),
        ).fetchone()[0]
        legacy_evidence_digest = digest(kind, legacy_key, occurrence_digest, "official_link")
        evidence_digest = digest(kind, key, occurrence_digest, "official_link")
        legacy_evidence = self.connection.execute(
            "SELECT evidence_id FROM match_evidence WHERE evidence_digest = ?",
            (legacy_evidence_digest,),
        ).fetchone()
        if legacy_evidence is not None:
            self.connection.execute(
                "UPDATE match_evidence SET evidence_digest = ? WHERE evidence_id = ?",
                (evidence_digest, legacy_evidence["evidence_id"]),
            )
        self.connection.execute(
            """INSERT INTO match_evidence
               (evidence_digest, stance, evidence_kind, direction, strength, detector,
                detector_version, link_observation_id, platform_reference_id, observed_at,
                explanation, components_json)
               VALUES (?, 'supports', 'official_link', 'subject_to_target', 'strong',
                       'link-discovery', ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (
                evidence_digest,
                extractor_version,
                observation_id,
                reference_id,
                now,
                "A catalog field directly links the subject to the target reference.",
                json.dumps({"strength_points": STRENGTH_SCORES["strong"]}, sort_keys=True),
            ),
        )
        evidence_id = int(
            self.connection.execute(
                "SELECT evidence_id FROM match_evidence WHERE evidence_digest = ?",
                (evidence_digest,),
            ).fetchone()[0]
        )
        join_table = f"{kind}_candidate_evidence"
        self.connection.execute(
            f"""INSERT INTO {join_table} ({id_column}, evidence_id)
                VALUES (?, ?) ON CONFLICT DO NOTHING""",
            (candidate_id, evidence_id),
        )
        score = self.connection.execute(
            f"""SELECT COALESCE(SUM(CASE e.strength WHEN 'exact' THEN 100 WHEN 'strong' THEN 70
                        WHEN 'moderate' THEN 35 ELSE 10 END), 0), COUNT(*)
                FROM {join_table} ce JOIN match_evidence e ON e.evidence_id = ce.evidence_id
                WHERE ce.{id_column} = ? AND e.stance = 'supports'""",
            (candidate_id,),
        ).fetchone()
        components = json.dumps(
            {"supporting_evidence": score[1], "points": score[0]}, sort_keys=True
        )
        self.connection.execute(
            f"""UPDATE {table} SET score = ?, score_components_json = ?,
                    evidence_generation = ?, updated_at = ? WHERE {id_column} = ?""",
            (score[0], components, score[1], now, candidate_id),
        )
