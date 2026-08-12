from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from media_catalog.acquisition.policies import (
    DANBOORU_MEDIA_POLICY,
    PIXIV_MEDIA_POLICY,
    MediaRequestPolicy,
)
from media_catalog.acquisition.transfer import (
    HTTPTransferEngine,
    TransferBudget,
    TransferLimits,
)
from media_catalog.storage.cas import AssetStorage, InspectionLimits

LIVE = os.getenv("MEDIA_CATALOG_LIVE_ACQUISITION") == "1"
MAX_BYTES = 32 * 1024 * 1024


def _live_download(
    tmp_path: Path,
    *,
    policy: MediaRequestPolicy,
    url_env: str,
) -> None:
    url = os.getenv(url_env)
    if not url:
        pytest.skip(f"live acquisition requires externally configured {url_env}")
    managed = tmp_path / "managed"
    managed.mkdir()
    recipe = policy.recipe(
        media_occurrence_id=1,
        variant_key="original",
        selected_url=url,
    )
    timeout = httpx.Timeout(10.0, read=20.0)
    with httpx.Client(timeout=timeout) as client, AssetStorage.for_remote(
        managed,
        limits=InspectionLimits(
            max_bytes=MAX_BYTES, max_pixels=100_000_000, max_frames=100
        ),
    ) as storage:
        result = HTTPTransferEngine(client).transfer(
            recipe,
            storage,
            limits=TransferLimits(MAX_BYTES, 1, 30, 2),
            budget=TransferBudget(MAX_BYTES),
        )
        assert result.complete
        assert 0 < result.received_bytes <= MAX_BYTES
        assert result.staged is not None
        inspection = storage.inspect_staged(result.staged)
        assert inspection.size == result.received_bytes
        relative_path, _created = storage.publish_staged(result.staged)
        assert (managed / relative_path).is_file()


@pytest.mark.skipif(
    not LIVE,
    reason="set MEDIA_CATALOG_LIVE_ACQUISITION=1 for live acquisition smoke",
)
def test_live_pixiv_image_is_policy_bound_and_hard_limited(tmp_path: Path) -> None:
    _live_download(
        tmp_path,
        policy=PIXIV_MEDIA_POLICY,
        url_env="MEDIA_CATALOG_LIVE_PIXIV_MEDIA_URL",
    )


@pytest.mark.skipif(
    not LIVE,
    reason="set MEDIA_CATALOG_LIVE_ACQUISITION=1 for live acquisition smoke",
)
def test_live_danbooru_image_is_policy_bound_and_hard_limited(tmp_path: Path) -> None:
    _live_download(
        tmp_path,
        policy=DANBOORU_MEDIA_POLICY,
        url_env="MEDIA_CATALOG_LIVE_DANBOORU_MEDIA_URL",
    )
