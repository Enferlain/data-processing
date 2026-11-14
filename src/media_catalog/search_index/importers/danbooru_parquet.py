"""Danbooru community snapshot (parquet) → lookup-v1 posts projection.

Bootstrap source per ``docs/plans/booru_investigation.md``:
``nyanko-devs/danbooru2026`` ``metadata/posts-snapshot.parquet`` — 4.1 GB,
11.7M rows, verified schema (id, md5, source, parent_id, file_ext,
image_width/height, created_at/updated_at timestamps, is_deleted, is_banned,
tag_string_artist, pixiv_id).  The snapshot is bootstrap material, not current
truth: freshness rides the revision, live lookups fall through, and
teach-on-result maintains encountered knowledge.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from media_catalog.search_index.importers.e621_export import (
    PROGRESS_INTERVAL_ROWS,
    ImportResult,
    _canonical,
    _element_urls,
    sha256_file,
)
from media_catalog.search_index.projection import ProjectionBuilder

BUILDER_VERSION = "danbooru2026-parquet-v1"

_CAPABILITIES = (
    "verified_md5",
    "declared_md5",
    "source_post_url",
    "external_post_id",
    "artist_exact_name",
    "artist_alias",
    "artist_text",
)

_REQUIRED_COLUMNS = ("id", "md5")


@dataclass(frozen=True, slots=True)
class DanbooruImportResult(ImportResult):
    pass


def _py(value: object) -> Any:
    """pyarrow scalar → python native."""
    method = getattr(value, "as_py", None)
    return method() if callable(method) else value


def _iso(value: object) -> str | None:
    if value is None:
        return None
    method = getattr(value, "isoformat", None)
    return method() if callable(method) else str(value)


def import_danbooru_parquet(
    artifact: Path,
    *,
    destination: Path,
    checksum: str | None = None,
    max_records: int | None = None,
) -> DanbooruImportResult:
    """Build a lookup-v1 posts projection from the danbooru snapshot."""
    import pyarrow.parquet as pq

    artifact = Path(artifact)
    if not artifact.is_file():
        raise ValueError(f"artifact does not exist: {artifact.name}")
    digest = sha256_file(artifact)
    if checksum is not None and digest != checksum.strip().lower():
        raise ValueError(
            f"artifact checksum mismatch: expected {checksum.strip().lower()[:16]}…,"
            f" computed {digest[:16]}…"
        )
    if max_records is not None and max_records < 1:
        raise ValueError("max_records must be positive")
    destination.parent.mkdir(parents=True, exist_ok=True)

    parquet = pq.ParquetFile(artifact)
    names = set(parquet.schema_arrow.names)
    missing = [name for name in _REQUIRED_COLUMNS if name not in names]
    if missing:
        raise ValueError(
            "snapshot is missing required column(s): "
            + ", ".join(missing)
            + f"; available: {', '.join(sorted(names))}"
        )
    optional = (
        "source",
        "parent_id",
        "file_ext",
        "image_width",
        "image_height",
        "created_at",
        "updated_at",
        "is_deleted",
        "is_banned",
        "tag_string_artist",
    )
    columns_absent = tuple(name for name in optional if name not in names)

    truncated = False
    builder: ProjectionBuilder | None = None
    index = 0
    try:
        builder = ProjectionBuilder(
            provider="danbooru",
            destination=destination,
            artifact_path=artifact,
            artifact_digest=digest,
            snapshot_revision=f"{digest[:12]}-{BUILDER_VERSION}-pending",
            builder_version=BUILDER_VERSION,
            capabilities=_CAPABILITIES,
        )
        for batch in parquet.iter_batches(batch_size=50_000, columns=None):
            if max_records is not None and index >= max_records:
                truncated = True
                break
            columns = {name: batch.column(i) for i, name in enumerate(batch.schema.names)}
            length = batch.num_rows
            for row in range(length):
                if max_records is not None and index >= max_records:
                    truncated = True
                    break
                if index and index % PROGRESS_INTERVAL_ROWS == 0:
                    print(f"danbooru snapshot: imported {index:,} rows…", file=sys.stderr)
                raw: dict[str, Any] = {name: _py(column[row]) for name, column in columns.items()}
                sources: list[str] = []
                if raw.get("source"):
                    for element in str(raw["source"]).split():
                        sources.extend(_canonical(url) for url in _element_urls(element))
                artists = (
                    [tag for tag in str(raw["tag_string_artist"]).split() if tag]
                    if raw.get("tag_string_artist")
                    else []
                )
                builder.add_post(
                    post_id=int(raw["id"]),
                    md5=str(raw["md5"]) if raw.get("md5") else None,
                    source=str(raw["source"]).strip() or None if raw.get("source") else None,
                    parent_id=int(raw["parent_id"]) if raw.get("parent_id") else None,
                    file_ext=str(raw["file_ext"]) if raw.get("file_ext") else None,
                    width=int(raw["image_width"]) if raw.get("image_width") else None,
                    height=int(raw["image_height"]) if raw.get("image_height") else None,
                    created_at=_iso(raw.get("created_at")),
                    updated_at=_iso(raw.get("updated_at")),
                    is_deleted=int(bool(raw.get("is_deleted")) or bool(raw.get("is_banned"))),
                    origin="export",
                    seen_at=str(_iso(raw.get("updated_at")) or ""),
                    sources=sources,
                    artists=artists,
                )
                index += 1
            if truncated:
                break
        assert builder is not None
        scope_value = f"head{max_records}" if truncated else "full"
        result = DanbooruImportResult(
            projection_path=builder.commit(scope=scope_value),
            snapshot_revision=builder.snapshot_revision,
            record_count=builder.record_count or 0,
            artifact_digest=digest,
            artifact_path=str(artifact),
            scope=scope_value,
            columns_absent=columns_absent,
        )
    except BaseException:
        if builder is not None:
            builder.discard()
        raise
    return result
