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
import sys
from dataclasses import dataclass
from pathlib import Path

from media_catalog.links import canonicalize_url
from media_catalog.search_index.projection import ProjectionBuilder

BUILDER_VERSION = "e621-export-v1"

# Progress goes to stderr only; stdout stays machine-readable (--json).
PROGRESS_INTERVAL_ROWS = 500_000

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
    scope: str = "unknown"
    columns_absent: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "projection": self.projection_path.name,
            "snapshot_revision": self.snapshot_revision,
            "scope": self.scope,
            "record_count": self.record_count,
            "artifact_digest": self.artifact_digest,
            "artifact": self.artifact_path,
            "columns_absent": list(self.columns_absent),
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
    # Postgres quotes array elements only when they need it: the posts
    # source column ships {"url","url"} while the artists other_names column
    # ships {name,name} — both styles occur in the real exports.
    parts = inner.split('","') if '","' in inner else inner.split(",")
    items: list[str] = []
    for part in parts:
        item = part.strip().strip('"')
        if item:
            items.append(item)
    return items


# Legacy e621 source elements pack SEVERAL URLs into one postgres array
# element — separated by whitespace/newlines, or jammed together with no
# separator at all (37% of source-bearing elements in the first 20k rows
# of the real 2026-11-09 export).  Each embedded URL must become its own
# lookup key.
_EMBEDDED_URL = re.compile(r"(?=https?://)")


def _element_urls(element: str) -> list[str]:
    urls: list[str] = []
    for token in element.split():
        urls.extend(part for part in _EMBEDDED_URL.split(token) if part)
    return urls


def canonical_export_url(value: str) -> str:
    """Canonicalize one export URL token with scheme repair.

    e621 exports mix scheme-full URLs with bare host/path tokens
    (``furaffinity.net/user/x``, case-preserved), which canonicalize_url
    passes through unchanged — permanently unmatchable against canonical
    probes.  A bare token whose first segment carries a dot is retried with
    ``https://`` before the raw fallback.
    """
    text = value.strip()
    if "://" not in text and "." in text.split("/", 1)[0]:
        text = f"https://{text}"
    try:
        return canonicalize_url(text).canonical_url
    except ValueError:
        return value.strip()


def _canonical(value: str) -> str:
    return canonical_export_url(value)


def import_e621_export(
    artifact: Path,
    *,
    destination: Path,
    checksum: str | None = None,
    max_records: int | None = None,
) -> ImportResult:
    """Build a lookup-v1 projection from an e621 posts DB export.

    The snapshot revision identifies the ACTUAL searchable scope: artifact
    digest + builder version + ``full`` when the artifact was consumed to
    EOF, else ``head<n>`` for the bounded prefix.  A bounded shakeout and a
    full import of the same artifact are therefore different revisions, and
    expanding coverage invalidates prior searches.
    """
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

    # Optional columns degrade to NULLs when the export layout changes; the
    # import must say so instead of silently dropping that data (the real
    # e621 posts export has no tag_string_artist — artist tags live in the
    # tags export, not here).
    optional_columns = (
        "source",
        "parent_id",
        "file_ext",
        "image_width",
        "image_height",
        "created_at",
        "updated_at",
        "is_deleted",
        "tag_string_artist",
    )
    truncated = False
    builder: ProjectionBuilder | None = None
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
            columns_absent = tuple(name for name in optional_columns if name not in header)
            builder = ProjectionBuilder(
                provider="e621",
                destination=destination,
                artifact_path=artifact,
                artifact_digest=digest,
                # The scope suffix is resolved at commit, once the rows have
                # said whether the artifact was consumed to EOF.
                snapshot_revision=f"{digest[:12]}-{BUILDER_VERSION}-pending",
                builder_version=BUILDER_VERSION,
            )
            for index, row in enumerate(reader):
                if max_records is not None and index >= max_records:
                    truncated = True
                    break
                if index and index % PROGRESS_INTERVAL_ROWS == 0:
                    print(f"e621 export: imported {index:,} rows…", file=sys.stderr)
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
                    sources=[
                        _canonical(url)
                        for element in _parse_array(row.get("source"))
                        for url in _element_urls(element)
                    ],
                    artists=[tag for tag in (row.get("tag_string_artist") or "").split() if tag],
                )
        assert builder is not None
        scope_value = f"head{max_records}" if truncated else "full"
        result = ImportResult(
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
