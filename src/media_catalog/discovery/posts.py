from __future__ import annotations

import json
from typing import Any

from media_catalog.discovery.support import STRENGTH_SCORES, digest, now, parse_match_ref
from media_catalog.records import validate_relation


class PostMatchManager:
    """Manage manually asserted post characteristics and relationships."""

    def __init__(self, database: Any) -> None:
        self.database = database
        self.connection = database.connection

    def add_characteristic(
        self,
        match_ref: str,
        characteristic: str,
        *,
        direction: str = "none",
        source_label: str = "manual",
    ) -> None:
        kind, candidate_id = parse_match_ref(match_ref)
        if kind != "post":
            raise ValueError("image characteristics apply only to post candidates")
        with self.database.transaction():
            self.connection.execute(
                """INSERT INTO post_candidate_characteristics
                   (post_candidate_id, characteristic, direction, source_label, added_at)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
                (candidate_id, characteristic, direction, source_label, now()),
            )

    def create_post_candidate(
        self,
        subject_post_id: int,
        target_post_id: int,
        relation: str,
        *,
        explanation: str,
        strength: str = "moderate",
        scoring_version: str,
    ) -> str:
        validate_relation(relation, candidate_kind="post")
        if subject_post_id == target_post_id:
            raise ValueError("post candidate endpoints must be different")
        if strength not in STRENGTH_SCORES:
            raise ValueError(f"unsupported evidence strength: {strength}")
        if relation == "same_work":
            subject_post_id, target_post_id = sorted((subject_post_id, target_post_id))
        key = digest("post", subject_post_id, relation, "local", target_post_id)
        timestamp = now()
        with self.database.transaction():
            self.connection.execute(
                """INSERT INTO post_match_candidates
                   (candidate_key, subject_post_id, target_post_id, relation_kind,
                    score_version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(candidate_key) DO NOTHING""",
                (
                    key,
                    subject_post_id,
                    target_post_id,
                    relation,
                    scoring_version,
                    timestamp,
                    timestamp,
                ),
            )
            candidate_id = int(
                self.connection.execute(
                    """SELECT post_candidate_id FROM post_match_candidates
                       WHERE candidate_key = ?""",
                    (key,),
                ).fetchone()[0]
            )
            evidence_digest = digest("manual", key, explanation, strength)
            self.connection.execute(
                """INSERT INTO match_evidence
                   (evidence_digest, stance, evidence_kind, direction, strength, detector,
                    detector_version, observed_at, explanation, components_json)
                   VALUES (?, 'supports', 'manual_assessment', ?, ?, 'manual', 'manual-v1',
                           ?, ?, ?) ON CONFLICT DO NOTHING""",
                (
                    evidence_digest,
                    "symmetric" if relation == "same_work" else "subject_to_target",
                    strength,
                    timestamp,
                    explanation,
                    json.dumps({"strength_points": STRENGTH_SCORES[strength]}, sort_keys=True),
                ),
            )
            evidence_id = int(
                self.connection.execute(
                    "SELECT evidence_id FROM match_evidence WHERE evidence_digest = ?",
                    (evidence_digest,),
                ).fetchone()[0]
            )
            self.connection.execute(
                """INSERT INTO post_candidate_evidence (post_candidate_id, evidence_id)
                   VALUES (?, ?) ON CONFLICT DO NOTHING""",
                (candidate_id, evidence_id),
            )
            score = int(
                self.connection.execute(
                    """SELECT COALESCE(SUM(CASE e.strength WHEN 'exact' THEN 100
                               WHEN 'strong' THEN 70 WHEN 'moderate' THEN 35 ELSE 10 END), 0)
                       FROM post_candidate_evidence ce JOIN match_evidence e USING (evidence_id)
                       WHERE ce.post_candidate_id = ? AND e.stance = 'supports'""",
                    (candidate_id,),
                ).fetchone()[0]
            )
            generation = int(
                self.connection.execute(
                    """SELECT COUNT(*) FROM post_candidate_evidence
                       WHERE post_candidate_id = ?""",
                    (candidate_id,),
                ).fetchone()[0]
            )
            self.connection.execute(
                """UPDATE post_match_candidates SET score = ?, score_components_json = ?,
                          evidence_generation = ?, updated_at = ? WHERE post_candidate_id = ?""",
                (
                    score,
                    json.dumps(
                        {"supporting_evidence": generation, "points": score}, sort_keys=True
                    ),
                    generation,
                    timestamp,
                    candidate_id,
                ),
            )
        return f"post:{candidate_id}"
