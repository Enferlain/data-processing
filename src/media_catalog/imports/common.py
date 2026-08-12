from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from media_catalog.database import CatalogDatabase
from media_catalog.output import bounded_error, public_path
from media_catalog.writer import CatalogWriter

CountMap = dict[str, dict[str, int]]


@dataclass(frozen=True, slots=True)
class ImportReport:
    import_run_id: int
    source_kind: str
    source: str
    source_digest: str
    status: str
    counts: CountMap
    reused: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "import_run_id": self.import_run_id,
            "source_kind": self.source_kind,
            "source": self.source,
            "source_digest": self.source_digest,
            "status": self.status,
            "counts": self.counts,
            "reused": self.reused,
        }


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def source_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def run_import(
    database: CatalogDatabase,
    source: Path,
    source_kind: str,
    importer: Callable[[CatalogWriter, int, Path], CountMap],
) -> ImportReport:
    source = source.resolve(strict=True)
    digest, size = source_digest(source)
    existing = database.connection.execute(
        """SELECT import_run_id, status FROM import_runs
           WHERE source_kind = ? AND source_digest = ?""",
        (source_kind, digest),
    ).fetchone()
    if existing is not None and existing["status"] == "complete":
        counts = _load_counts(database, int(existing["import_run_id"]))
        return ImportReport(
            int(existing["import_run_id"]),
            source_kind,
            public_path(source),
            digest,
            "complete",
            counts,
            True,
        )
    started_at = now()
    with database.transaction():
        if existing is None:
            cursor = database.connection.execute(
                """INSERT INTO import_runs (
                       source_kind, source_reference, source_digest, source_size, started_at, status
                   ) VALUES (?, ?, ?, ?, ?, 'running')""",
                (source_kind, public_path(source), digest, size, started_at),
            )
            if cursor.lastrowid is None:
                raise sqlite3.DatabaseError("import run insert did not produce a row identifier")
            import_run_id = cursor.lastrowid
        else:
            import_run_id = int(existing["import_run_id"])
            database.connection.execute(
                """UPDATE import_runs SET started_at = ?, finished_at = NULL, status = 'running'
                   WHERE import_run_id = ?""",
                (started_at, import_run_id),
            )
    try:
        with database.transaction():
            counts = importer(CatalogWriter(database), import_run_id, source)
            _save_counts(database, import_run_id, counts)
            database.connection.execute(
                """UPDATE import_runs SET status = 'complete', finished_at = ?
                   WHERE import_run_id = ?""",
                (now(), import_run_id),
            )
    except BaseException as error:
        with database.transaction():
            failure_counts = getattr(error, "counts", None)
            if not isinstance(failure_counts, dict):
                failure_counts = {
                    "records": {
                        "source": 0,
                        "inserted": 0,
                        "updated": 0,
                        "existing": 0,
                        "skipped": 0,
                        "failed": 1,
                    }
                }
            _save_counts(database, import_run_id, failure_counts)
            database.connection.execute(
                """UPDATE import_runs SET status = 'failed', finished_at = ?
                   WHERE import_run_id = ?""",
                (now(), import_run_id),
            )
            database.connection.execute(
                """INSERT INTO import_diagnostics (
                       import_run_id, severity, code, message
                   ) VALUES (?, 'error', 'import_failed', ?)""",
                (import_run_id, bounded_error(error, private_paths=(source,))),
            )
        raise
    return ImportReport(import_run_id, source_kind, public_path(source), digest, "complete", counts)


def _save_counts(database: CatalogDatabase, import_run_id: int, counts: CountMap) -> None:
    for entity_kind, values in counts.items():
        database.connection.execute(
            """INSERT INTO import_run_counts (
                   import_run_id, entity_kind, source_count, inserted_count, updated_count,
                   existing_count, skipped_count, failed_count
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(import_run_id, entity_kind) DO UPDATE SET
                   source_count = excluded.source_count,
                   inserted_count = excluded.inserted_count,
                   updated_count = excluded.updated_count,
                   existing_count = excluded.existing_count,
                   skipped_count = excluded.skipped_count,
                   failed_count = excluded.failed_count""",
            (
                import_run_id,
                entity_kind,
                values.get("source", 0),
                values.get("inserted", 0),
                values.get("updated", 0),
                values.get("existing", 0),
                values.get("skipped", 0),
                values.get("failed", 0),
            ),
        )


def _load_counts(database: CatalogDatabase, import_run_id: int) -> CountMap:
    result: CountMap = {}
    for row in database.connection.execute(
        "SELECT * FROM import_run_counts WHERE import_run_id = ?", (import_run_id,)
    ):
        result[row["entity_kind"]] = {
            key: int(row[f"{key}_count"])
            for key in ("source", "inserted", "updated", "existing", "skipped", "failed")
        }
    return result
