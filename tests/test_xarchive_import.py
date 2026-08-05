from __future__ import annotations

import json
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.imports.xarchive import XArchiveError, import_xarchive


def _write_export(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "export_metadata": {"exported_at": "2026-08-05T00:00:00Z"},
                "folders": {},
                "bookmarks": [
                    {
                        "tweet_id": "42",
                        "full_text": "ocean light",
                        "created_at": "Wed Aug 05 00:00:00 +0000 2026",
                        "status": "available",
                        "folders": ["art"],
                        "author": {
                            "user_id": "7",
                            "screen_name": "user_7",
                            "name": "User 7",
                            "description": "watercolor artist",
                            "url": "https://artist.example",
                            "location": "Somewhere",
                        },
                        "media": [
                            {
                                "type": "video",
                                "url": "https://example.test/a.mp4",
                                "thumbnail_url": "https://example.test/a.jpg",
                                "duration_ms": 1200,
                                "variants": [{"bitrate": 1000, "url": "https://example.test/v"}],
                            },
                            {"type": "photo", "url": "https://example.test/b.jpg"},
                        ],
                        "in_reply_to_tweet_id": "40",
                        "quoted_tweet": {"tweet_id": "41"},
                        "unknown_future_field": {"retained": True},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_xarchive_import_is_conservative_complete_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "bookmarks.json"
    _write_export(source)
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        first = import_xarchive(database, source)
        second = import_xarchive(database, source)
        assert first.reused is False
        assert second.reused is True
        assert database.summary()["accounts"] == 1
        assert database.summary()["posts"] == 3
        assert database.summary()["observations"] == 1
        assert database.summary()["media_occurrences"] == 2
        snapshot = database.connection.execute(
            "SELECT handle, display_name, bio, website_url, location FROM account_snapshots"
        ).fetchone()
        assert tuple(snapshot) == (
            None,
            None,
            "watercolor artist",
            "https://artist.example",
            "Somewhere",
        )
        media = database.connection.execute(
            """SELECT preview_url, duration_ms, variants_json FROM media_occurrences
               WHERE media_index = 0"""
        ).fetchone()
        assert media["preview_url"] == "https://example.test/a.jpg"
        assert media["duration_ms"] == 1200
        assert json.loads(media["variants_json"])[0]["bitrate"] == 1000
        assert {
            row[0]
            for row in database.connection.execute("SELECT relation_type FROM post_relations")
        } == {"quote", "reply"}
        raw = json.loads(
            bytes(database.connection.execute("SELECT payload FROM raw_payloads").fetchone()[0])
        )
        assert raw["unknown_future_field"] == {"retained": True}
        assert database.stats(event_type="bookmarked")["matching_posts"] == 1
        assert database.stats(event_type="liked")["matching_posts"] == 0
        assert database.doctor()["ok"] is True


def test_malformed_xarchive_rolls_back_records_and_audits_failure(tmp_path: Path) -> None:
    source = tmp_path / "bad.json"
    source.write_text('{"bookmarks":[{}]}', encoding="utf-8")
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with pytest.raises(XArchiveError, match="missing tweet_id"):
            import_xarchive(database, source)
        assert database.summary()["posts"] == 0
        run = database.connection.execute("SELECT status FROM import_runs").fetchone()[0]
        assert run == "failed"
        assert (
            database.connection.execute("SELECT COUNT(*) FROM import_diagnostics").fetchone()[0]
            == 1
        )
        failed = database.connection.execute(
            """SELECT source_count, failed_count FROM import_run_counts
               WHERE entity_kind = 'posts'"""
        ).fetchone()
        assert tuple(failed) == (1, 1)


def test_overlapping_export_reports_real_outcomes_and_retains_folder_history(
    tmp_path: Path,
) -> None:
    source = tmp_path / "bookmarks.json"
    _write_export(source)
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        import_xarchive(database, source)
        root = json.loads(source.read_text(encoding="utf-8"))
        root["export_metadata"]["exported_at"] = "2026-08-06T00:00:00Z"
        root["bookmarks"][0]["folders"] = ["favorites"]
        root["bookmarks"][0]["media"][0]["thumbnail_url"] = "https://example.test/new.jpg"
        root["bookmarks"].append(
            {
                "tweet_id": "43",
                "full_text": "new bookmark",
                "status": "available",
                "author": {"user_id": "8", "screen_name": "real_handle", "name": "Artist"},
                "media": [],
            }
        )
        source.write_text(json.dumps(root), encoding="utf-8")

        report = import_xarchive(database, source)
        assert report.counts["posts"]["inserted"] == 1
        assert report.counts["posts"]["existing"] == 1
        assert report.counts["observations"]["inserted"] == 1
        assert report.counts["observations"]["updated"] == 1
        assert report.counts["media_occurrences"]["updated"] == 1
        assert report.counts["media_occurrences"]["existing"] == 1
        assert (
            database.connection.execute("SELECT COUNT(*) FROM observation_revisions").fetchone()[0]
            == 3
        )
        revisions = [
            json.loads(row[0])
            for row in database.connection.execute(
                """SELECT collection_data FROM observation_revisions
                   WHERE collection_data IS NOT NULL ORDER BY observation_revision_id"""
            )
        ]
        assert revisions == [["art"], ["favorites"]]


def test_present_invalid_created_at_fails_with_indexed_diagnostic(tmp_path: Path) -> None:
    source = tmp_path / "bad-date.json"
    _write_export(source)
    root = json.loads(source.read_text(encoding="utf-8"))
    root["bookmarks"][0]["created_at"] = "not-a-date"
    source.write_text(json.dumps(root), encoding="utf-8")
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with pytest.raises(XArchiveError, match=r"bookmark\[0\]\.created_at"):
            import_xarchive(database, source)
        assert database.summary()["posts"] == 0
