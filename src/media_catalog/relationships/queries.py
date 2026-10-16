"""Privacy-safe query surfaces over works and relationships."""

from __future__ import annotations

import sqlite3
from typing import Any

from media_catalog.database import CatalogDatabase


def list_relationships(
    database: CatalogDatabase | sqlite3.Connection,
    *,
    relation_kind: str | None = None,
    epistemic_status: str | None = None,
    review_state: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    connection = database.connection if isinstance(database, CatalogDatabase) else database
    clauses: list[str] = []
    values: list[Any] = []
    if relation_kind is not None:
        clauses.append("r.relation_kind = ?")
        values.append(relation_kind)
    if epistemic_status is not None:
        clauses.append("r.epistemic_status = ?")
        values.append(epistemic_status)
    if review_state is not None:
        clauses.append("r.review_state = ?")
        values.append(review_state)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"""SELECT r.relationship_id, r.relation_kind, r.epistemic_status, r.review_state,
                   r.subject_kind, r.subject_id, r.target_kind, r.target_id,
                   r.created_at, r.updated_at
              FROM relationships r {where}
             ORDER BY r.relationship_id
             LIMIT ?""",
        values,
    ).fetchall()
    labeled: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        record["subject"] = _resolve(connection, str(row["subject_kind"]), int(row["subject_id"]))
        record["target"] = _resolve(connection, str(row["target_kind"]), int(row["target_id"]))
        labeled.append(record)
    return labeled


def _resolve(connection: sqlite3.Connection, kind: str, object_id: int) -> str:
    if kind == "work":
        row = connection.execute(
            """SELECT pl.platform_key, op.native_post_id FROM works w
                 JOIN posts op ON op.post_id = w.origin_post_id
                 JOIN platforms pl ON pl.platform_id = op.platform_id
                WHERE w.work_id = ?""",
            (object_id,),
        ).fetchone()
        return f"work:{row[0]}:{row[1]}" if row else f"work:{object_id}"
    if kind == "post":
        row = connection.execute(
            """SELECT pl.platform_key, p.native_post_id FROM posts p
                 JOIN platforms pl ON pl.platform_id = p.platform_id WHERE p.post_id = ?""",
            (object_id,),
        ).fetchone()
        return f"post:{row[0]}:{row[1]}" if row else f"post:{object_id}"
    if kind == "media_occurrence":
        return f"occurrence:{object_id}"
    return f"asset:{object_id}"


def get_relationship(database: CatalogDatabase, relationship_id: int) -> dict[str, Any] | None:
    rows = list_relationships(database, limit=100_000)
    for row in rows:
        if row["relationship_id"] == relationship_id:
            row["evidence"] = [
                {
                    "evidence_id": int(evidence["evidence_id"]),
                    "stance": str(evidence["stance"]),
                    "evidence_kind": str(evidence["evidence_kind"]),
                    "strength": str(evidence["strength"]),
                    "detector": str(evidence["detector"]),
                    "detector_version": str(evidence["detector_version"]),
                    "explanation": str(evidence["explanation"]),
                }
                for evidence in database.connection.execute(
                    """SELECT me.evidence_id, me.stance, me.evidence_kind, me.strength,
                              me.detector, me.detector_version, me.explanation
                         FROM relationship_evidence re
                         JOIN match_evidence me ON me.evidence_id = re.evidence_id
                        WHERE re.relationship_id = ?
                        ORDER BY me.evidence_id""",
                    (relationship_id,),
                )
            ]
            row["decisions"] = [
                {
                    "relationship_decision_id": int(decision["relationship_decision_id"]),
                    "prior_state": str(decision["prior_state"]),
                    "decision": str(decision["decision"]),
                    "decided_at": str(decision["decided_at"]),
                }
                for decision in database.connection.execute(
                    """SELECT relationship_decision_id, prior_state, decision, decided_at
                         FROM relationship_review_decisions
                        WHERE relationship_id = ? ORDER BY relationship_decision_id""",
                    (relationship_id,),
                )
            ]
            row["status_history"] = [
                {
                    "prior_status": str(entry["prior_status"]),
                    "new_status": str(entry["new_status"]),
                    "cause": str(entry["cause"]),
                    "at": str(entry["at"]),
                }
                for entry in database.connection.execute(
                    """SELECT prior_status, new_status, cause, at
                         FROM relationship_status_history
                        WHERE relationship_id = ?
                        ORDER BY relationship_status_history_id""",
                    (relationship_id,),
                )
            ]
            return row
    return None


def list_works(
    database: CatalogDatabase | sqlite3.Connection, *, limit: int = 200
) -> list[dict[str, Any]]:
    connection = database.connection if isinstance(database, CatalogDatabase) else database
    return [
        {
            "work_id": int(row["work_id"]),
            "origin": f"{row['platform_key']}:{row['native_post_id']}",
            "work_kind": str(row["work_kind"]),
            "representation_count": int(row["representation_count"]),
            "created_at": str(row["created_at"]),
        }
        for row in connection.execute(
            """SELECT w.work_id, w.work_kind, w.created_at, pl.platform_key,
                      op.native_post_id,
                      (SELECT COUNT(*) FROM work_representations wr
                        WHERE wr.work_id = w.work_id) AS representation_count
                 FROM works w
                 JOIN posts op ON op.post_id = w.origin_post_id
                 JOIN platforms pl ON pl.platform_id = op.platform_id
             ORDER BY w.work_id LIMIT ?""",
            (limit,),
        )
    ]
