from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from importlib import resources
from pathlib import Path
from typing import Any

MIGRATION_PACKAGE = "media_catalog.migrations"
READ_ONLY_SNAPSHOT_LIMIT = 512 * 1024 * 1024


class SchemaVersionError(RuntimeError):
    """Raised when a catalog schema cannot be used by this software."""


def available_migrations() -> tuple[tuple[int, str, str], ...]:
    migrations: list[tuple[int, str, str]] = []
    root = resources.files(MIGRATION_PACKAGE)
    for item in root.iterdir():
        if not item.name.endswith(".sql"):
            continue
        prefix, separator, _ = item.name.partition("_")
        if not separator or not prefix.isdigit():
            raise SchemaVersionError(f"invalid packaged migration name: {item.name}")
        migrations.append((int(prefix), item.name, item.read_text(encoding="utf-8")))
    migrations.sort()
    versions = [version for version, _, _ in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise SchemaVersionError(f"migration versions must be contiguous from 1: {versions}")
    return tuple(migrations)


def current_schema_version() -> int:
    migrations = available_migrations()
    return migrations[-1][0] if migrations else 0


class CatalogDatabase:
    def __init__(self, path: Path, *, migrate: bool = True) -> None:
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path, timeout=5.0)
        try:
            self.connection.row_factory = sqlite3.Row
            self._check_version()
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA busy_timeout = 5000")
            self.connection.execute("PRAGMA journal_mode = WAL")
            if migrate:
                self.migrate()
            self.search_backend = self._initialize_search()
        except BaseException:
            self.connection.close()
            raise

    @classmethod
    def open_read_only(cls, path: Path) -> CatalogDatabase:
        """Open an existing current-schema catalog without any filesystem writes.

        The database is read through one no-follow descriptor, checked for
        stability and transaction-sidecar safety on both sides of the read,
        then deserialized into a query-only in-memory connection.  This avoids
        SQLite journal/SHM creation and closes races where WAL frames or a
        rollback journal can appear during a pathname-based snapshot.
        """

        path = Path(os.path.abspath(os.fspath(path)))
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except OSError as error:
            raise sqlite3.OperationalError("unable to open database file read-only") from error
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise sqlite3.OperationalError("catalog is not a regular file")
            if before.st_size > READ_ONLY_SNAPSHOT_LIMIT:
                raise SchemaVersionError(
                    "catalog exceeds the bounded read-only snapshot size; use a normal backup or "
                    "query workflow with sufficient resources"
                )
            cls._require_absent_wal(path)
            cls._require_absent_rollback_journal(path)
            payload = bytearray(before.st_size)
            view = memoryview(payload)
            offset = 0
            while offset < before.st_size:
                chunk = os.read(fd, min(1024 * 1024, before.st_size - offset))
                if not chunk:
                    raise SchemaVersionError("catalog was truncated during read-only snapshot")
                view[offset : offset + len(chunk)] = chunk
                offset += len(chunk)
            view.release()
            after = os.fstat(fd)
            cls._require_absent_wal(path)
            cls._require_absent_rollback_journal(path)
            stable = (
                (before.st_dev, before.st_ino, before.st_size)
                == (after.st_dev, after.st_ino, after.st_size)
                and before.st_mtime_ns == after.st_mtime_ns
                and before.st_ctime_ns == after.st_ctime_ns
            )
            if not stable:
                raise SchemaVersionError(
                    "catalog changed during read-only snapshot; stop writers and retry"
                )
            if len(payload) < 100 or payload[:16] != b"SQLite format 3\x00":
                raise sqlite3.DatabaseError("file is not a database")
            # Bytes 18/19 are the file read/write versions.  A main database
            # checkpointed from WAL mode still carries value 2 and would make
            # an in-memory deserialization look for a filesystem WAL.  The
            # snapshot has already proven no frames exist, so convert only the
            # private copy to rollback format before deserializing it.
            payload[18:20] = b"\x01\x01"
        finally:
            os.close(fd)
        connection = sqlite3.connect(":memory:", timeout=5.0)
        database = cls.__new__(cls)
        database.path = path
        database.connection = connection
        try:
            connection.deserialize(payload)
            # The serialized header may retain WAL mode.  The snapshot is an
            # isolated in-memory database, so disable journaling before reads
            # instead of letting SQLite look for filesystem sidecars.
            connection.execute("PRAGMA journal_mode = OFF")
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            database._check_current_version()
            # FTS index rebuilding is a write operation.  The LIKE query path is
            # safe for read-only connections and leaves any existing FTS table untouched.
            database.search_backend = "like"
        except BaseException:
            connection.close()
            raise
        return database

    @staticmethod
    def _require_absent_wal(path: Path) -> None:
        try:
            wal_stat = Path(f"{path}-wal").lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            raise sqlite3.OperationalError(
                "cannot safely inspect the catalog WAL sidecar for read-only access"
            ) from error
        if (
            stat.S_ISREG(wal_stat.st_mode)
            and not stat.S_ISLNK(wal_stat.st_mode)
            and wal_stat.st_size <= 32
        ):
            return
        raise SchemaVersionError(
            "catalog has WAL frames or an unsafe WAL sidecar; stop writers, create a backup, and "
            "complete the normal checkpoint workflow before read-only access"
        )

    @staticmethod
    def _require_absent_rollback_journal(path: Path) -> None:
        try:
            journal_stat = Path(f"{path}-journal").lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            raise sqlite3.OperationalError(
                "cannot safely inspect the catalog rollback journal for read-only access"
            ) from error
        if stat.S_ISREG(journal_stat.st_mode) and journal_stat.st_size == 0:
            return
        raise SchemaVersionError(
            "catalog has a pending rollback journal or an unsafe rollback-journal sidecar; stop "
            "writers, create a backup, and complete normal recovery before read-only access"
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> CatalogDatabase:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        return int(self.connection.execute("PRAGMA user_version").fetchone()[0])

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self.connection.in_transaction:
            raise RuntimeError("nested catalog transactions are not supported")
        self.connection.execute("BEGIN")
        try:
            yield
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def _check_version(self) -> None:
        found = self.schema_version
        supported = current_schema_version()
        if found > supported:
            raise SchemaVersionError(
                f"catalog schema version {found} is newer than supported version {supported}"
            )

    def _check_current_version(self) -> None:
        found = self.schema_version
        supported = current_schema_version()
        if found == supported:
            return
        direction = "older" if found < supported else "newer"
        raise SchemaVersionError(
            f"catalog schema version {found} is {direction} than supported version {supported}; "
            "create a backup of the catalog and use the normal migration workflow or a compatible "
            "software release before retrying read-only access"
        )

    def migrate(self) -> None:
        self._check_version()
        foreign_keys_enabled = bool(self.connection.execute("PRAGMA foreign_keys").fetchone()[0])
        if foreign_keys_enabled:
            self.connection.execute("PRAGMA foreign_keys = OFF")
        try:
            for version, name, sql in available_migrations():
                if version <= self.schema_version:
                    continue
                try:
                    self.connection.executescript(
                        f"BEGIN EXCLUSIVE;\n{sql}\nPRAGMA user_version = {version};"
                    )
                    violations = list(self.connection.execute("PRAGMA foreign_key_check"))
                    if violations:
                        raise sqlite3.IntegrityError(
                            f"migration left {len(violations)} foreign-key violation(s)"
                        )
                    self.connection.commit()
                except sqlite3.Error as error:
                    with suppress(sqlite3.Error):
                        self.connection.execute("ROLLBACK")
                    raise SchemaVersionError(
                        f"failed to apply migration {name}: {error}"
                    ) from error
        finally:
            if foreign_keys_enabled:
                self.connection.execute("PRAGMA foreign_keys = ON")

    def schema_info(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "supported_schema_version": current_schema_version(),
            "search_backend": self.search_backend,
        }

    def doctor(self) -> dict[str, Any]:
        integrity_rows = [row[0] for row in self.connection.execute("PRAGMA integrity_check")]
        foreign_key_rows = [
            dict(row) for row in self.connection.execute("PRAGMA foreign_key_check")
        ]
        ok = integrity_rows == ["ok"] and not foreign_key_rows
        return {
            "ok": ok,
            "integrity": integrity_rows,
            "foreign_key_violations": foreign_key_rows,
            **self.schema_info(),
        }

    def summary(self) -> dict[str, int]:
        tables = (
            "platforms",
            "accounts",
            "account_snapshots",
            "posts",
            "observations",
            "media_occurrences",
            "assets",
            "import_runs",
        )
        return {
            table: int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }

    def stats(self, *, event_type: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"counts": self.summary()}
        if event_type is not None:
            result["event_type"] = event_type
            result["matching_posts"] = int(
                self.connection.execute(
                    """SELECT COUNT(DISTINCT subject_id) FROM observations
                       WHERE subject_kind = 'post' AND event_type = ?""",
                    (event_type,),
                ).fetchone()[0]
            )
        return result

    def _initialize_search(self) -> str:
        try:
            self.connection.execute("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(value)")
            self.connection.execute("DROP TABLE temp.fts5_probe")
        except sqlite3.OperationalError:
            return "like"
        self.connection.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS post_search USING fts5(
                   post_id UNINDEXED, text_content, author_handle, author_name, author_bio
               )"""
        )
        return "fts5"

    def rebuild_search_index(self) -> None:
        if self.search_backend != "fts5":
            return
        with self.transaction():
            self.connection.execute("DELETE FROM post_search")
            self.connection.execute(
                """INSERT INTO post_search (
                       post_id, text_content, author_handle, author_name, author_bio
                   )
                   SELECT p.post_id, COALESCE(p.text_content, ''),
                          COALESCE((
                              SELECT s.handle
                              FROM post_participants pp
                              JOIN account_snapshots s ON s.account_id = pp.account_id
                              WHERE pp.post_id = p.post_id AND pp.role = 'author'
                              ORDER BY s.observed_at DESC, s.account_snapshot_id DESC LIMIT 1
                          ), ''),
                          COALESCE((
                              SELECT s.display_name
                              FROM post_participants pp
                              JOIN account_snapshots s ON s.account_id = pp.account_id
                              WHERE pp.post_id = p.post_id AND pp.role = 'author'
                              ORDER BY s.observed_at DESC, s.account_snapshot_id DESC LIMIT 1
                          ), ''),
                          COALESCE((
                              SELECT s.bio
                              FROM post_participants pp
                              JOIN account_snapshots s ON s.account_id = pp.account_id
                              WHERE pp.post_id = p.post_id AND pp.role = 'author'
                              ORDER BY s.observed_at DESC, s.account_snapshot_id DESC LIMIT 1
                          ), '')
                   FROM posts p"""
            )

    def search(
        self, query: str, *, event_type: str | None = None, backend: str | None = None
    ) -> dict[str, Any]:
        selected_backend = backend or self.search_backend
        if selected_backend not in {"fts5", "like"}:
            raise ValueError(f"unsupported search backend: {selected_backend}")
        if selected_backend == "fts5" and self.search_backend != "fts5":
            selected_backend = "like"
        parameters: list[object]
        event_clause = ""
        if event_type is not None:
            event_clause = (
                " AND EXISTS (SELECT 1 FROM observations o "
                "WHERE o.subject_kind = 'post' AND o.subject_id = p.post_id "
                "AND o.event_type = ?)"
            )
        if selected_backend == "fts5":
            self.rebuild_search_index()
            phrase = f'"{query.replace(chr(34), chr(34) * 2)}"'
            sql = (
                "SELECT p.platform_id, p.native_post_id, p.text_content "
                "FROM post_search s JOIN posts p ON p.post_id = s.post_id "
                "WHERE post_search MATCH ?" + event_clause + " ORDER BY p.post_id"
            )
            parameters = [phrase]
        else:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            sql = (
                "SELECT p.platform_id, p.native_post_id, p.text_content FROM posts p "
                "WHERE (COALESCE(p.text_content, '') LIKE ? ESCAPE '\\' "
                "OR EXISTS (SELECT 1 FROM post_participants pp "
                "JOIN account_snapshots s ON s.account_id = pp.account_id "
                "WHERE pp.post_id = p.post_id AND pp.role = 'author' "
                "AND (COALESCE(s.handle, '') LIKE ? ESCAPE '\\' "
                "OR COALESCE(s.display_name, '') LIKE ? ESCAPE '\\' "
                "OR COALESCE(s.bio, '') LIKE ? ESCAPE '\\')))"
                + event_clause
                + " ORDER BY p.post_id"
            )
            parameters = [pattern, pattern, pattern, pattern]
        if event_type is not None:
            parameters.append(event_type)
        rows = []
        for row in self.connection.execute(sql, parameters):
            platform_key = self.connection.execute(
                "SELECT platform_key FROM platforms WHERE platform_id = ?", (row["platform_id"],)
            ).fetchone()[0]
            rows.append(
                {
                    "post": f"{platform_key}:{row['native_post_id']}",
                    "text": row["text_content"],
                }
            )
        return {"search_backend": selected_backend, "results": rows}
