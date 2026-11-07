"""Pair-queue building for the labeling tool (bead data-processing-w7j).

Queues candidate image pairs from NON-perceptual signals so the operator can
label how two images relate without the tool needing the similarity judge it
is helping to calibrate: provenance (identical hashes, shared source URLs),
provider-labeled structure (e621 parent_of), metadata overlap (shared artist
with tag-Jaccard, shared external ids), and within-artist contrast pairs.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PairCandidate:
    post_a_id: int
    post_b_id: int
    queue_signal: str
    detail: str


def _pairs(connection: sqlite3.Connection, sql: str) -> list[tuple[int, int]]:
    return [
        (int(row[0]), int(row[1])) for row in connection.execute(sql) if int(row[0]) < int(row[1])
    ]


def build_queue(connection: sqlite3.Connection, *, limit: int = 50) -> list[PairCandidate]:
    """Every signal family contributes; already-labeled pairs are excluded."""
    labeled = {
        (int(row[0]), int(row[1]))
        for row in connection.execute("SELECT post_a_id, post_b_id FROM pair_labels")
    }
    candidates: list[PairCandidate] = []
    seen: set[tuple[int, int]] = set()

    def add(pairs: list[tuple[int, int]], signal: str, detail: str) -> None:
        for a, b in pairs:
            if (a, b) not in labeled and (a, b) not in seen:
                seen.add((a, b))
                candidates.append(PairCandidate(a, b, signal, detail))

    # A1: identical declared md5 across platforms.
    add(
        _pairs(
            connection,
            """SELECT DISTINCT m1.post_id, m2.post_id
                 FROM media_occurrences m1
                 JOIN media_occurrences m2
                   ON m1.declared_md5 = m2.declared_md5
                  AND m1.media_occurrence_id < m2.media_occurrence_id
                 JOIN posts p1 ON p1.post_id = m1.post_id
                 JOIN posts p2 ON p2.post_id = m2.post_id
                 JOIN platforms x1 ON x1.platform_id = p1.platform_id
                 JOIN platforms x2 ON x2.platform_id = p2.platform_id
                WHERE m1.declared_md5 IS NOT NULL
                  AND x1.platform_key != x2.platform_key""",
        ),
        "identical_md5",
        "identical declared md5 across platforms",
    )
    # A2: shared source URL.
    add(
        _pairs(
            connection,
            """SELECT DISTINCT r1.post_id, r2.post_id
                 FROM post_external_references r1
                 JOIN post_external_references r2
                   ON r1.external_link_id = r2.external_link_id
                  AND r1.post_id < r2.post_id
                WHERE r1.reference_kind = 'source_url'""",
        ),
        "shared_source_url",
        "posts cite the same source URL",
    )
    # A3: provider-labeled parent/child variants (post_relations, recorded
    # by the e621 adapter from parent_id on the wire).
    add(
        [
            (a, b) if a < b else (b, a)
            for a, b in (
                (int(row[0]), int(row[1]))
                for row in connection.execute(
                    """SELECT DISTINCT source_post_id, target_post_id
                         FROM post_relations WHERE relation_type = 'parent_of'"""
                )
            )
            if a != b
        ],
        "provider_parent",
        "provider records a parent/child variant relation",
    )

    # B1: shared external id across platforms (e.g. both cite one pixiv id).
    add(
        _pairs(
            connection,
            """SELECT DISTINCT r1.post_id, r2.post_id
                 FROM post_external_references r1
                 JOIN post_external_references r2
                   ON r1.platform_reference_id = r2.platform_reference_id
                  AND r1.post_id < r2.post_id
                WHERE r1.reference_kind != 'source_url'""",
        ),
        "shared_external_id",
        "posts share a stable external reference",
    )
    # B2/C: within-artist pairs, closest-tag-overlap first (B) plus random
    # different works (C) for calibration negatives.
    artist_pairs = connection.execute(
        """SELECT t.name, p1.post_id, p2.post_id,
                  (SELECT count(*) FROM post_tags a1
                     JOIN post_tags a2 ON a2.tag_id = a1.tag_id AND a2.post_id = p2.post_id
                    WHERE a1.post_id = p1.post_id) AS shared_tags
             FROM post_tags pt1
             JOIN tags t ON t.tag_id = pt1.tag_id AND t.category = 'artist'
             JOIN posts p1 ON p1.post_id = pt1.post_id
             JOIN post_tags pt2 ON pt2.tag_id = t.tag_id AND pt2.post_id != p1.post_id
             JOIN posts p2 ON p2.post_id = pt2.post_id
            WHERE p1.post_id < p2.post_id
            GROUP BY t.name, p1.post_id, p2.post_id
            ORDER BY shared_tags DESC""",
    ).fetchall()
    for row in artist_pairs:
        a, b = int(row[1]), int(row[2])
        if a > b:
            a, b = b, a
        if (a, b) in labeled or (a, b) in seen:
            continue
        seen.add((a, b))
        signal = "same_artist_tags" if int(row[3]) >= 15 else "same_artist_contrast"
        detail = (
            f"same artist ({row[0]}), {row[3]} shared tags"
            if signal == "same_artist_tags"
            else f"same artist ({row[0]}), {row[3]} shared tags (contrast candidate)"
        )
        candidates.append(PairCandidate(a, b, signal, detail))

    # Stable order, capped.
    candidates.sort(key=lambda c: (c.queue_signal, c.post_a_id, c.post_b_id))
    return candidates[:limit]
