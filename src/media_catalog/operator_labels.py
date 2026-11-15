"""Operator labels: free-form local facts on catalog subjects (bead
``data-processing-j7l``, change ``add-operator-labels``).

Labels are operator-invented names ("ai-generated", "needs-review", a batch
name) that double as groupings.  They are never provider tags: applications are
append-only assertions attributed to the operator, and the current state of a
(label, subject) pair is the latest assertion.  A label covers identical
content regardless of platform: search expands along byte-identical links —
file seeds sharing a verified hash pair, and posts sharing an md5 with a seed
or another post.  Variants never inherit.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

SUBJECT_KINDS = ("file_seed", "post", "asset", "work")

# Polymorphic subject resolution, the relationships precedent: kind plus the
# table owning the primary key.
_SUBJECT_TABLES: dict[str, tuple[str, str]] = {
    "file_seed": ("discovery_file_seeds", "discovery_file_seed_id"),
    "post": ("posts", "post_id"),
    "asset": ("assets", "asset_id"),
    "work": ("works", "work_id"),
}

DEFAULT_OPERATOR = "operator"


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    # Row iteration yields values, so .keys() is required here (SIM118 is a
    # dict-protocol false positive).
    return {str(key): row[key] for key in row.keys()}  # noqa: SIM118


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _label_row(connection: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT operator_label_id, name, description, created_at, retired_at"
        " FROM operator_labels WHERE name = ? COLLATE NOCASE",
        (name,),
    ).fetchone()


def _require_subject(connection: sqlite3.Connection, kind: str, subject_id: int) -> None:
    table, pk = _SUBJECT_TABLES[kind]
    row = connection.execute(
        f"SELECT {pk} FROM {table} WHERE {pk} = ?",  # constant table names
        (subject_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"subject {kind}:{subject_id} not found")


def create_label(
    connection: sqlite3.Connection, name: str, *, description: str | None = None
) -> dict[str, Any]:
    """Create a label; creating an identical active label is a no-op."""
    name = name.strip()
    if not 1 <= len(name) <= 100:
        raise ValueError("label name must be 1-100 characters")
    existing = _label_row(connection, name)
    if existing is not None:
        if existing["retired_at"] is not None:
            raise ValueError(f"label {name!r} is retired; pick a new name (history is kept)")
        return {"status": "existing", **dict(existing)}
    connection.execute(
        """INSERT INTO operator_labels (name, description, created_at)
           VALUES (?, ?, ?)""",
        (name, description, _now()),
    )
    connection.commit()
    created = _label_row(connection, name)
    assert created is not None
    return {"status": "created", **_row_dict(created)}


def retire_label(connection: sqlite3.Connection, name: str) -> dict[str, Any]:
    row = _label_row(connection, name)
    if row is None:
        raise ValueError(f"label {name!r} not found")
    if row["retired_at"] is None:
        connection.execute(
            "UPDATE operator_labels SET retired_at = ? WHERE operator_label_id = ?",
            (_now(), int(row["operator_label_id"])),
        )
        connection.commit()
    retired = _label_row(connection, name)
    assert retired is not None
    return {"status": "retired", **_row_dict(retired)}


def list_labels(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Labels with their current application counts; history is never lost."""
    rows = connection.execute(
        """SELECT l.operator_label_id, l.name, l.description, l.created_at,
                  l.retired_at,
                  (SELECT count(*) FROM operator_label_assertions a
                    WHERE a.operator_label_id = l.operator_label_id) AS assertions,
                  (SELECT count(*) FROM (
                        SELECT 1 FROM operator_label_assertions a
                         WHERE a.operator_label_id = l.operator_label_id
                           AND a.state = 'applied'
                           AND NOT EXISTS (
                               SELECT 1 FROM operator_label_assertions b
                                WHERE b.operator_label_id = a.operator_label_id
                                  AND b.subject_kind = a.subject_kind
                                  AND b.subject_id = a.subject_id
                                  AND (b.observed_at, b.operator_label_assertion_id) >
                                      (a.observed_at, a.operator_label_assertion_id)
                           )
                       )) AS applied_subjects
             FROM operator_labels l
            ORDER BY l.name COLLATE NOCASE"""
    )
    return [_row_dict(row) for row in rows]


def _assert(
    connection: sqlite3.Connection,
    name: str,
    kind: str,
    subject_id: int,
    state: str,
    *,
    by: str,
    note: str | None,
) -> dict[str, Any]:
    if kind not in SUBJECT_KINDS:
        raise ValueError(f"subject kind must be one of {', '.join(SUBJECT_KINDS)}")
    by = by.strip()
    if not 1 <= len(by) <= 200:
        raise ValueError("asserted_by must be 1-200 characters")
    label = _label_row(connection, name)
    if label is None:
        raise ValueError(f"label {name!r} not found")
    if label["retired_at"] is not None and state == "applied":
        raise ValueError(f"label {name!r} is retired")
    _require_subject(connection, kind, subject_id)
    connection.execute(
        """INSERT INTO operator_label_assertions
               (operator_label_id, subject_kind, subject_id, state, asserted_by,
                note, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (int(label["operator_label_id"]), kind, subject_id, state, by, note, _now()),
    )
    connection.commit()
    return {
        "label": name,
        "subject": f"{kind}:{subject_id}",
        "state": state,
        "asserted_by": by,
    }


def apply_label(
    connection: sqlite3.Connection,
    name: str,
    kind: str,
    subject_id: int,
    *,
    by: str = DEFAULT_OPERATOR,
    note: str | None = None,
) -> dict[str, Any]:
    return _assert(connection, name, kind, subject_id, "applied", by=by, note=note)


def revoke_label(
    connection: sqlite3.Connection,
    name: str,
    kind: str,
    subject_id: int,
    *,
    by: str = DEFAULT_OPERATOR,
    note: str | None = None,
) -> dict[str, Any]:
    return _assert(connection, name, kind, subject_id, "revoked", by=by, note=note)


def _current_assertions(
    connection: sqlite3.Connection, *, label_id: int | None = None
) -> list[sqlite3.Row]:
    """Latest assertion per (label, subject); applied state only."""
    clause = "WHERE a.operator_label_id = ?" if label_id is not None else ""
    params: tuple[Any, ...] = (label_id,) if label_id is not None else ()
    return list(
        connection.execute(
            f"""SELECT * FROM (
                    SELECT a.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY a.operator_label_id, a.subject_kind,
                                            a.subject_id
                               ORDER BY a.observed_at DESC,
                                        a.operator_label_assertion_id DESC
                           ) AS recency
                      FROM operator_label_assertions a
                     {clause}
                )
                WHERE recency = 1 AND state = 'applied'
                ORDER BY subject_kind, subject_id""",
            params,
        )
    )


def _identical_subjects(
    connection: sqlite3.Connection, kind: str, subject_id: int
) -> list[tuple[str, int]]:
    """Byte-identical subjects only: shared verified hash pair (seeds) or
    shared md5 between a seed's verified hash and post occurrences."""
    identical: set[tuple[str, int]] = set()
    if kind == "file_seed":
        for row in connection.execute(
            """SELECT discovery_file_seed_id FROM discovery_file_seeds
                WHERE verified_md5 = (SELECT verified_md5 FROM discovery_file_seeds
                                       WHERE discovery_file_seed_id = ?)
                  AND verified_sha256 = (SELECT verified_sha256 FROM discovery_file_seeds
                                          WHERE discovery_file_seed_id = ?)""",
            (subject_id, subject_id),
        ):
            identical.add(("file_seed", int(row[0])))
        for row in connection.execute(
            """SELECT DISTINCT mo.post_id FROM media_occurrences mo
                WHERE mo.declared_md5 = (SELECT verified_md5 FROM discovery_file_seeds
                                          WHERE discovery_file_seed_id = ?)""",
            (subject_id,),
        ):
            identical.add(("post", int(row[0])))
    elif kind == "post":
        for row in connection.execute(
            """SELECT DISTINCT other.post_id
                 FROM media_occurrences mine
                 JOIN media_occurrences other ON other.declared_md5 = mine.declared_md5
                WHERE mine.post_id = ? AND other.post_id != ?""",
            (subject_id, subject_id),
        ):
            identical.add(("post", int(row[0])))
        for row in connection.execute(
            """SELECT s.discovery_file_seed_id
                 FROM discovery_file_seeds s
                 JOIN media_occurrences mo ON mo.declared_md5 = s.verified_md5
                WHERE mo.post_id = ?""",
            (subject_id,),
        ):
            identical.add(("file_seed", int(row[0])))
    identical.discard((kind, subject_id))
    return sorted(identical)


def current_labels(
    connection: sqlite3.Connection, kind: str, subject_id: int, *, include_identical: bool = True
) -> dict[str, Any]:
    """Labels carried by a subject: directly, and via identical content."""
    if kind not in SUBJECT_KINDS:
        raise ValueError(f"subject kind must be one of {', '.join(SUBJECT_KINDS)}")
    _require_subject(connection, kind, subject_id)
    subjects = {(kind, subject_id)}
    inherited: dict[tuple[str, int], list[str]] = {}
    if include_identical:
        for other_kind, other_id in _identical_subjects(connection, kind, subject_id):
            subjects.add((other_kind, other_id))
    direct: dict[str, dict[str, Any]] = {}
    labels_by_id: dict[int, str] = {
        int(row["operator_label_id"]): str(row["name"])
        for row in connection.execute("SELECT operator_label_id, name FROM operator_labels")
    }
    for row in _current_assertions(connection):
        key = (str(row["subject_kind"]), int(row["subject_id"]))
        label = labels_by_id.get(int(row["operator_label_id"]))
        if label is None:
            continue
        if key == (kind, subject_id):
            direct[label] = {
                "state": "applied",
                "basis": "direct",
                "asserted_by": str(row["asserted_by"]),
                "observed_at": str(row["observed_at"]),
            }
        elif key in subjects:
            inherited.setdefault(key, []).append(label)
    return {
        "subject": f"{kind}:{subject_id}",
        "labels": direct,
        "identical_content": [
            {"subject": f"{k}:{i}", "labels": sorted(v)} for (k, i), v in sorted(inherited.items())
        ],
    }


def search_label(connection: sqlite3.Connection, name: str, *, limit: int = 200) -> dict[str, Any]:
    """Subjects carrying a label, directly or by identical content."""
    label = _label_row(connection, name)
    if label is None:
        raise ValueError(f"label {name!r} not found")
    label_id = int(label["operator_label_id"])
    direct_rows = _current_assertions(connection, label_id=label_id)
    direct = {(str(row["subject_kind"]), int(row["subject_id"])) for row in direct_rows}
    expanded: dict[tuple[str, int], list[tuple[str, int]]] = {}
    seen = set(direct)
    for kind, subject_id in sorted(direct):
        for other in _identical_subjects(connection, kind, subject_id):
            if other not in seen:
                expanded.setdefault(other, []).append((kind, subject_id))
                seen.add(other)
    direct_list = [{"subject": f"{k}:{i}", "basis": "direct"} for k, i in sorted(direct)]
    expanded_list = [
        {
            "subject": f"{k}:{i}",
            "basis": "identical-content",
            "via": [f"{vk}:{vi}" for vk, vi in sorted(via)],
        }
        for (k, i), via in sorted(expanded.items())
    ]
    return {
        "label": dict(label),
        "subjects": direct_list[:limit],
        "subjects_total": len(direct_list),
        "identical_content_subjects": expanded_list[:limit],
        "identical_content_total": len(expanded_list),
        "truncated": len(direct_list) > limit or len(expanded_list) > limit,
    }
