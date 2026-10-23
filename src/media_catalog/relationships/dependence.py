"""Evidence dependence: lineage groups derived from the relationship graph.

Observation count is not independent-corroboration count (gh#9): a mirror
chain repeats one original claim, and byte-identical files prove common
origin.  Dependence is expressed by descent and equivalence relationships
carrying epistemic status -- never by lineage stamps on evidence or
observation rows -- so lineage groups are derived at read time, under a
stated dependence policy, from the retained graph alone.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.records import EPISTEMIC_STATUSES, RELATIONSHIP_KINDS
from media_catalog.relationships.queries import _resolve

# Kinds whose subject's content (and transitively its claims about that
# content) likely descend from the target's: reposts, derivatives, and
# transforms, each directional with the derivative on the subject side.
DESCENT_KINDS = frozenset(
    {
        "reposted_from",
        "derived_from",
        "variant_of",
        "reencoded_from",
        "resized_from",
        "cropped_from",
        "censored_variant_of",
        "edited_from",
        "transcoded_from",
        "extracted_from",
        "thumbnail_of",
    }
)

# Symmetric kinds proving common origin without claiming who copied whom.
EQUIVALENCE_KINDS = frozenset({"same_bytes", "same_work"})

# Kinds that anchor objects together without expressing claim descent; they
# never merge lineages under the default policy.
STRUCTURAL_KINDS = frozenset({"page_of", "parent_of"})

DEPENDENCE_KINDS = DESCENT_KINDS | EQUIVALENCE_KINDS

# Conclusion-grade statuses: an ``inferred`` edge is a pending proposal, not
# a dependence a corroboration count may rely on.
CONCLUSION_STATUSES = frozenset({"observed", "verified", "derived", "reviewed"})

_Node = tuple[str, int]


class _Components:
    """Union-find over (kind, id) object nodes."""

    def __init__(self) -> None:
        self._parent: dict[_Node, _Node] = {}

    def add(self, node: _Node) -> None:
        self._parent.setdefault(node, node)

    def find(self, node: _Node) -> _Node:
        parent = self._parent[node]
        if parent != node:
            self._parent[node] = self.find(parent)
        return self._parent[node]

    def union(self, first: _Node, second: _Node) -> None:
        self.add(first)
        self.add(second)
        first_root, second_root = self.find(first), self.find(second)
        if first_root != second_root:
            # Deterministic representative: the smaller node wins.
            self._parent[max(first_root, second_root)] = min(first_root, second_root)

    def nodes(self) -> list[_Node]:
        return sorted(self._parent)


def lineage_components(
    database: CatalogDatabase | sqlite3.Connection,
    *,
    relation_kinds: frozenset[str] | set[str] = DEPENDENCE_KINDS,
    epistemic_statuses: frozenset[str] | set[str] = CONCLUSION_STATUSES,
    include_rejected: bool = False,
) -> list[dict[str, Any]]:
    """Connected components over the stated dependence edge set.

    Structural anchoring always applies: a post, its media occurrences, and
    its work anchor are one node for lineage purposes.  Every component is
    returned -- singletons included -- because an unconnected object is its
    own independent lineage.  Read-only and deterministic: components and
    their members are ordered by label, edges by kind then endpoints.
    """

    connection = database.connection if isinstance(database, CatalogDatabase) else database
    # Materialize once: the sets are validated and then consumed twice (marks
    # and parameters), so a one-shot iterable must not drain on the first pass.
    kinds = frozenset(relation_kinds)
    statuses = frozenset(epistemic_statuses)
    unknown_kinds = sorted(kinds - set(RELATIONSHIP_KINDS))
    if unknown_kinds:
        raise ValueError(f"unknown relationship kinds in dependence policy: {unknown_kinds}")
    unknown_statuses = sorted(statuses - set(EPISTEMIC_STATUSES))
    if unknown_statuses:
        raise ValueError(f"unknown epistemic statuses in dependence policy: {unknown_statuses}")

    components = _Components()
    # The object universe: every post, occurrence, and work is a node even
    # when no dependence edge touches it -- an unconnected object is its own
    # lineage, so it must appear in the partition.
    for (post_id,) in connection.execute("SELECT post_id FROM posts"):
        components.add(("post", int(post_id)))
    for occurrence_id, post_id in connection.execute(
        "SELECT media_occurrence_id, post_id FROM media_occurrences"
    ):
        components.union(("media_occurrence", int(occurrence_id)), ("post", int(post_id)))
    for work_id, origin_post_id in connection.execute("SELECT work_id, origin_post_id FROM works"):
        components.union(("work", int(work_id)), ("post", int(origin_post_id)))
    for work_id, occurrence_id in connection.execute(
        "SELECT work_id, media_occurrence_id FROM work_representations"
    ):
        components.union(("work", int(work_id)), ("media_occurrence", int(occurrence_id)))

    edges: list[tuple[_Node, str, _Node]] = []
    kind_marks = ", ".join("?" for _ in kinds)
    status_marks = ", ".join("?" for _ in statuses)
    rejected_clause = "" if include_rejected else "AND review_state != 'rejected'"
    rows = connection.execute(
        f"""SELECT relation_kind, subject_kind, subject_id, target_kind, target_id
              FROM relationships
             WHERE relation_kind IN ({kind_marks})
               AND epistemic_status IN ({status_marks}) {rejected_clause}
             ORDER BY relationship_id""",
        (*kinds, *statuses),
    ).fetchall()
    for row in rows:
        subject = (str(row["subject_kind"]), int(row["subject_id"]))
        target = (str(row["target_kind"]), int(row["target_id"]))
        components.add(subject)
        components.add(target)
        components.union(subject, target)
        edges.append((subject, str(row["relation_kind"]), target))

    members: dict[_Node, list[str]] = {}
    roots: dict[_Node, _Node] = {}
    for node in components.nodes():
        root = components.find(node)
        roots[node] = root
        label = _resolve(connection, node[0], node[1])
        members.setdefault(root, []).append(label)
    grouped_edges: dict[_Node, list[dict[str, str]]] = {}
    for subject, kind, target in edges:
        grouped_edges.setdefault(roots[subject], []).append(
            {
                "kind": kind,
                "subject": _resolve(connection, subject[0], subject[1]),
                "target": _resolve(connection, target[0], target[1]),
            }
        )
    return [
        {
            "members": sorted(labels),
            "dependence_edges": sorted(
                grouped_edges.get(root, []),
                key=lambda edge: (edge["kind"], edge["subject"], edge["target"]),
            ),
        }
        for root, labels in sorted(members.items(), key=lambda item: sorted(item[1])[0])
    ]
