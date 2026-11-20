"""Sankaku artist sweep (bead ``data-processing-hvs``, phase 2, change
``add-sankaku-artist-sweep``): bounded bulk listing of the catalog's top
artist names through the existing sankaku keyset listing, with prior-run
skipping, budgets, platform-floor pacing, and a post-sweep md5 overlap
report — the compare half of the sankaku plan before any similarity channel
lands.

The sweep records post metadata only (the standard adapter flow); media
pulls, similarity, and new-content acquisition are later phases.  Research
provenance (bead data-processing-84v): keyset tag search is the listing
path gallery-dl uses; 429/quota handling and signed-URL expiry live in the
adapter and service layers already.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from media_catalog.adapters import AdapterOperation
from media_catalog.database import CatalogDatabase
from media_catalog.remote_sync.service import MetadataSyncService, SyncLimits

DEFAULT_PAGES_PER_ARTIST = 2


def swept_artist_names(
    connection: sqlite3.Connection, *, limit: int, platform_keys: tuple[str, ...]
) -> list[tuple[str, int]]:
    """Artist tag names across the source platforms, ranked by held posts.

    Names are deduplicated across platforms: the sweep searches sankaku by
    tag, and artist tag vocabularies are shared across booru conventions.
    """
    placeholders = ",".join("?" for _ in platform_keys)
    rows = connection.execute(
        f"""SELECT t.name, count(DISTINCT p.post_id) AS held
              FROM tags t
              JOIN post_tags pt ON pt.tag_id = t.tag_id
              JOIN posts p ON p.post_id = pt.post_id
              JOIN platforms pl ON pl.platform_id = p.platform_id
             WHERE pl.platform_key IN ({placeholders})
               AND t.category = 'artist'
             GROUP BY t.name
            HAVING held >= 3
             ORDER BY held DESC, t.name
             LIMIT ?""",
        (*platform_keys, limit),
    )
    return [(str(row[0]), int(row[1])) for row in rows]


def _already_swept(connection: sqlite3.Connection, platform_key: str, target: str) -> bool:
    row = connection.execute(
        """SELECT 1 FROM remote_runs rr
             JOIN platforms pl ON pl.platform_id = rr.platform_id
            WHERE pl.platform_key = ?
              AND rr.operation = 'list_account_posts'
              AND rr.target = ?
              AND rr.status = 'complete'
            LIMIT 1""",
        (platform_key, target),
    ).fetchone()
    return row is not None


def md5_overlap_report(connection: sqlite3.Connection) -> dict[str, int]:
    """Sankaku posts whose declared md5 is already known on another platform
    versus md5s new to the catalog — the phase-3 md5 join, read-only."""
    known = int(
        connection.execute(
            """SELECT count(DISTINCT s.post_id)
                 FROM media_occurrences s
                 JOIN posts sp ON sp.post_id = s.post_id
                 JOIN platforms spl ON spl.platform_id = sp.platform_id
                WHERE spl.platform_key = 'sankaku'
                  AND s.declared_md5 IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM media_occurrences o
                        JOIN posts op ON op.post_id = o.post_id
                        JOIN platforms opl ON opl.platform_id = op.platform_id
                       WHERE o.declared_md5 = s.declared_md5
                         AND opl.platform_key != 'sankaku')"""
        ).fetchone()[0]
    )
    total = int(
        connection.execute(
            """SELECT count(DISTINCT s.post_id)
                 FROM media_occurrences s
                 JOIN posts sp ON sp.post_id = s.post_id
                 JOIN platforms spl ON spl.platform_id = sp.platform_id
                WHERE spl.platform_key = 'sankaku'
                  AND s.declared_md5 IS NOT NULL"""
        ).fetchone()[0]
    )
    return {
        "sankaku_posts_with_md5": total,
        "md5_known_elsewhere": known,
        "md5_new_to_catalog": total - known,
    }


def sweep_artists(
    database: CatalogDatabase,
    adapter_factory: Any,
    platform_key: str,
    *,
    names_limit: int = 50,
    request_budget: int = 50,
    pages_per_artist: int = DEFAULT_PAGES_PER_ARTIST,
    source_platforms: tuple[str, ...] = ("danbooru", "e621", "sankaku"),
    client_factory: Any = None,
    minimum_interval_seconds: float = 0.0,
) -> dict[str, Any]:
    """List sankaku posts for the catalog's top artist names under a budget.

    One listing run per not-yet-swept name (the standard sync contract);
    prior complete listing runs for the same target are skipped.  A name is
    only started when the budget can fund all its pages (strict capping —
    sankaku is quota-hostile).  Pacing comes from the sync service's
    interval; the loop adds the platform floor between names.
    """
    import httpx

    connection = database.connection
    names = swept_artist_names(connection, limit=names_limit, platform_keys=source_platforms)
    client_factory = client_factory or httpx.Client
    results: list[dict[str, Any]] = []
    requests_used = 0
    skipped = 0
    with client_factory() as client:
        adapter = adapter_factory(client)
        service = MetadataSyncService(
            database, adapter, minimum_interval_seconds=minimum_interval_seconds
        )
        for name, held in names:
            if _already_swept(connection, platform_key, name):
                skipped += 1
                continue
            if requests_used + pages_per_artist > request_budget:
                break
            if requests_used and minimum_interval_seconds > 0:
                time.sleep(minimum_interval_seconds)
            limits = SyncLimits(
                requests=pages_per_artist,
                pages=pages_per_artist,
                records=pages_per_artist * adapter.instance.page_size,
                elapsed_seconds=300,
            )
            try:
                result = service.synchronize(
                    AdapterOperation.LIST_ACCOUNT_POSTS, name, limits=limits
                )
            except Exception as error:  # recorded per-name, sweep continues
                results.append(
                    {
                        "artist": name,
                        "held_posts": held,
                        "outcome": "failed",
                        "error": f"{type(error).__name__}: {error}"[:200],
                    }
                )
                requests_used += pages_per_artist
                continue
            payload: dict[str, Any] = dict(result.as_dict())
            results.append(
                {
                    "artist": name,
                    "held_posts": held,
                    "outcome": str(payload.get("status", "complete")),
                    "requests": int(payload.get("request_count", pages_per_artist)),
                    "records": int(payload.get("record_count", 0)),
                }
            )
            requests_used += int(payload.get("request_count", pages_per_artist))
    report = md5_overlap_report(connection)
    return {
        "platform": platform_key,
        "names_considered": len(names),
        "names_skipped_already_swept": skipped,
        "names_swept": len(results),
        "requests_used": requests_used,
        "results": results,
        "md5_overlap": report,
    }
