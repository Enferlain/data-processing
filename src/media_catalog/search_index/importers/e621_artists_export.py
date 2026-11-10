"""e621 daily artists DB export → lookup-v1 artist projection (offline import).

The export is a gzipped CSV (real columns, verified 2026-11-09): ``id, name,
other_names`` (postgres array), ``group_name, linked_user_id, is_active (t/f),
is_locked, creator_id, created_at, updated_at, active_urls, inactive_urls``.
The URL columns are plain whitespace-separated strings — not arrays.  The
projection serves exactly the ``artist_identifier`` method: canonicalized
artist URLs → artist entry (name, other names, active flag).
"""

from __future__ import annotations

import csv
import gzip
import sys
from dataclasses import dataclass
from pathlib import Path

from media_catalog.search_index.importers.e621_export import (
    PROGRESS_INTERVAL_ROWS,
    ImportResult,
    _element_urls,
    _parse_array,
    canonical_export_url,
    sha256_file,
)
from media_catalog.search_index.projection import ProjectionBuilder

BUILDER_VERSION = "e621-artists-export-v1"

CAPABILITY = "artist_identifier"

_REQUIRED_COLUMNS = ("id", "name")

# Optional columns degrade to NULLs when the layout changes; the import says
# so instead of silently dropping that data.
_OPTIONAL_COLUMNS = (
    "other_names",
    "group_name",
    "is_active",
    "updated_at",
    "active_urls",
    "inactive_urls",
)


@dataclass(frozen=True, slots=True)
class ArtistImportResult(ImportResult):
    url_count: int = 0


def _canonical(value: str) -> str:
    return canonical_export_url(value)


def import_e621_artists_export(
    artifact: Path,
    *,
    destination: Path,
    checksum: str | None = None,
    max_records: int | None = None,
) -> ArtistImportResult:
    """Build an artist-entry projection from an e621 artists DB export."""
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

    truncated = False
    builder: ProjectionBuilder | None = None
    url_count = 0
    try:
        with gzip.open(artifact, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            header = set(reader.fieldnames or ())
            missing = [name for name in _REQUIRED_COLUMNS if name not in header]
            if missing:
                raise ValueError(
                    "export is missing required column(s): "
                    + ", ".join(missing)
                    + f"; available: {', '.join(sorted(header))}"
                )
            columns_absent = tuple(name for name in _OPTIONAL_COLUMNS if name not in header)
            builder = ProjectionBuilder(
                provider="e621",
                destination=destination,
                artifact_path=artifact,
                artifact_digest=digest,
                snapshot_revision=f"{digest[:12]}-{BUILDER_VERSION}-pending",
                builder_version=BUILDER_VERSION,
                capabilities=(CAPABILITY,),
                count_table="artist_entries",
                artist_schema=True,
            )
            for index, row in enumerate(reader):
                if max_records is not None and index >= max_records:
                    truncated = True
                    break
                if index and index % PROGRESS_INTERVAL_ROWS == 0:
                    print(f"e621 artists export: imported {index:,} rows…", file=sys.stderr)
                other_names = _parse_array(row.get("other_names"))
                urls: list[tuple[str, int]] = []
                for column, active in (("active_urls", 1), ("inactive_urls", 0)):
                    raw = row.get(column) or ""
                    for element in raw.split():
                        for url in _element_urls(element):
                            urls.append((_canonical(url), active))
                url_count += len(urls)
                builder.add_artist(
                    artist_id=int(row["id"]),
                    name=row["name"],
                    group_name=row.get("group_name") or None,
                    is_active=1 if (row.get("is_active") or "t") == "t" else 0,
                    updated_at=row.get("updated_at") or None,
                    other_names=other_names,
                    urls=urls,
                )
        assert builder is not None
        scope_value = f"head{max_records}" if truncated else "full"
        result = ArtistImportResult(
            projection_path=builder.commit(scope=scope_value),
            snapshot_revision=builder.snapshot_revision,
            record_count=builder.record_count or 0,
            artifact_digest=digest,
            artifact_path=str(artifact),
            scope=scope_value,
            columns_absent=columns_absent,
            url_count=url_count,
        )
    except BaseException:
        if builder is not None:
            builder.discard()
        raise
    return result
