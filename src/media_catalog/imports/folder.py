"""Bulk local-folder ingest (grabber-style media directories).

Scans one directory non-recursively, verifies each file's intrinsic identity
(md5/sha256 computed from bytes — filenames are never trusted), and records
idempotent bare-file seeds under one batch session.  No posts, no platform
identities, no catalog facts: the seeds are discovery subjects like any other
bare file, so existing offline index lookups, cross-check, and labeling treat
them uniformly.  Grabber ``<image>.txt`` sidecars are parsed and retained as
operator-supplied declared evidence on their file seed (bead
``data-processing-h6d``); sidecars without a media twin are counted only.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.imports.sidecar import SidecarStore
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
    observed_at = _now()
    input_digest = f"folder:{directory.resolve()}:{len(media)}"
    session_cursor = connection.execute(
        """INSERT INTO discovery_sessions
               (input_kind, input_digest, live_authorized, status,
                started_at, finished_at)
           VALUES ('bulk_files', ?, 0, 'complete', ?, ?)""",
        (input_digest, observed_at, observed_at),
    )
    connection.commit()
    assert session_cursor.lastrowid is not None
    session_id = int(session_cursor.lastrowid)

    service = SeedMaterializationService(database)
    media_names = {path.name for path in media}
    sidecar_for_media = {
        path: directory / f"{path.name}.txt"
        for path in media
        if f"{path.name}.txt" in {sidecar.name for sidecar in sidecars}
    }
    orphan_sidecars = sum(
        1 for sidecar in sidecars if sidecar.name[: -len(".txt")] not in media_names
    )
    sidecar_store: SidecarStore | None = None
    if sidecar_for_media:
        sidecar_store = SidecarStore(
            database, digest=f"{input_digest}:sidecars", observed_at=observed_at
        )
    materialized = 0
    existing = 0
    sidecar_parsed = 0
    sidecar_pool_tags = 0
    failed: list[dict[str, str]] = []
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
        twin = sidecar_for_media.get(path)
        if twin is not None and sidecar_store is not None:
            summary = sidecar_store.attach(
                int(result["file_seed_id"]), twin, observed_at=observed_at
            )
            if summary is not None:
                sidecar_parsed += 1
                sidecar_pool_tags += len(summary["pool_ids"])
    if sidecar_store is not None:
        sidecar_store.finish(observed_at)
    connection.commit()

    return {
        "session_id": session_id,
        "directory": directory.name,
        "scanned_files": len(entries),
        "media_files": len(media),
        "materialized": materialized,
        "existing": existing,
        "sidecar_files": len(sidecars),
        "sidecar_parsed": sidecar_parsed,
        "sidecar_orphan": orphan_sidecars,
        "sidecar_pool_tags": sidecar_pool_tags,
        "other_files": others,
        "failed": failed[:50],
        "failed_count": len(failed),
    }
