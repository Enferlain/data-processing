"""Bulk local-folder ingest (grabber-style media directories).

Scans one directory non-recursively, verifies each file's intrinsic identity
(md5/sha256 computed from bytes — filenames are never trusted), and records
idempotent bare-file seeds under one batch session.  No posts, no platform
identities, no catalog facts: the seeds are discovery subjects like any other
bare file, so existing offline index lookups, cross-check, and labeling treat
them uniformly.  Sidecar/tag files are counted, not parsed (sidecar ingestion
is a deliberate follow-up).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.seeding import SeedMaterializationService

MEDIA_EXTENSIONS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".webm",
        ".mp4",
        ".swf",
        ".avif",
        ".jxl",
        ".bmp",
    }
)

_MAX_FILES_PER_BATCH = 200_000


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def ingest_folder(
    database: CatalogDatabase,
    directory: Path,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    """Record every media file in ``directory`` (non-recursive) as an
    idempotent bare-file discovery seed under one batch session."""
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"not a directory: {directory.name}")
    entries = sorted(entry for entry in directory.iterdir() if entry.is_file())
    media = [entry for entry in entries if entry.suffix.lower() in MEDIA_EXTENSIONS]
    sidecars = [entry for entry in entries if entry.suffix.lower() == ".txt"]
    others = len(entries) - len(media) - len(sidecars)
    if len(media) > _MAX_FILES_PER_BATCH:
        raise ValueError(
            f"directory holds {len(media)} media files"
            f" (limit {_MAX_FILES_PER_BATCH}); split the batch"
        )

    connection = database.connection
    connection.row_factory = sqlite3.Row
    session_cursor = connection.execute(
        """INSERT INTO discovery_sessions
               (input_kind, input_digest, live_authorized, status,
                started_at, finished_at)
           VALUES ('bulk_files', ?, 0, 'complete', ?, ?)""",
        (
            f"folder:{directory.resolve()}:{len(media)}",
            _now(),
            _now(),
        ),
    )
    connection.commit()
    assert session_cursor.lastrowid is not None
    session_id = int(session_cursor.lastrowid)

    service = SeedMaterializationService(database)
    materialized = 0
    existing = 0
    failed: list[dict[str, str]] = []
    observed_at = _now()
    for path in media:
        try:
            result = service.materialize_file(
                path, session_id=session_id, note=note, observed_at=observed_at
            )
        except ValueError as error:
            failed.append({"file": path.name, "reason": str(error)[:200]})
            continue
        if result["status"] == "materialized":
            materialized += 1
        else:
            existing += 1
    connection.commit()

    return {
        "session_id": session_id,
        "directory": directory.name,
        "scanned_files": len(entries),
        "media_files": len(media),
        "materialized": materialized,
        "existing": existing,
        "sidecar_files": len(sidecars),
        "other_files": others,
        "failed": failed[:50],
        "failed_count": len(failed),
    }
