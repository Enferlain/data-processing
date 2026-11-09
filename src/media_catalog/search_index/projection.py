"""lookup-v1 projections: disposable provider lookup databases.

The projection is OUR derived format, built from raw provider artifacts and
always rebuildable from them; artifacts are retained untouched beside it
(their path and digest recorded in ``index_meta``). Discovery reads here
never write, and teaching (the shared post-commit boundary) is the only
writer afterwards.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from media_catalog.output import public_path

LOOKUP_FORMAT = "lookup-v1"

_SCHEMA = """
CREATE TABLE posts (
    post_id INTEGER PRIMARY KEY,
    md5 TEXT,
    source TEXT,
    parent_id INTEGER,
    file_ext TEXT,
    width INTEGER,
    height INTEGER,
    created_at TEXT,
    updated_at TEXT,
    is_deleted INTEGER,
    origin TEXT NOT NULL CHECK (origin IN ('export', 'api')),
    first_seen_at TEXT NOT NULL,
    last_confirmed_at TEXT NOT NULL
);
CREATE INDEX idx_posts_md5 ON posts(md5);
CREATE TABLE post_sources (
    post_id INTEGER NOT NULL,
    normalized_url TEXT NOT NULL,
    PRIMARY KEY (post_id, normalized_url)
) WITHOUT ROWID;
CREATE INDEX idx_sources_url ON post_sources(normalized_url);
CREATE TABLE post_artists (
    post_id INTEGER NOT NULL,
    artist_tag TEXT NOT NULL,
    PRIMARY KEY (post_id, artist_tag)
) WITHOUT ROWID;
CREATE INDEX idx_artists_tag ON post_artists(artist_tag);
CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    provider: str
    revision: str
    source_digest: str | None
    artifact_path: str | None
    record_count: int
    format: str


def _snapshot_from_meta(meta: dict[str, str]) -> SnapshotInfo:
    revision = meta.get("snapshot_revision") or ""
    if not revision:
        raise ValueError("projection is missing its snapshot revision")
    return SnapshotInfo(
        provider=meta.get("provider") or "",
        revision=revision,
        source_digest=meta.get("source_digest"),
        artifact_path=meta.get("artifact_path"),
        record_count=int(meta.get("record_count", "0")),
        format=meta.get("format") or "",
    )


def read_snapshot(path: Path) -> SnapshotInfo:
    """The projection's snapshot identity.

    Raises when the file is unreadable or not a lookup-v1 projection —
    binding the wrong database to a target name is exactly what registration
    must refuse loudly.
    """
    connection = open_read_only(path)
    try:
        meta = {
            str(row["key"]): str(row["value"])
            for row in connection.execute("SELECT key, value FROM index_meta")
        }
        if meta.get("format") != LOOKUP_FORMAT:
            raise ValueError(
                f"{public_path(Path(path))} is not a {LOOKUP_FORMAT} projection"
                f" (format: {meta.get('format') or 'unknown'})"
            )
        return _snapshot_from_meta(meta)
    finally:
        connection.close()


def open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


class ProjectionBuilder:
    """Build a lookup-v1 projection in a temp file, then swap it into place."""

    def __init__(
        self,
        *,
        provider: str,
        destination: Path,
        artifact_path: Path,
        artifact_digest: str,
        snapshot_revision: str,
        builder_version: str,
        record_count: int | None = None,
    ) -> None:
        self.provider = provider
        self.destination = Path(destination)
        self.artifact_path = str(artifact_path)
        self.artifact_digest = artifact_digest
        self.snapshot_revision = snapshot_revision
        self.builder_version = builder_version
        self.record_count = record_count
        self._temp = destination.with_name(destination.name + ".build-tmp")
        if self._temp.exists():
            self._temp.unlink()
        self._connection = sqlite3.connect(self._temp)
        self._connection.executescript(_SCHEMA)

    def add_post(
        self,
        *,
        post_id: int,
        md5: str | None,
        source: str | None,
        parent_id: int | None,
        file_ext: str | None,
        width: int | None,
        height: int | None,
        created_at: str | None,
        updated_at: str | None,
        is_deleted: int,
        origin: str,
        seen_at: str,
        sources: Iterable[str] = (),
        artists: Iterable[str] = (),
    ) -> None:
        self._connection.execute(
            """INSERT OR REPLACE INTO posts
                   (post_id, md5, source, parent_id, file_ext, width, height,
                    created_at, updated_at, is_deleted, origin,
                    first_seen_at, last_confirmed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                post_id,
                md5,
                source,
                parent_id,
                file_ext,
                width,
                height,
                created_at,
                updated_at,
                is_deleted,
                origin,
                seen_at,
                seen_at,
            ),
        )
        for url in sources:
            self._connection.execute(
                "INSERT OR IGNORE INTO post_sources (post_id, normalized_url) VALUES (?, ?)",
                (post_id, url),
            )
        for artist in artists:
            self._connection.execute(
                "INSERT OR IGNORE INTO post_artists (post_id, artist_tag) VALUES (?, ?)",
                (post_id, artist),
            )

    def discard(self) -> None:
        """Remove the temp build file; the destination is left untouched."""
        self._connection.close()
        if self._temp.exists():
            self._temp.unlink()

    def commit(self) -> Path:
        count = int(self._connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
        self.record_count = count
        meta = {
            "format": LOOKUP_FORMAT,
            "provider": self.provider,
            "snapshot_revision": self.snapshot_revision,
            "source_digest": self.artifact_digest,
            "artifact_path": self.artifact_path,
            "record_count": str(self.record_count if self.record_count is not None else count),
            "builder_version": self.builder_version,
        }
        self._connection.executemany(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            sorted(meta.items()),
        )
        self._connection.commit()
        self._connection.close()
        from os import replace

        replace(self._temp, self.destination)
        return self.destination


def _registration_rows(connection: Any) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """SELECT target_name, provider, index_format, private_path,
                      snapshot_revision, registered_at, last_refreshed_at
                 FROM search_index_registrations
                ORDER BY search_index_registration_id"""
        )
    )


@dataclass(frozen=True, slots=True)
class IndexTarget:
    """One registered index resolved against its projection file."""

    name: str
    provider: str
    path: Path
    snapshot: SnapshotInfo | None
    problem: str | None

    @property
    def version(self) -> str:
        revision = self.snapshot.revision if self.snapshot else "unknown"
        # Version charset follows the records VERSION_PATTERN; the revision
        # rides the strategy version so refresh invalidates freshness.
        return f"{LOOKUP_FORMAT}.{revision}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.name,
            "provider": self.provider,
            "format": LOOKUP_FORMAT,
            "path": self.path.name,
            "snapshot_revision": self.snapshot.revision if self.snapshot else None,
            "record_count": self.snapshot.record_count if self.snapshot else None,
            "problem": self.problem,
        }


def registered_targets(connection: Any) -> list[IndexTarget]:
    """Resolve registrations against their projection files (read-only).

    A missing/unreadable projection never raises: the planner excludes the
    target with the problem named and discovery continues.
    """
    targets: list[IndexTarget] = []
    for row in _registration_rows(connection):
        name = str(row["target_name"])
        path = Path(str(row["private_path"]))
        snapshot: SnapshotInfo | None = None
        problem: str | None = None
        if not path.is_file():
            problem = f"projection file missing: {public_path(path)}"
        else:
            try:
                snapshot = read_snapshot(path)
                if snapshot.provider != str(row["provider"]):
                    problem = (
                        f"projection reports provider {snapshot.provider or '?'},"
                        f" registration records {row['provider']}"
                    )
                    snapshot = None
            except (sqlite3.Error, ValueError) as error:
                problem = f"projection unreadable: {error}"
        targets.append(
            IndexTarget(
                name=name,
                provider=str(row["provider"]),
                path=path,
                snapshot=snapshot,
                problem=problem,
            )
        )
    return targets


def target_by_name(connection: Any, name: str) -> IndexTarget | None:
    for target in registered_targets(connection):
        if target.name == name:
            return target
    return None


@dataclass(frozen=True, slots=True)
class _LookupPlan:
    statement: str

    def rows(self, connection: sqlite3.Connection, value: str, limit: int) -> list[sqlite3.Row]:
        return list(connection.execute(self.statement, (value, limit)))


def _lookup_plan(method: str) -> _LookupPlan | None:
    """The projection query for one discovery method, or None."""
    if method in {"verified_md5", "declared_md5"}:
        return _LookupPlan("SELECT post_id, md5, source FROM posts WHERE md5 = ? LIMIT ?")
    if method == "external_post_id":
        return _LookupPlan("SELECT post_id, md5 FROM posts WHERE post_id = ? LIMIT ?")
    if method == "source_post_url":
        return _LookupPlan(
            "SELECT ps.post_id, p.md5 FROM post_sources ps"
            " JOIN posts p ON p.post_id = ps.post_id"
            " WHERE ps.normalized_url = ? LIMIT ?"
        )
    if method in {"artist_exact_name", "artist_alias", "artist_text"}:
        return _LookupPlan(
            "SELECT pa.post_id, p.md5 FROM post_artists pa"
            " JOIN posts p ON p.post_id = pa.post_id"
            " WHERE pa.artist_tag = ? LIMIT ?"
        )
    return None


def lookup(
    target: IndexTarget,
    *,
    method: str,
    values: Iterable[str],
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Point-lookup one method's values against a projection (read-only).

    ``method`` is the discovery method string; unknown methods raise so the
    planner can never promise a lookup the projection cannot serve.
    """
    assert target.snapshot is not None
    plan = _lookup_plan(method)
    if plan is None:
        raise ValueError(f"index target does not support method {method}")
    connection = open_read_only(target.path)
    try:
        seen: set[str] = set()
        hits: list[dict[str, Any]] = []
        for value in values:
            rows = plan.rows(connection, value, limit)
            for row in rows:
                post_id = str(row["post_id"])
                if post_id in seen:
                    continue
                seen.add(post_id)
                hit_md5 = (
                    row["md5"]
                    if "md5" in row.keys()  # noqa: SIM118  (sqlite3.Row has no __contains__)
                    else None
                )
                if hit_md5 is None:
                    fetched = connection.execute(
                        "SELECT md5 FROM posts WHERE post_id = ?", (post_id,)
                    ).fetchone()
                    hit_md5 = fetched[0] if fetched else None
                sources = [
                    str(r["normalized_url"])
                    for r in connection.execute(
                        "SELECT normalized_url FROM post_sources WHERE post_id = ?",
                        (post_id,),
                    )
                ]
                hits.append(
                    {
                        "provider": target.provider,
                        "post_native_id": post_id,
                        "md5": hit_md5,
                        "sources": sources,
                    }
                )
                if len(hits) >= limit:
                    return hits
        return hits
    finally:
        connection.close()


def teach(
    connection: Any,
    items: Iterable[dict[str, Any]],
) -> int:
    """Upsert provider-confirmed post identities into registered projections.

    Called from the shared post-commit boundary (NormalizedPageWriter) for
    every persisted provider post.  Each item: provider, native_id, md5,
    canonical_url, sources.  Returns the number of indexes written; the hook
    contains all failures, so this raises only on programmer error.
    """
    by_provider: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_provider.setdefault(str(item["provider"]), []).append(item)
    written = 0
    seen_at = _dt.datetime.now(_dt.UTC).isoformat().replace("+00:00", "Z")
    for row in _registration_rows(connection):
        provider = str(row["provider"])
        batch = by_provider.get(provider)
        if not batch:
            continue
        path = Path(str(row["private_path"]))
        if not path.is_file():
            continue
        writer = _TeachWriter(path, provider)
        try:
            snapshot = read_snapshot(path)
            if snapshot is None or snapshot.provider != provider:
                continue
            for item in batch:
                writer.teach_one(
                    post_id=int(str(item["native_id"])),
                    md5=item.get("md5"),
                    sources=[
                        str(url)
                        for url in [item.get("canonical_url"), *item.get("sources", [])]
                        if url
                    ],
                    seen_at=seen_at,
                )
            writer.close()
            written += 1
        except (sqlite3.Error, OSError, ValueError):
            # Failure containment is the whole point: an unwritable index
            # never affects the catalog write that already committed.
            writer.close()
            continue
    return written


class _TeachWriter:
    """Minimal in-place upserts on a projection (teach hook only)."""

    def __init__(self, path: Path, provider: str) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.provider = provider

    def teach_one(self, *, post_id: int, md5: str | None, sources: list[str], seen_at: str) -> None:
        self.connection.execute(
            """INSERT INTO posts (post_id, md5, origin, first_seen_at, last_confirmed_at)
               VALUES (?, ?, 'api', ?, ?)
               ON CONFLICT(post_id) DO UPDATE SET
                   last_confirmed_at = excluded.last_confirmed_at,
                   md5 = COALESCE(excluded.md5, md5)""",
            (post_id, md5, seen_at, seen_at),
        )
        for url in sources:
            self.connection.execute(
                "INSERT OR IGNORE INTO post_sources (post_id, normalized_url) VALUES (?, ?)",
                (post_id, url),
            )

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()


def teach_json_note(count: int) -> str:
    return json.dumps({"taught": count})
