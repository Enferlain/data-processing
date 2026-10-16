"""Work materialization: deterministic anchors, one per post with occurrences."""

from __future__ import annotations

from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.records import WorkRecord
from media_catalog.writer import CatalogWriter


def materialize_works(database: CatalogDatabase, *, clock: Any) -> dict[str, Any]:
    """Create the missing work anchors and link each post's occurrences.

    Idempotent: existing anchors and representation links are left alone.
    The work kind is a deterministic hint recorded at materialization time;
    projections recompute page counts from live representation links.
    """

    now = str(clock())
    created = existing = 0
    linked = 0
    with database.transaction():
        writer = CatalogWriter(database)
        posts = database.connection.execute(
            """SELECT p.post_id, COUNT(mo.media_occurrence_id) AS occurrence_count
                 FROM posts p
                 JOIN media_occurrences mo ON mo.post_id = p.post_id
             GROUP BY p.post_id
             ORDER BY p.post_id"""
        ).fetchall()
        for row in posts:
            work = writer.materialize_work(
                WorkRecord(
                    origin_post_id=int(row["post_id"]),
                    work_kind="multi_page" if int(row["occurrence_count"]) > 1 else "single",
                    created_at=now,
                )
            )
            if work.outcome == "inserted":
                created += 1
            else:
                existing += 1
            for occurrence in database.connection.execute(
                "SELECT media_occurrence_id FROM media_occurrences WHERE post_id = ? "
                "ORDER BY media_occurrence_id",
                (int(row["post_id"]),),
            ):
                link = writer.link_work_representation(
                    work.id, int(occurrence["media_occurrence_id"]), now
                )
                linked += 1 if link.outcome == "inserted" else 0
    return {
        "works_created": created,
        "works_existing": existing,
        "representations_linked": linked,
    }
