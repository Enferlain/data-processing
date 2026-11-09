"""e621 daily DB export → lookup-v1 projection (offline import).

The export is a gzipped CSV with a published SHA-256; the importer verifies
the checksum when supplied, streams the artifact with bounded memory, records
the artifact's path and digest in ``index_meta`` (the artifact is retained
untouched — the projection is the derived, rebuildable copy), and swaps the
finished projection into place atomically.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from media_catalog.links import canonicalize_url
from media_catalog.search_index.projection import ProjectionBuilder

BUILDER_VERSION = "e621-export-v1"

# e621 posts export: postgres text[] columns arrive quoted like
# {"a","b"}; unquoted entries carry no backslashes in practice.
_ARRAY = re.compile(r"^\{(.*)\}$", re.DOTALL)

_REQUIRED_COLUMNS = ("id", "md5")


@dataclass(frozen=True, slots=True)
class ImportResult:
    projection_path: Path
    snapshot_revision: str
    record_count: int
    artifact_digest: str
    artifact_path: str

    def as_dict(self) -> dict[str, object]:
        return {
            "projection": self.projection_path.name,
            "snapshot_revision": self.snapshot_revision,
            "record_count": self.record_count,
            "artifact_digest": self.artifact_digest,
            "artifact": self.artifact_path,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_array(value: str | None) -> list[str]:
    if not value:
        return []
    match = _ARRAY.match(value.strip())
    if match is None:
        item = value.strip()
        return [item] if item else []
    inner = match.group(1)
    if not inner.strip():
        return []
    items: list[str] = []
    for part in inner.split('","'):
        item = part.strip().strip('"')
        if item:
            items.append(item)
    return items


def _canonical(value: str) -> str:
    try:
        return canonicalize_url(value.strip()).canonical_url
    except ValueError:
        return value.strip()


def import_e621_export(
    artifact: Path,
    *,
    destination: Path,
    checksum: str | None = None,
    max_records: int | None = None,
) -> ImportResult:
    """Build a lookup-v1 projection from an e621 posts DB export."""
    artifact = Path(artifact)
    if not artifact.is_file():
        raise ValueError(f"artifact does not exist: {artifact.name}")
    digest = sha256_file(artifact)
    if checksum is not None and digest != checksum.strip().lower():
        raise ValueError(
            f"artifact checksum mismatch: expected {checksum.strip().lower()[:16]}…,"
            f" computed {digest[:16]}…"
        )
    revision = digest[:16]
    destination.parent.mkdir(parents=True, exist_ok=True)
    builder = ProjectionBuilder(
        provider="e621",
        destination=destination,
        artifact_path=artifact,
        artifact_digest=digest,
        snapshot_revision=revision,
        builder_version=BUILDER_VERSION,
    )
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
            for index, row in enumerate(reader):
                if max_records is not None and index >= max_records:
                    break
                builder.add_post(
                    post_id=int(row["id"]),
                    md5=(row.get("md5") or None),
                    source=(row.get("source") or None) or None,
                    parent_id=int(row["parent_id"]) if row.get("parent_id") else None,
                    file_ext=row.get("file_ext") or None,
                    width=int(row["image_width"]) if row.get("image_width") else None,
                    height=int(row["image_height"]) if row.get("image_height") else None,
                    created_at=row.get("created_at") or None,
                    updated_at=row.get("updated_at") or None,
                    is_deleted=1 if (row.get("is_deleted") or "") == "t" else 0,
                    origin="export",
                    seen_at=row.get("updated_at") or row.get("created_at") or "",
                    sources=[_canonical(url) for url in _parse_array(row.get("source"))],
                    artists=[tag for tag in (row.get("tag_string_artist") or "").split() if tag],
                )
        result = ImportResult(
            projection_path=builder.commit(),
            snapshot_revision=revision,
            record_count=builder.record_count or 0,
            artifact_digest=digest,
            artifact_path=str(artifact),
        )
    except BaseException:
        builder.discard()
        raise
    return result
