from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from x_likes.archive import ArchivedLike
from x_likes.provider import PostMetadata

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    author_id TEXT PRIMARY KEY,
    handle TEXT,
    display_name TEXT,
    bio TEXT,
    profile_url TEXT,
    avatar_url TEXT,
    banner_url TEXT,
    location TEXT,
    website_url TEXT,
    followers INTEGER,
    following INTEGER,
    verified INTEGER,
    verification_type TEXT,
    fetched_at TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    post_id TEXT PRIMARY KEY,
    post_url TEXT NOT NULL,
    archive_text TEXT,
    author_id TEXT,
    author_handle TEXT,
    author_name TEXT,
    post_text TEXT,
    created_at TEXT,
    imported_at TEXT NOT NULL,
    fetched_at TEXT,
    fetch_provider TEXT,
    fetch_status TEXT NOT NULL DEFAULT 'pending',
    fetch_error TEXT,
    unavailable_reason TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS media (
    post_id TEXT NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    media_index INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    source_url TEXT NOT NULL,
    local_path TEXT,
    width INTEGER,
    height INTEGER,
    alt_text TEXT,
    file_size INTEGER,
    md5 TEXT,
    sha256 TEXT,
    phash TEXT,
    download_error TEXT,
    PRIMARY KEY (post_id, media_index)
);

CREATE INDEX IF NOT EXISTS posts_fetch_status_idx ON posts(fetch_status);
CREATE INDEX IF NOT EXISTS accounts_handle_idx ON accounts(handle);
CREATE INDEX IF NOT EXISTS media_sha256_idx ON media(sha256);
CREATE INDEX IF NOT EXISTS media_phash_idx ON media(phash);
"""


@dataclass(frozen=True, slots=True)
class PendingImage:
    post_id: str
    media_index: int
    source_url: str
    author_handle: str | None


class LikesDatabase:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> LikesDatabase:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def import_likes(self, likes: Iterable[ArchivedLike]) -> int:
        imported_at = _now()
        before = self.connection.total_changes
        with self.transaction():
            self.connection.executemany(
                """
                INSERT INTO posts (post_id, post_url, archive_text, imported_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(post_id) DO UPDATE SET
                    post_url = excluded.post_url,
                    archive_text = COALESCE(excluded.archive_text, posts.archive_text)
                """,
                ((like.post_id, like.post_url, like.archived_text, imported_at) for like in likes),
            )
        return self.connection.total_changes - before

    def posts_to_fetch(self, *, refresh: bool = False, limit: int | None = None) -> list[str]:
        where = "1 = 1" if refresh else "fetch_status IN ('pending', 'error')"
        sql = f"SELECT post_id FROM posts WHERE {where} ORDER BY CAST(post_id AS INTEGER)"
        parameters: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            parameters = (limit,)
        return [row["post_id"] for row in self.connection.execute(sql, parameters)]

    def save_metadata(self, metadata: PostMetadata, *, provider: str) -> None:
        with self.transaction():
            fetched_at = _now()
            if metadata.account is not None:
                account = metadata.account
                self.connection.execute(
                    """
                    INSERT INTO accounts (
                        author_id, handle, display_name, bio, profile_url, avatar_url,
                        banner_url, location, website_url, followers, following, verified,
                        verification_type, fetched_at, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(author_id) DO UPDATE SET
                        handle = excluded.handle,
                        display_name = excluded.display_name,
                        bio = excluded.bio,
                        profile_url = excluded.profile_url,
                        avatar_url = excluded.avatar_url,
                        banner_url = excluded.banner_url,
                        location = excluded.location,
                        website_url = excluded.website_url,
                        followers = excluded.followers,
                        following = excluded.following,
                        verified = excluded.verified,
                        verification_type = excluded.verification_type,
                        fetched_at = excluded.fetched_at,
                        raw_json = excluded.raw_json
                    """,
                    (
                        account.account_id,
                        account.handle,
                        account.display_name,
                        account.bio,
                        account.profile_url,
                        account.avatar_url,
                        account.banner_url,
                        account.location,
                        account.website_url,
                        account.followers,
                        account.following,
                        account.verified,
                        account.verification_type,
                        fetched_at,
                        json.dumps(account.raw, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
            self.connection.execute(
                """
                UPDATE posts SET
                    post_url = ?, author_id = ?, author_handle = ?, author_name = ?,
                    post_text = ?, created_at = ?, fetched_at = ?, fetch_provider = ?,
                    fetch_status = 'fetched', fetch_error = NULL, unavailable_reason = NULL,
                    raw_json = ?
                WHERE post_id = ?
                """,
                (
                    metadata.post_url,
                    metadata.author_id,
                    metadata.author_handle,
                    metadata.author_name,
                    metadata.text,
                    metadata.created_at,
                    fetched_at,
                    provider,
                    json.dumps(metadata.raw, ensure_ascii=False, separators=(",", ":")),
                    metadata.post_id,
                ),
            )
            self.connection.execute(
                "DELETE FROM media WHERE post_id = ? AND local_path IS NULL",
                (metadata.post_id,),
            )
            self.connection.executemany(
                """
                INSERT INTO media (
                    post_id, media_index, media_type, source_url, width, height, alt_text
                ) VALUES (?, ?, 'image', ?, ?, ?, ?)
                ON CONFLICT(post_id, media_index) DO UPDATE SET
                    source_url = CASE
                        WHEN media.local_path IS NULL THEN excluded.source_url
                        ELSE media.source_url
                    END,
                    width = excluded.width,
                    height = excluded.height,
                    alt_text = excluded.alt_text
                """,
                (
                    (
                        metadata.post_id,
                        image.index,
                        image.source_url,
                        image.width,
                        image.height,
                        image.alt_text,
                    )
                    for image in metadata.images
                ),
            )

    def save_fetch_error(
        self,
        post_id: str,
        error: str,
        *,
        status: str = "error",
        unavailable_reason: str | None = None,
        raw: dict[str, object] | None = None,
    ) -> None:
        with self.transaction():
            self.connection.execute(
                """
                UPDATE posts SET fetched_at = ?, fetch_provider = 'fxtwitter',
                    fetch_status = ?, fetch_error = ?, unavailable_reason = ?, raw_json = ?
                WHERE post_id = ?
                """,
                (
                    _now(),
                    status,
                    error,
                    unavailable_reason,
                    json.dumps(raw, ensure_ascii=False, separators=(",", ":")) if raw else None,
                    post_id,
                ),
            )

    def pending_images(self) -> list[PendingImage]:
        rows = self.connection.execute(
            """
            SELECT media.post_id, media.media_index, media.source_url, posts.author_handle
            FROM media JOIN posts USING (post_id)
            WHERE media.media_type = 'image' AND media.local_path IS NULL
            ORDER BY CAST(media.post_id AS INTEGER), media.media_index
            """
        )
        return [PendingImage(**dict(row)) for row in rows]

    def save_download(
        self,
        image: PendingImage,
        *,
        local_path: str,
        file_size: int,
        md5: str,
        sha256: str,
        phash: str,
    ) -> None:
        with self.transaction():
            self.connection.execute(
                """
                UPDATE media SET local_path = ?, file_size = ?, md5 = ?, sha256 = ?,
                    phash = ?, download_error = NULL
                WHERE post_id = ? AND media_index = ?
                """,
                (local_path, file_size, md5, sha256, phash, image.post_id, image.media_index),
            )

    def save_download_error(self, image: PendingImage, error: str) -> None:
        with self.transaction():
            self.connection.execute(
                """UPDATE media SET download_error = ? WHERE post_id = ? AND media_index = ?""",
                (error, image.post_id, image.media_index),
            )

    def summary(self) -> dict[str, int]:
        result = {
            "posts": self.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
            "accounts": self.connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
            "fetched": self.connection.execute(
                "SELECT COUNT(*) FROM posts WHERE fetch_status = 'fetched'"
            ).fetchone()[0],
            "fetch_errors": self.connection.execute(
                "SELECT COUNT(*) FROM posts WHERE fetch_status = 'error'"
            ).fetchone()[0],
            "unavailable": self.connection.execute(
                "SELECT COUNT(*) FROM posts WHERE fetch_status = 'unavailable'"
            ).fetchone()[0],
            "images": self.connection.execute("SELECT COUNT(*) FROM media").fetchone()[0],
            "downloaded": self.connection.execute(
                "SELECT COUNT(*) FROM media WHERE local_path IS NOT NULL"
            ).fetchone()[0],
        }
        return result


def _now() -> str:
    return datetime.now(UTC).isoformat()
