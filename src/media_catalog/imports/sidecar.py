"""Grabber sidecar tag files retained during folder ingest (bead
``data-processing-h6d``, change ``parse-grabber-sidecars``).

Grabber saves one ``<image>.txt`` per downloaded image carrying the booru
tags the file was downloaded with.  The ingest walk already touches every
file, so parsing rides it: each sidecar is retained verbatim-plus-parsed as
a raw observation attached to its file seed — operator-supplied declared
material from the original download, evidence until a provider match
brings fresher facts.  Tags never write the provider tag tables (they are
post-scoped); ``pool:`` metatags are counted for the pool bead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.records.catalog import RawRecord
from media_catalog.writer import CatalogWriter

SOURCE_KIND = "folder_sidecar"
SIDECAR_SCHEMA = "grabber-sidecar-v1"
MAX_SIDECAR_BYTES = 64 * 1024

_CATEGORY_BY_PREFIX = {
    "general": "general",
    "artist": "artist",
    "copyright": "copyright",
    "character": "character",
    "meta": "meta",
    "species": "unknown",
    "studio": "unknown",
    "genre": "unknown",
    "medium": "unknown",
}


@dataclass(frozen=True, slots=True)
class ParsedSidecar:
    """Danbooru-style comma-separated tags with category prefixes."""

    tags: tuple[tuple[str, str], ...]
    pool_ids: tuple[str, ...]
    unparseable_lines: tuple[str, ...]


def parse_sidecar(text: str) -> ParsedSidecar:
    """Parse Grabber's saved tag lines into (name, category) pairs.

    Each non-empty line is a comma-separated tag list; entries carry an
    optional ``category:`` prefix (``pool:`` is a metatag, counted apart).
    Unprefixed entries are general tags or artist names — the category the
    kernel vocabulary cannot distinguish here is ``general``, matching how
    the labeling queue treats raw tag text.
    """

    tags: list[tuple[str, str]] = []
    pool_ids: list[str] = []
    unparseable: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "\x00" in line:
            unparseable.append(line[:80])
            continue
        for raw_entry in line.split(","):
            entry = raw_entry.strip()
            if not entry:
                continue
            prefix, separator, name = entry.partition(":")
            if separator and name:
                if prefix == "pool" and name.isdigit():
                    pool_ids.append(name)
                    continue
                category = _CATEGORY_BY_PREFIX.get(prefix.lower())
                if category is not None:
                    tags.append((name, category))
                    continue
            tags.append((entry, "general"))
    return ParsedSidecar(tuple(tags), tuple(pool_ids), tuple(unparseable))


class SidecarStore:
    """One ``folder_sidecar`` import run per ingest, raw evidence per seed."""

    def __init__(self, database: CatalogDatabase, *, digest: str, observed_at: str) -> None:
        self._database = database
        self._writer = CatalogWriter(database)
        self._run_id = self._begin_run(digest, observed_at)

    def _begin_run(self, digest: str, observed_at: str) -> int:
        connection = self._database.connection
        connection.execute(
            """INSERT INTO import_runs (
                   source_kind, source_reference, source_digest, source_size,
                   started_at, status
               ) VALUES (?, ?, ?, 0, ?, 'running')
               ON CONFLICT(source_kind, source_digest) DO NOTHING""",
            (SOURCE_KIND, "folder-sidecar", digest, observed_at),
        )
        row = connection.execute(
            """SELECT import_run_id FROM import_runs
                WHERE source_kind = ? AND source_digest = ?""",
            (SOURCE_KIND, digest),
        ).fetchone()
        assert row is not None
        # Re-ingesting a folder reuses its completed run: the per-seed raw
        # attach is conflict-idempotent, so reruns add nothing.
        return int(row["import_run_id"])

    def attach(
        self,
        seed_id: int,
        sidecar_path: Path,
        *,
        observed_at: str,
    ) -> dict[str, Any] | None:
        """Retain one sidecar as parsed evidence on its file seed.

        Returns ``None`` when the file is missing or oversized (counted as
        failed by the caller); otherwise the retention summary.
        """

        try:
            size = sidecar_path.stat().st_size
        except OSError:
            return None
        if not 0 < size <= MAX_SIDECAR_BYTES:
            return None
        try:
            text = sidecar_path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError):
            text = sidecar_path.read_text(encoding="utf-8", errors="replace")
        parsed = parse_sidecar(text)
        payload = json.dumps(
            {
                "version": 1,
                "kind": "folder_sidecar",
                "source_file": sidecar_path.name,
                "tags": [{"name": name, "category": category} for name, category in parsed.tags],
                "pool_ids": list(parsed.pool_ids),
                "unparseable_lines": list(parsed.unparseable_lines),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        raw_observation_id = self._writer.store_raw(
            RawRecord(
                payload,
                "application/json",
                "sidecar_tags",
                str(seed_id),
                observed_at,
                source_schema=SIDECAR_SCHEMA,
            ),
            import_run_id=self._run_id,
        )
        return {
            "raw_observation_id": raw_observation_id,
            "tag_count": len(parsed.tags),
            "pool_ids": list(parsed.pool_ids),
        }

    def finish(self, observed_at: str) -> None:
        connection = self._database.connection
        connection.execute(
            "UPDATE import_runs SET status = 'complete', finished_at = ? WHERE import_run_id = ?",
            (observed_at, self._run_id),
        )
