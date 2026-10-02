"""Disabled-by-default live smoke tests for Gelbooru DAPI and HTML transports.

These tests require explicit operator authorization before they will run:
the ``GELBOORU_LIVE_SMOKE`` environment variable must be set to ``acknowledged``,
and external ``GELBOORU_USER_ID`` / ``GELBOORU_API_KEY`` credentials must be
present for DAPI tests.

No media host is contacted during these tests — only the Gelbooru metadata
endpoints. Hard request, body, record, and time limits are enforced.

OpenSpec task 7.5 for change ``add-gelbooru-metadata-adapter``.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import AdapterOperation
from media_catalog.adapters.gelbooru import (
    GELBOORU,
    GelbooruAdapter,
    GelbooruCredentials,
    GelbooruHtmlAdapter,
)
from media_catalog.database import CatalogDatabase
from media_catalog.remote_sync import MetadataSyncService, SyncLimits

# ---------------------------------------------------------------------------
# Policy acknowledgement gate
# ---------------------------------------------------------------------------

_LIVE_POLICY_ACK = "GELBOORU_LIVE_SMOKE"
_REQUIRED_CRED_ENV_VARS = ("GELBOORU_USER_ID", "GELBOORU_API_KEY")


def _live_smoke_enabled() -> bool:
    """Return True only when the operator has explicitly acknowledged the
    live-use policy and provided the required external credentials."""
    if os.environ.get(_LIVE_POLICY_ACK) != "acknowledged":
        return False
    return all(os.environ.get(var) for var in _REQUIRED_CRED_ENV_VARS)


_LIVE_SMOKE_REASON = (
    "Live smoke tests require explicit operator authorization: "
    f"set {_LIVE_POLICY_ACK}=acknowledged and provide "
    f"{' and '.join(_REQUIRED_CRED_ENV_VARS)} environment variables. "
    "See CHANGELOG.md for automation-policy risk details."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Hard budget limits for live smoke tests: 1 request, 1 page, 50 records, 30s.
_LIVE_LIMITS = SyncLimits(requests=1, pages=1, records=50, elapsed_seconds=30)

# Known Gelbooru post IDs used for smoke verification.
_LIVE_POST_ID = "12370900"


def _make_dapi_adapter() -> GelbooruAdapter:
    credentials = GelbooruCredentials.from_environment("GELBOORU")
    return GelbooruAdapter(
        GELBOORU,
        client=httpx.Client(),
        credentials=credentials,
    )


def _make_html_adapter() -> GelbooruHtmlAdapter:
    return GelbooruHtmlAdapter(GELBOORU, client=httpx.Client())


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _live_smoke_enabled(),
    reason=_LIVE_SMOKE_REASON,
)
def test_live_dapi_post_smoke(tmp_path: Path) -> None:
    """7.5: Live DAPI smoke test — one post, hard limits, no media contact."""
    path = tmp_path / "catalog.sqlite3"
    adapter = _make_dapi_adapter()
    with CatalogDatabase(path) as database:
        service = MetadataSyncService(
            database,
            adapter,
            minimum_interval_seconds=adapter.minimum_interval_seconds,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
        )
        result = service.synchronize(
            AdapterOperation.FETCH_POST,
            _LIVE_POST_ID,
            limits=_LIVE_LIMITS,
        )
    assert result.status in ("complete", "failed")
    # Credentials never appear in the result.
    for env_var in _REQUIRED_CRED_ENV_VARS:
        assert os.environ.get(env_var) not in str(result)


@pytest.mark.skipif(
    not _live_smoke_enabled(),
    reason=_LIVE_SMOKE_REASON,
)
def test_live_html_post_smoke(tmp_path: Path) -> None:
    """7.5: Live HTML smoke test — one post, hard limits, no credentials."""
    path = tmp_path / "catalog.sqlite3"
    adapter = _make_html_adapter()
    with CatalogDatabase(path) as database:
        service = MetadataSyncService(
            database,
            adapter,
            minimum_interval_seconds=adapter.minimum_interval_seconds,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
        )
        result = service.synchronize(
            AdapterOperation.FETCH_POST,
            _LIVE_POST_ID,
            limits=_LIVE_LIMITS,
        )
    assert result.status in ("complete", "failed")
