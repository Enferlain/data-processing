"""lookup-v1 projections: disposable provider lookup databases.

The projection is OUR derived format, built from raw provider artifacts and
always rebuildable from them; artifacts are retained untouched beside it
(their path and digest recorded in ``index_meta``). Discovery reads here
never write, and teaching (the shared post-commit boundary) is the only
writer afterwards.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from media_catalog.output import public_path

LOOKUP_FORMAT = "lookup-v1"

# The method set a posts projection serves when index_meta records no
# explicit capabilities (artist projections list theirs).
DEFAULT_CAPABILITIES = (
    "verified_md5",
    "declared_md5",
    "source_post_url",
    "external_post_id",
    "artist_exact_name",
    "artist_alias",
    "artist_text",
)

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

_ARTIST_SCHEMA = """
CREATE TABLE artist_entries (
    artist_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    group_name TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT
);
CREATE TABLE artist_names (
    artist_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    PRIMARY KEY (artist_id, name, kind)
);
CREATE INDEX idx_artist_names_name ON artist_names(name);
CREATE TABLE artist_urls (
    artist_id INTEGER NOT NULL,
    normalized_url TEXT NOT NULL,
    active INTEGER NOT NULL,
    PRIMARY KEY (artist_id, normalized_url)
);
CREATE INDEX idx_artist_urls_url ON artist_urls(normalized_url);
"""


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    """The projection's searchable identity.

    ``revision`` identifies the base import (artifact digest + builder +
    scope: a bounded head-N import is a different revision from a full one,
    so expanding coverage invalidates prior searches).  ``overlay_generation``
    counts teach mutations since the build — the version that freshness
    compares is ``lookup-v1.<revision>.g<generation>``, so taught content
    replans prior attempts too.
    """

    provider: str
    revision: str
    source_digest: str | None
    artifact_path: str | None
    record_count: int
    format: str
    scope: str = "unknown"
    overlay_generation: int = 0
    # Methods this projection serves (from index_meta; the post-method set
    # when the key is absent, so pre-capability projections keep working).
    capabilities: tuple[str, ...] = ()


def _snapshot_from_meta(meta: dict[str, str]) -> SnapshotInfo:
    revision = meta.get("snapshot_revision") or ""
    if not revision:
        raise ValueError("projection is missing its snapshot revision")
    try:
        generation = int(meta.get("overlay_generation", "0"))
    except ValueError:
        generation = 0
    capabilities = tuple(
        part.strip() for part in (meta.get("capabilities") or "").split(",") if part.strip()
    )
    if not capabilities:
        # Pre-capability projections (posts-only) keep serving the original
        # method set; artist projections record an explicit list.
        capabilities = DEFAULT_CAPABILITIES
    return SnapshotInfo(
        provider=meta.get("provider") or "",
        revision=revision,
        source_digest=meta.get("source_digest"),
        artifact_path=meta.get("artifact_path"),
        record_count=int(meta.get("record_count", "0")),
        format=meta.get("format") or "",
        scope=meta.get("scope") or "unknown",
        overlay_generation=generation,
        capabilities=capabilities,
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
        scope: str = "unknown",
        record_count: int | None = None,
        capabilities: tuple[str, ...] | None = None,
        count_table: str = "posts",
        artist_schema: bool = False,
    ) -> None:
        self.provider = provider
        self.destination = Path(destination)
        self.artifact_path = str(artifact_path)
        self.artifact_digest = artifact_digest
        self.snapshot_revision = snapshot_revision
        self.builder_version = builder_version
        self.scope = scope
        self.record_count = record_count
        self.capabilities = capabilities
        self.count_table = count_table
        self._temp = destination.with_name(destination.name + ".build-tmp")
        if self._temp.exists():
            self._temp.unlink()
        self._connection = sqlite3.connect(self._temp)
        self._connection.executescript(_SCHEMA)
        # Keyed on the builder kind, not on "capabilities were passed": a
        # posts importer that someday records explicit capabilities must not
        # silently gain empty artist tables.
        if artist_schema:
            self._connection.executescript(_ARTIST_SCHEMA)

    def add_artist(
        self,
        *,
        artist_id: int,
        name: str,
        group_name: str | None,
        is_active: int,
        updated_at: str | None,
        other_names: Iterable[str] = (),
        urls: Iterable[tuple[str, int]] = (),
    ) -> None:
        """One artist entry; ``urls`` are (normalized_url, active) pairs."""
        # Duplicate artist ids in the export must not accumulate child rows:
        # the later occurrence replaces names/urls entirely.
        self._connection.execute("DELETE FROM artist_names WHERE artist_id = ?", (artist_id,))
        self._connection.execute("DELETE FROM artist_urls WHERE artist_id = ?", (artist_id,))
        self._connection.execute(
            """INSERT OR REPLACE INTO artist_entries
                   (artist_id, name, group_name, is_active, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (artist_id, name, group_name, is_active, updated_at),
        )
        for other in other_names:
            self._connection.execute(
                "INSERT OR IGNORE INTO artist_names (artist_id, name, kind) VALUES (?, ?, 'other')",
                (artist_id, other),
            )
        for url, active in urls:
            self._connection.execute(
                "INSERT OR IGNORE INTO artist_urls (artist_id, normalized_url, active)"
                " VALUES (?, ?, ?)",
                (artist_id, url, active),
            )

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

    def commit(self, *, scope: str | None = None) -> Path:
        count = int(
            self._connection.execute(f"SELECT COUNT(*) FROM {self.count_table}").fetchone()[0]
        )
        self.record_count = count
        if scope is not None:
            self.scope = scope
            if self.snapshot_revision.endswith("-pending"):
                # The import scope is only known after the rows are read
                # (EOF means full); resolve it into the revision so a
                # bounded shakeout and a full import never share identity.
                self.snapshot_revision = self.snapshot_revision[: -len("-pending")] + f"-{scope}"
        meta: dict[str, str] = {
            "format": LOOKUP_FORMAT,
            "provider": self.provider,
            "snapshot_revision": self.snapshot_revision,
            "scope": self.scope,
            "overlay_generation": "0",
            "source_digest": self.artifact_digest,
            "artifact_path": self.artifact_path,
            "record_count": str(self.record_count if self.record_count is not None else count),
            "builder_version": self.builder_version,
        }
        if self.capabilities is not None:
            meta["capabilities"] = ",".join(self.capabilities)
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
        # Version charset follows the records VERSION_PATTERN; the base
        # revision (artifact + builder + import scope) and the teach overlay
        # generation both ride the strategy version, so an expanded import or
        # taught content invalidates prior attempts.
        if self.snapshot is None:
            return f"{LOOKUP_FORMAT}.unknown"
        return f"{LOOKUP_FORMAT}.{self.snapshot.revision}.g{self.snapshot.overlay_generation}"

    def serves(self, method: str) -> bool:
        """Whether this projection serves a discovery method."""
        if self.snapshot is None:
            return False
        return method in self.snapshot.capabilities

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.name,
            "provider": self.provider,
            "format": LOOKUP_FORMAT,
            "path": self.path.name,
            "snapshot_revision": self.snapshot.revision if self.snapshot else None,
            "scope": self.snapshot.scope if self.snapshot else None,
            "overlay_generation": (self.snapshot.overlay_generation if self.snapshot else None),
            "capabilities": (list(self.snapshot.capabilities) if self.snapshot else []),
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
    if method == "artist_identifier":
        return _LookupPlan("SELECT artist_id FROM artist_urls WHERE normalized_url = ? LIMIT ?")
    if method in {"artist_exact_name", "artist_alias", "artist_text"}:
        return _LookupPlan(
            "SELECT pa.post_id, p.md5 FROM post_artists pa"
            " JOIN posts p ON p.post_id = pa.post_id"
            " WHERE pa.artist_tag = ? LIMIT ?"
        )
    return None


def _artist_identifier_hits(
    target: IndexTarget,
    connection: sqlite3.Connection,
    values: Iterable[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Artist-entry leads for identifier probes; a different hit shape from
    post lookups (artist entries are not posts and never feed the fetch
    bridge)."""
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        rows = connection.execute(
            """SELECT au.artist_id, ae.name, ae.is_active,
                      au.normalized_url AS matched_url,
                      (SELECT GROUP_CONCAT(n.name, ' ') FROM artist_names n
                        WHERE n.artist_id = au.artist_id
                          AND n.kind = 'other') AS other_names
                 FROM artist_urls au
                 JOIN artist_entries ae ON ae.artist_id = au.artist_id
                WHERE au.normalized_url = ? LIMIT ?""",
            (value, limit),
        )
        for row in rows:
            artist_id = str(row["artist_id"])
            if artist_id in seen:
                continue
            name = str(row["name"] or "").strip()
            if not name:
                # The lead table CHECKs a non-empty bounded name; skip
                # entries that could not satisfy it instead of aborting the
                # session mid-run.
                continue
            seen.add(artist_id)
            hits.append(
                {
                    "provider": target.provider,
                    "artist_id": artist_id,
                    "name": name[:200],
                    "other_names": str(row["other_names"] or "")[:800].split(),
                    "matched_url": row["matched_url"],
                    "is_active": bool(row["is_active"]),
                }
            )
            if len(hits) >= limit:
                return hits
    return hits


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
    if plan is None or not target.serves(method):
        raise ValueError(f"index target does not support method {method}")
    connection = open_read_only(target.path)
    try:
        if method == "artist_identifier":
            return _artist_identifier_hits(target, connection, values, limit)
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
    canonical_url, sources (provider source URLs), artists.  Each index
    write is one transaction: either the whole batch lands and the teach
    overlay generation is bumped when content changed, or the transaction
    rolls back leaving the projection (and its generation) untouched.  A
    durable ``teach_log`` row records every landed batch for inspection.
    Returns the number of indexes written; failures are contained here —
    the committed catalog write is never affected.
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
        try:
            snapshot = read_snapshot(path)
            if snapshot.provider != provider:
                continue
            if "verified_md5" not in snapshot.capabilities:
                # Post teach material belongs to post projections only: an
                # artists projection registered under the same provider must
                # not grow post rows (and a forever-churning generation).
                continue
            _TeachWriter(path).teach_batch(batch, seen_at=seen_at)
            written += 1
        except (sqlite3.Error, OSError, ValueError):
            # Failure containment is the whole point: an unwritable index
            # never affects the catalog write that already committed, and a
            # failed batch leaves no partial rows behind.
            continue
    return written


_TEACH_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS teach_log (
    teach_log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    taught_at TEXT NOT NULL,
    posts INTEGER NOT NULL,
    changed INTEGER NOT NULL,
    overlay_generation INTEGER NOT NULL
)
"""


class _TeachWriter:
    """One transactional teach batch against a projection (teach hook only)."""

    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path, timeout=5.0)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 5000")

    def teach_batch(self, batch: list[dict[str, Any]], *, seen_at: str) -> dict[str, int]:
        self.connection.execute(_TEACH_LOG_SCHEMA)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            changed = 0
            for item in batch:
                changed += self._teach_one(
                    post_id=int(str(item["native_id"])),
                    md5=item.get("md5"),
                    sources=[
                        str(url)
                        for url in [item.get("canonical_url"), *item.get("sources", [])]
                        if url
                    ],
                    artists=[str(tag) for tag in item.get("artists", ()) if tag],
                    seen_at=seen_at,
                )
            generation = self._bump_generation() if changed else self._generation()
            self.connection.execute(
                """INSERT INTO teach_log
                       (taught_at, posts, changed, overlay_generation)
                   VALUES (?, ?, ?, ?)""",
                (seen_at, len(batch), changed, generation),
            )
            self.connection.commit()
        except BaseException:
            # Roll back, never commit whatever happened before the failure.
            self.connection.rollback()
            raise
        finally:
            self.connection.close()
        return {"posts": len(batch), "changed": changed, "overlay_generation": generation}

    def _teach_one(
        self,
        *,
        post_id: int,
        md5: str | None,
        sources: list[str],
        artists: list[str],
        seen_at: str,
    ) -> int:
        """Upsert one identity; returns 1 when content actually changed."""
        existing = self.connection.execute(
            "SELECT md5 FROM posts WHERE post_id = ?", (post_id,)
        ).fetchone()
        new_post = existing is None
        new_md5 = md5 is not None and (existing is None or existing["md5"] is None)
        changed = 1 if (new_post or new_md5) else 0
        self.connection.execute(
            """INSERT INTO posts (post_id, md5, origin, first_seen_at, last_confirmed_at)
               VALUES (?, ?, 'api', ?, ?)
               ON CONFLICT(post_id) DO UPDATE SET
                   last_confirmed_at = excluded.last_confirmed_at,
                   md5 = COALESCE(excluded.md5, md5)""",
            (post_id, md5, seen_at, seen_at),
        )
        for url in sources:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO post_sources (post_id, normalized_url) VALUES (?, ?)",
                (post_id, url),
            )
            changed += cursor.rowcount
        for artist in artists:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO post_artists (post_id, artist_tag) VALUES (?, ?)",
                (post_id, artist),
            )
            changed += cursor.rowcount
        return min(1, changed)

    def _generation(self) -> int:
        row = self.connection.execute(
            "SELECT value FROM index_meta WHERE key = 'overlay_generation'"
        ).fetchone()
        try:
            return int(row["value"]) if row else 0
        except ValueError:
            return 0

    def _bump_generation(self) -> int:
        generation = self._generation() + 1
        self.connection.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES ('overlay_generation', ?)",
            (str(generation),),
        )
        return generation
