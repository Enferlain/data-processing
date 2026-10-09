"""Deterministic JSONL and CSV serialization of one projection row sequence.

Both formats consume the same rows in the same order, so they cannot drift
logically.  JSONL is the canonical format (one canonical-JSON object per
line); CSV flattens the same objects with a deterministic column order and
canonical-JSON strings for nested values.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from media_catalog.projections.spec import canonical_json

_LINE_TERMINATOR = "\n"


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return canonical_json(value)
    if value is None:
        return ""
    return value


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> tuple[int, str]:
    """Write rows as canonical JSONL; return (row_count, content_digest)."""

    digest = hashlib.sha256()
    with path.open("w", encoding="utf-8", newline="") as handle:
        for row in rows:
            line = canonical_json(row) + _LINE_TERMINATOR
            handle.write(line)
            digest.update(line.encode("utf-8"))
    return len(rows), digest.hexdigest()


def write_csv(rows: list[dict[str, Any]], path: Path) -> tuple[int, str]:
    """Write rows as CSV; return (row_count, content_digest).

    Columns are the sorted union of row keys so the byte layout is stable
    across re-runs on unchanged evidence.
    """

    columns = sorted({key for row in rows for key in row})
    digest = hashlib.sha256()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator=_LINE_TERMINATOR)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_cell(row.get(column)) for column in columns])
        handle.flush()
        digest.update(path.read_bytes())
    return len(rows), digest.hexdigest()


def selection_digest(selection_keys: list[str]) -> str:
    """Digest over the ordered stable identifiers of the included rows."""

    return hashlib.sha256(
        (_LINE_TERMINATOR.join(selection_keys) + _LINE_TERMINATOR).encode("utf-8")
    ).hexdigest()


def parse_jsonl(path: Path) -> list[dict[str, Any]]:
    """Test/inspection helper: read canonical JSONL back as objects."""

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
