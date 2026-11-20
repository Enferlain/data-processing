"""Sankaku artist sweep (bead data-processing-hvs phase 2, change
add-sankaku-artist-sweep): ranked-name bulk listing with prior-run skipping
and budgets, plus the md5 overlap report."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest

from media_catalog.adapters import AdapterOperation
from media_catalog.database import CatalogDatabase
from media_catalog.remote_sync.artist_sweep import (
    md5_overlap_report,
    sweep_artists,
    swept_artist_names,
)

MD5_KNOWN = "0123456789abcdef0123456789abcdef"
MD5_NEW = "f" * 32


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database, database.transaction():
        connection = database.connection
        platform_ids = {}
        for key in ("gelbooru", "sankaku", "danbooru", "e621"):
            platform = connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = ?", (key,)
            ).fetchone()
            assert platform is not None
            platform_ids[key] = int(platform[0])
        # three alpha posts on gelbooru (artist source platform), two beta
        tag_ids: dict[str, int] = {}
        for artist in ("alpha_artist", "beta_artist", "rare"):
            tag = connection.execute(
                """INSERT INTO tags (platform_id, category, name, normalization_version)
                   VALUES (?, 'artist', ?, 'test-v1')""",
                (platform_ids["gelbooru"], artist),
            )
            tag_ids[artist] = int(tag.lastrowid)
        for native, artist in (
            ("g-1", "alpha_artist"),
            ("g-2", "alpha_artist"),
            ("g-3", "alpha_artist"),
            ("g-4", "beta_artist"),
            ("g-5", "beta_artist"),
        ):
            post = connection.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform_ids["gelbooru"], native),
            )
            connection.execute(
                """INSERT INTO post_tags (post_id, tag_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (int(post.lastrowid), tag_ids[artist]),
            )
        # gelbooru occurrence with the known md5 (overlap target)
        connection.execute(
            """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                                  media_type, declared_md5, observed_at)
               VALUES ((SELECT post_id FROM posts WHERE native_post_id='g-1'),
                       's:p', 0, 'image/png', ?, '2026-01-01T00:00:00Z')""",
            (MD5_KNOWN,),
        )
        # two sankaku posts: one md5 already known elsewhere, one new
        for native, md5 in (("s-1", MD5_KNOWN), ("s-2", MD5_NEW)):
            post = connection.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform_ids["sankaku"], native),
            )
            connection.execute(
                """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                                      media_type, declared_md5, observed_at)
                   VALUES (?, 's:p', 0, 'image/png', ?, '2026-01-01T00:00:00Z')""",
                (int(post.lastrowid), md5),
            )
    return path


def test_swept_artist_names_cross_platform_and_floored(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database, database.transaction():
        connection = database.connection
        # alpha also has one post on danbooru: held counts sum across platforms
        danbooru_platform = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
        ).fetchone()
        assert danbooru_platform is not None
        post = connection.execute(
            """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
               VALUES (?, 'd-1', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
            (int(danbooru_platform[0]),),
        )
        tag = connection.execute(
            """INSERT INTO tags (platform_id, category, name, normalization_version)
               VALUES (?, 'artist', 'alpha_artist', 'test-v1')""",
            (int(danbooru_platform[0]),),
        )
        connection.execute(
            """INSERT INTO post_tags (post_id, tag_id, first_seen_at, last_seen_at)
               VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
            (int(post.lastrowid), int(tag.lastrowid)),
        )
    with CatalogDatabase(catalog) as database:
        names = swept_artist_names(
            database.connection,
            limit=10,
            platform_keys=("gelbooru", "danbooru", "e621", "sankaku"),
        )
    # alpha (3+1=4 held across platforms); beta (2) never clears the floor
    assert names == [("alpha_artist", 4)]


def test_md5_overlap_report(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        report = md5_overlap_report(database.connection)
    assert report == {
        "sankaku_posts_with_md5": 2,
        "md5_known_elsewhere": 1,
        "md5_new_to_catalog": 1,
    }


class _FakeAdapter:
    instance_key = "sankaku"
    adapter_version = "test-v1"
    schema_version = "sankaku-v1"

    class _Instance:
        page_size = 50

    instance = _Instance()


class _FakeSyncResult:
    def __init__(self, requests: int, records: int) -> None:
        self._payload = {
            "status": "complete",
            "request_count": requests,
            "record_count": records,
        }

    def as_dict(self) -> dict[str, Any]:
        return self._payload


class _FakeService:
    calls: ClassVar[list[tuple[str, str]]] = []
    fail_for: ClassVar[set[str]] = set()

    def __init__(self, database, adapter, minimum_interval_seconds: float = 0.0) -> None:
        self.database = database
        self.adapter = adapter

    def synchronize(self, operation, target, *, limits, resume_from_run_id=None):
        assert operation is AdapterOperation.LIST_ACCOUNT_POSTS
        _FakeService.calls.append((operation.value, target))
        if target in _FakeService.fail_for:
            raise RuntimeError("boom")
        return _FakeSyncResult(requests=1, records=5)


class _NullClient:
    def __enter__(self) -> _NullClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_sweep_budgets_skips_and_fails_per_name(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import media_catalog.remote_sync.artist_sweep as sweep_module

    # widen the floor so both names rank
    monkeypatch.setattr(
        sweep_module,
        "swept_artist_names",
        lambda connection, *, limit, platform_keys: [
            ("alpha_artist", 3),
            ("beta_artist", 3),
            ("rare", 3),
        ],
    )
    monkeypatch.setattr(
        sweep_module,
        "MetadataSyncService",
        _FakeService,
    )
    _FakeService.calls.clear()
    _FakeService.fail_for = {"beta_artist"}
    with CatalogDatabase(catalog) as database:
        first = sweep_artists(
            database,
            lambda client: _FakeAdapter(),
            "sankaku",
            names_limit=10,
            request_budget=10,
            client_factory=_NullClient,
        )
    outcomes = {entry["artist"]: entry["outcome"] for entry in first["results"]}
    assert outcomes == {"alpha_artist": "complete", "beta_artist": "failed", "rare": "complete"}
    assert first["names_swept"] == 3
    assert first["md5_overlap"]["md5_new_to_catalog"] == 1


def test_sweep_strict_budget_stops_before_unfundable_name(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import media_catalog.remote_sync.artist_sweep as sweep_module

    monkeypatch.setattr(
        sweep_module,
        "swept_artist_names",
        lambda connection, *, limit, platform_keys: [
            ("alpha_artist", 3),
            ("beta_artist", 3),
        ],
    )
    monkeypatch.setattr(sweep_module, "MetadataSyncService", _FakeService)
    _FakeService.calls.clear()
    _FakeService.fail_for = set()
    with CatalogDatabase(catalog) as database:
        result = sweep_artists(
            database,
            lambda client: _FakeAdapter(),
            "sankaku",
            names_limit=10,
            request_budget=2,  # funds one name's reservation; the second stops
            pages_per_artist=2,
            client_factory=_NullClient,
        )
    assert [entry["artist"] for entry in result["results"]] == ["alpha_artist"]
    assert result["names_swept"] == 1


def test_sweep_skips_names_with_complete_prior_runs(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import media_catalog.remote_sync.artist_sweep as sweep_module

    with CatalogDatabase(catalog) as database:
        connection = database.connection
        sankaku_platform = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'sankaku'"
        ).fetchone()
        assert sankaku_platform is not None
        connection.execute(
            """INSERT INTO remote_runs (platform_id, operation, target,
                   adapter_version, schema_version, status, request_budget,
                   page_budget, record_budget, time_budget_seconds, started_at,
                   finished_at)
               VALUES (?, 'list_account_posts', 'alpha_artist', 't', 't',
                       'complete', 1, 1, 1, 60, '2026-01-01T00:00:00Z',
                       '2026-01-01T00:01:00Z')""",
            (int(sankaku_platform[0]),),
        )
        connection.commit()
    monkeypatch.setattr(
        sweep_module,
        "swept_artist_names",
        lambda connection, *, limit, platform_keys: [("alpha_artist", 3)],
    )
    monkeypatch.setattr(sweep_module, "MetadataSyncService", _FakeService)
    _FakeService.calls.clear()
    _FakeService.fail_for = set()
    with CatalogDatabase(catalog) as database:
        result = sweep_artists(
            database,
            lambda client: _FakeAdapter(),
            "sankaku",
            names_limit=10,
            request_budget=10,
            client_factory=_NullClient,
        )
    assert result["names_swept"] == 0
    assert result["names_skipped_already_swept"] == 1
    assert _FakeService.calls == []


def test_sweep_cli_dispatch(catalog: Path, capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    import media_catalog.remote_sync.artist_sweep as sweep_module
    from media_catalog.cli import main

    monkeypatch.setattr(
        sweep_module,
        "swept_artist_names",
        lambda connection, *, limit, platform_keys: [("alpha_artist", 3)],
    )
    monkeypatch.setattr(sweep_module, "MetadataSyncService", _FakeService)
    monkeypatch.setattr(
        "media_catalog.cli_commands.metadata.adapter_construction",
        lambda platform: (lambda client: _FakeAdapter(), 0.0),
    )
    _FakeService.calls.clear()
    _FakeService.fail_for = set()
    main(
        [
            "metadata",
            "sankaku-sweep",
            str(catalog),
            "--discover-names",
            "5",
            "--discover-requests",
            "5",
            "--no-interval",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["names_swept"] == 1
    assert payload["md5_overlap"]["md5_known_elsewhere"] == 1
