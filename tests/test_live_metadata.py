from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import AdapterOperation
from media_catalog.adapters.danbooru import DANBOORU, DanbooruAdapter
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.database import CatalogDatabase
from media_catalog.remote_sync import MetadataSyncService, SyncLimits

LIVE = os.getenv("MEDIA_CATALOG_LIVE_METADATA") == "1"


@pytest.mark.skipif(not LIVE, reason="set MEDIA_CATALOG_LIVE_METADATA=1 for live metadata smoke")
def test_live_danbooru_public_post_is_metadata_only(tmp_path: Path) -> None:
    with httpx.Client(timeout=20) as client, CatalogDatabase(
        tmp_path / "catalog.sqlite3"
    ) as database:
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
