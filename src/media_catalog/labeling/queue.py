"""Pair-queue building for the labeling tool (bead data-processing-w7j).

Queues candidate image pairs from NON-perceptual signals so the operator can
label how two images relate without the tool needing the similarity judge it
is helping to calibrate: provenance (identical hashes, shared source URLs),
provider-labeled structure (e621 parent_of), metadata overlap (shared artist
with tag-Jaccard, shared external ids), and within-artist contrast pairs.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PairCandidate:
    post_a_id: int
    post_b_id: int
    queue_signal: str
    detail: str
    prior_note: str | None = None


class CandidateQueue(list[PairCandidate]):
    """Queue list carrying candidate pairs and skipped unavailable count."""

    skipped_count: int = 0

    def __init__(
        self,
        iterable: Iterable[PairCandidate] = (),
        *,
        skipped_count: int = 0,
    ) -> None:
        super().__init__(iterable)
        self.skipped_count = skipped_count


def _pairs(connection: sqlite3.Connection, sql: str) -> list[tuple[int, int]]:
    return [
        (int(row[0]), int(row[1])) for row in connection.execute(sql) if int(row[0]) < int(row[1])
    ]


def _has_usable_media(
    connection: sqlite3.Connection,
    post_id: int,
    media_root: Path | None,
    matched_root_ids: set[int] | None,
) -> bool:
    """Return True if the post has available remote media or verified local storage."""
    rows = connection.execute(
        """SELECT m.media_occurrence_id, m.remote_url, m.preview_url,
                  al.managed_root_id, al.relative_path
             FROM media_occurrences m
             LEFT JOIN occurrence_assets oa ON oa.media_occurrence_id = m.media_occurrence_id
             LEFT JOIN assets a ON a.asset_id = oa.asset_id
             LEFT JOIN asset_locations al
               ON al.asset_id = a.asset_id AND al.location_kind <> 'legacy'
            WHERE m.post_id = ?
              AND m.availability = 'available'""",
        (post_id,),
    ).fetchall()
    if not rows:
        return False
    for row in rows:
        if row["remote_url"] or row["preview_url"]:
            return True
        rel_path = row["relative_path"]
        m_root_id = row["managed_root_id"]
        if rel_path:
            if media_root is None:
                return True
            if matched_root_ids is not None and m_root_id not in matched_root_ids:
                continue
            with contextlib.suppress(OSError):
                target = (media_root / rel_path).resolve()
                if target.is_relative_to(media_root.resolve()) and target.is_file():
                    return True
    return False


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


AUTO_IDENTICAL_NOTE = (
    "auto: identical md5 — byte-identical assets (59/59 operator calibration, zero exceptions)"
)


def autoconfirm_identical_md5_pairs(connection: sqlite3.Connection) -> int:
    """Label identical-md5 cross-platform pairs `same` without review.

    Operators confirmed 59/59 such pairs as ``same`` with zero exceptions:
    an identical content md5 means byte-identical assets, so review would
    only re-spend operator attention.  The pairs never reach the queue; the
    automatic label stays visible and auditable via its note.  Idempotent:
    already-labeled pairs are left untouched.
    """
    rows = connection.execute(
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
              AND x1.platform_key != x2.platform_key
              AND p1.availability = 'available'
              AND p2.availability = 'available'
              AND NOT EXISTS (
                    SELECT 1 FROM pair_labels pl
                     WHERE pl.post_a_id = m1.post_id AND pl.post_b_id = m2.post_id)"""
    ).fetchall()
    now = _now()
    written = 0
    for a, b in rows:
        cursor = connection.execute(
            """INSERT OR IGNORE INTO pair_labels
                   (post_a_id, post_b_id, queue_signal, verdict, relation_note, labeled_at)
               VALUES (?, ?, 'identical_md5', 'same', ?, ?)""",
            (int(a), int(b), AUTO_IDENTICAL_NOTE, now),
        )
        written += cursor.rowcount
    connection.commit()
    return written


def build_queue(
    connection: sqlite3.Connection,
    *,
    limit: int = 50,
    revisit_unsure: bool = False,
    media_root: Path | None = None,
    matched_root_ids: set[int] | None = None,
) -> CandidateQueue:
    """Every signal family contributes; already-labeled pairs are excluded in normal mode."""
    media_ready: dict[int, bool] = {}

    def post_ready(post_id: int) -> bool:
        if post_id not in media_ready:
            media_ready[post_id] = _has_usable_media(
                connection, post_id, media_root, matched_root_ids
            )
        return media_ready[post_id]

    if revisit_unsure:
        rows = connection.execute(
            """SELECT pl.post_a_id, pl.post_b_id, pl.queue_signal, pl.relation_note,
                      p1.availability AS availability_a, p2.availability AS availability_b
                 FROM pair_labels pl
                 JOIN posts p1 ON p1.post_id = pl.post_a_id
                 JOIN posts p2 ON p2.post_id = pl.post_b_id
                WHERE pl.verdict = 'unsure'
                ORDER BY pl.pair_label_id""",
        ).fetchall()
        candidates: list[PairCandidate] = []
        skipped_count = 0
        for row in rows:
            a, b = int(row[0]), int(row[1])
            if (
                row["availability_a"] != "available"
                or row["availability_b"] != "available"
                or not post_ready(a)
                or not post_ready(b)
            ):
                skipped_count += 1
                continue
            sig = str(row[2])
            note = str(row[3]) if row[3] is not None else None
            detail = (
                f"revisit unsure ({sig}): prior note '{note}'"
                if note
                else f"revisit unsure ({sig})"
            )
            candidates.append(PairCandidate(a, b, sig, detail, prior_note=note))
        return CandidateQueue(candidates[:limit], skipped_count=skipped_count)

    labeled = {
        (int(row[0]), int(row[1]))
        for row in connection.execute("SELECT post_a_id, post_b_id FROM pair_labels")
    }
    candidates_list: list[PairCandidate] = []
    seen: set[tuple[int, int]] = set()
    skipped_unusable_count = 0

    def add(pairs: list[tuple[int, int]], signal: str, detail: str) -> None:
        nonlocal skipped_unusable_count
        for a, b in pairs:
            if (a, b) not in labeled and (a, b) not in seen:
                seen.add((a, b))
                if not (post_ready(a) and post_ready(b)):
                    skipped_unusable_count += 1
                    continue
                candidates_list.append(PairCandidate(a, b, signal, detail))
                candidates_list.append(PairCandidate(a, b, signal, detail))

    # A1: identical declared md5 across platforms — auto-confirmed before
    # the queue is built (autoconfirm_identical_md5_pairs), so this family
    # only enqueues pairs whose labeling predates the auto rule.
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
                  AND x1.platform_key != x2.platform_key
                  AND p1.availability = 'available'
                  AND p2.availability = 'available'""",
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
                 JOIN posts p1 ON p1.post_id = r1.post_id
                 JOIN posts p2 ON p2.post_id = r2.post_id
                WHERE r1.reference_kind = 'source_url'
                  AND p1.availability = 'available'
                  AND p2.availability = 'available'""",
        ),
        "shared_source_url",
        "posts cite the same source URL",
    )
    # A3: provider-labeled parent/child variants (post_relations, recorded
    # by the e621 adapter from parent_id on the wire). Provider parent relation
    # does not prove variant identity; explicit operator verdict is required.
    add(
        [
            (a, b) if a < b else (b, a)
            for a, b in (
                (int(row[0]), int(row[1]))
                for row in connection.execute(
                    """SELECT DISTINCT pr.source_post_id, pr.target_post_id
                         FROM post_relations pr
                         JOIN posts p1 ON p1.post_id = pr.source_post_id
                         JOIN posts p2 ON p2.post_id = pr.target_post_id
                        WHERE pr.relation_type = 'parent_of'
                          AND p1.availability = 'available'
                          AND p2.availability = 'available'"""
                )
            )
            if a != b
        ],
        "provider_parent",
        (
            "provider records parent/child relation "
            "(operator verdict required; parent does not prove variant)"
        ),
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
                 JOIN posts p1 ON p1.post_id = r1.post_id
                 JOIN posts p2 ON p2.post_id = r2.post_id
                WHERE r1.reference_kind != 'source_url'
                  AND p1.availability = 'available'
                  AND p2.availability = 'available'""",
        ),
        "shared_external_id",
        "posts share a stable external reference",
    )
    # B2/C: within-artist pairs, closest-tag-overlap first (B) plus random
    # different works (C) for calibration negatives. Same-artist contrast pairs
    # expect different works by the same artist for calibration negatives.
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
              AND p1.availability = 'available'
              AND p2.availability = 'available'
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
        if not (post_ready(a) and post_ready(b)):
            skipped_unusable_count += 1
            continue
        signal = "same_artist_tags" if int(row[3]) >= 15 else "same_artist_contrast"
        contrast_detail = (
            f"same artist ({row[0]}), {row[3]} shared tags "
            "(contrast candidate: different works expected for calibration negatives)"
        )
        detail = (
            f"same artist ({row[0]}), {row[3]} shared tags (high tag overlap)"
            if signal == "same_artist_tags"
            else contrast_detail
        )
        candidates_list.append(PairCandidate(a, b, signal, detail))

    # Stable order, capped.
    candidates_list.sort(key=lambda c: (c.queue_signal, c.post_a_id, c.post_b_id))
    return CandidateQueue(candidates_list[:limit], skipped_count=skipped_unusable_count)
