from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from media_catalog.database import CatalogDatabase


def caller_connection(database: CatalogDatabase) -> sqlite3.Connection:
    return database.connection


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def inserted_id(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise sqlite3.DatabaseError("insert did not produce a row identifier")
    return cursor.lastrowid


@dataclass(frozen=True, slots=True)
class WriteResult:
    id: int
    outcome: str
