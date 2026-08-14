"""Opt-in metadata-only provider smoke tests.

The e621 checks are skipped unless the caller explicitly supplies all of
``MEDIA_CATALOG_LIVE_E621_METADATA=1``,
``MEDIA_CATALOG_LIVE_E621_BASE_URL=https://e621.net``,
``MEDIA_CATALOG_LIVE_E621_POST_ID=<public-post-id>``, and
``MEDIA_CATALOG_LIVE_E621_TAG=<bounded-tag>``.  ``E621_USERNAME`` and
``E621_API_KEY`` are optional external credentials; they are used only for
ephemeral Basic authentication.  The tests issue bounded JSON metadata requests,
record contacted hosts, and never request returned media URLs or bytes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from media_catalog.adapters import AdapterOperation
from media_catalog.adapters.danbooru import DANBOORU, DanbooruAdapter
from media_catalog.adapters.e621 import E621Adapter, E621Credentials, E621Instance
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.database import CatalogDatabase
from media_catalog.remote_sync import MetadataSyncService, SyncLimits

LIVE = os.getenv("MEDIA_CATALOG_LIVE_METADATA") == "1"
E621_LIVE = os.getenv("MEDIA_CATALOG_LIVE_E621_METADATA") == "1"
E621_LIVE_BASE_URL = os.getenv("MEDIA_CATALOG_LIVE_E621_BASE_URL")
E621_LIVE_POST_ID = os.getenv("MEDIA_CATALOG_LIVE_E621_POST_ID")
E621_LIVE_TAG = os.getenv("MEDIA_CATALOG_LIVE_E621_TAG")

E621_POST_LIMITS = SyncLimits(requests=1, pages=1, records=100, elapsed_seconds=15)
E621_TAG_LIMITS = SyncLimits(requests=1, pages=1, records=1, elapsed_seconds=15)


def _live_e621_setup(*, page_size: int) -> tuple[E621Instance, E621Credentials | None]:
    if not E621_LIVE:
        pytest.skip("set MEDIA_CATALOG_LIVE_E621_METADATA=1 for e621 live metadata smoke")
    if not E621_LIVE_BASE_URL:
        pytest.skip(
            "set MEDIA_CATALOG_LIVE_E621_BASE_URL to an explicit canonical e621 API endpoint"
        )
    try:
        instance = E621Instance(base_url=E621_LIVE_BASE_URL, page_size=page_size)
        credentials = E621Credentials.from_environment(instance)
    except ValueError as error:
        pytest.skip(f"e621 live network or credential configuration is incomplete: {error}")
    return instance, credentials


def _returned_media_hosts(database: CatalogDatabase) -> set[str]:
    hosts: set[str] = set()
    rows = database.connection.execute("SELECT payload FROM raw_payloads").fetchall()
    for row in rows:
        body = json.loads(row[0])
        posts = body if isinstance(body, list) else [body]
        for post in posts:
            if not isinstance(post, dict):
                continue
            nested = post.get("post")
            if isinstance(nested, dict):
                post = nested
            for field in ("file", "sample", "preview"):
                variant = post.get(field)
                if not isinstance(variant, dict):
                    continue
                url = variant.get("url")
                if isinstance(url, str):
                    host = urlsplit(url).hostname
                    if host:
                        hosts.add(host.lower())
    return hosts


def _assert_e621_metadata_only(
    database: CatalogDatabase,
    contacted_hosts: set[str],
    request_paths: list[str],
    instance: E621Instance,
) -> None:
    assert contacted_hosts == {instance.host.lower()}
    assert all(path.endswith(".json") for path in request_paths)
    assert contacted_hosts.isdisjoint(_returned_media_hosts(database))
    assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0


@pytest.mark.skipif(not LIVE, reason="set MEDIA_CATALOG_LIVE_METADATA=1 for live metadata smoke")
def test_live_danbooru_public_post_is_metadata_only(tmp_path: Path) -> None:
    with (
        httpx.Client(timeout=20) as client,
        CatalogDatabase(tmp_path / "catalog.sqlite3") as database,
    ):
        result = MetadataSyncService(
            database,
            DanbooruAdapter(DANBOORU, client=client),
            minimum_interval_seconds=DANBOORU.minimum_interval_seconds,
        ).synchronize(
            AdapterOperation.FETCH_POST,
            "9714844",
            limits=SyncLimits(1, 1, 50, 30),
        )
        assert result.request_count == 1
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0


@pytest.mark.skipif(not LIVE, reason="set MEDIA_CATALOG_LIVE_METADATA=1 for live metadata smoke")
def test_live_pixiv_public_artwork_is_bounded_and_metadata_only(tmp_path: Path) -> None:
    required = ("PIXIV_REFRESH_TOKEN", "PIXIV_CLIENT_ID", "PIXIV_CLIENT_SECRET")
    if not all(os.getenv(name) for name in required):
        pytest.skip("Pixiv live smoke requires external refresh and app credentials")
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database, PixivAdapter() as adapter:
        result = MetadataSyncService(database, adapter).synchronize(
            AdapterOperation.FETCH_POST,
            "133416234",
            limits=SyncLimits(1, 1, 50, 30),
        )
        assert result.request_count == 1
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0


@pytest.mark.skipif(
    not E621_LIVE,
    reason="set MEDIA_CATALOG_LIVE_E621_METADATA=1 for e621 live metadata smoke",
)
def test_live_e621_public_post_is_bounded_metadata_only(tmp_path: Path) -> None:
    if not E621_LIVE_POST_ID:
        pytest.skip("set MEDIA_CATALOG_LIVE_E621_POST_ID to a public post ID")
    instance, credentials = _live_e621_setup(page_size=1)
    contacted_hosts: set[str] = set()
    request_paths: list[str] = []

    def record_request(request: httpx.Request) -> None:
        contacted_hosts.add(request.url.host.lower())
        request_paths.append(request.url.path)
        assert request.headers["user-agent"] == instance.user_agent
        assert not request.headers["user-agent"].lower().startswith("mozilla/")

    with (
        httpx.Client(
            timeout=httpx.Timeout(10.0),
            event_hooks={"request": [record_request]},
        ) as client,
        CatalogDatabase(tmp_path / "catalog.sqlite3") as database,
    ):
        result = MetadataSyncService(
            database,
            E621Adapter(instance, client=client, credentials=credentials),
            minimum_interval_seconds=instance.minimum_interval_seconds,
        ).synchronize(
            AdapterOperation.FETCH_POST,
            E621_LIVE_POST_ID,
            limits=E621_POST_LIMITS,
        )
        assert result.request_count <= E621_POST_LIMITS.requests
        assert result.page_count <= E621_POST_LIMITS.pages
        assert result.record_count <= E621_POST_LIMITS.records
        _assert_e621_metadata_only(database, contacted_hosts, request_paths, instance)


@pytest.mark.skipif(
    not E621_LIVE,
    reason="set MEDIA_CATALOG_LIVE_E621_METADATA=1 for e621 live metadata smoke",
)
def test_live_e621_tag_metadata_is_bounded_metadata_only(tmp_path: Path) -> None:
    if not E621_LIVE_TAG:
        pytest.skip("set MEDIA_CATALOG_LIVE_E621_TAG to a bounded artist/tag query")
    instance, credentials = _live_e621_setup(page_size=1)
    contacted_hosts: set[str] = set()
    request_paths: list[str] = []

    def record_request(request: httpx.Request) -> None:
        contacted_hosts.add(request.url.host.lower())
        request_paths.append(request.url.path)
        assert request.headers["user-agent"] == instance.user_agent
        assert not request.headers["user-agent"].lower().startswith("mozilla/")

    with (
        httpx.Client(
            timeout=httpx.Timeout(10.0),
            event_hooks={"request": [record_request]},
        ) as client,
        CatalogDatabase(tmp_path / "catalog.sqlite3") as database,
    ):
        result = MetadataSyncService(
            database,
            E621Adapter(instance, client=client, credentials=credentials),
            minimum_interval_seconds=instance.minimum_interval_seconds,
        ).synchronize(
            AdapterOperation.FETCH_TAG,
            E621_LIVE_TAG,
            limits=E621_TAG_LIMITS,
        )
        assert result.request_count <= E621_TAG_LIMITS.requests
        assert result.page_count <= E621_TAG_LIMITS.pages
        assert result.record_count <= E621_TAG_LIMITS.records
        _assert_e621_metadata_only(database, contacted_hosts, request_paths, instance)
