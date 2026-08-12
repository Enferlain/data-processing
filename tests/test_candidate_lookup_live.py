"""Optional one-request provider smoke test; disabled unless explicitly authorized."""

from __future__ import annotations

import os

import httpx
import pytest

from media_catalog.adapters import LookupQueryMaterial, LookupRequest, LookupStrategy
from media_catalog.adapters.danbooru import DANBOORU, DanbooruAdapter


@pytest.mark.skipif(
    os.environ.get("CATALOG_LIVE_LOOKUP") != "1",
    reason="set CATALOG_LIVE_LOOKUP=1 to authorize one public metadata request",
)
def test_live_danbooru_lookup_is_one_small_metadata_request() -> None:
    material = LookupQueryMaterial(
        LookupStrategy.SOURCE_POST_URL,
        "https://x.com/i/status/1",
    )
    with httpx.Client(timeout=15) as client:
        adapter = DanbooruAdapter(DANBOORU, client=client)
        response = adapter.fetch_lookup(
            LookupRequest(LookupStrategy.SOURCE_POST_URL, material, limit=1)
        )
    assert response.status_code in {200, 401, 403, 429}
    assert len(response.payload) <= 1_000_000
    assert response.headers.get("content-type", "").startswith("application/json")
