from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import AdapterOperation
from media_catalog.adapters.danbooru import AIBOORU, DANBOORU, DanbooruAdapter
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.database import CatalogDatabase
from media_catalog.library import LibraryCountProbeService, plan_library_expansion
from media_catalog.records import AccountRecord, AttributionRecord
from media_catalog.writer import CatalogWriter

NOW = "2026-08-12T20:00:00Z"


def _pixiv_plan(database: CatalogDatabase):
    writer = CatalogWriter(database)
    with database.transaction():
        account_id = writer.upsert_account(AccountRecord("pixiv", "1001", NOW)).id
    return plan_library_expansion(database, f"account:{account_id}")


def _adapter(handler: Callable[[httpx.Request], httpx.Response]) -> PixivAdapter:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return PixivAdapter(client, refresh_token_env=None, clock=lambda: NOW)


def test_provider_enumeration_capabilities_are_typed_and_fail_closed() -> None:
    pixiv = PixivAdapter(transport=httpx.MockTransport(lambda _request: httpx.Response(500)))
    danbooru = DanbooruAdapter(
        DANBOORU,
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(500))),
    )
    aibooru = DanbooruAdapter(
        AIBOORU,
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(500))),
    )
    try:
        pixiv_capability = pixiv.enumeration_capabilities.for_target("account")
        assert pixiv_capability is not None
        assert pixiv_capability.operation is AdapterOperation.LIST_ACCOUNT_POSTS
        assert pixiv_capability.count_probe_key == "pixiv-account-count"
        assert pixiv.enumeration_capabilities.for_target("attribution") is None
        assert danbooru.enumeration_capabilities.supports("attribution") is True
        assert danbooru.enumeration_capabilities.supports("account") is False
        assert aibooru.enumeration_capabilities.supports("attribution") is True
    finally:
        pixiv.close()
        danbooru._client.close()
        aibooru._client.close()


def test_pixiv_count_probe_makes_one_profile_request_and_retains_raw(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"user": {"id": 1001}, "profile": {"total_illusts": 37}},
        )

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        plan = _pixiv_plan(database)
        adapter = _adapter(handler)
        try:
            result = LibraryCountProbeService(
                database, pixiv_adapter=adapter, clock=lambda: NOW
            ).probe(plan)
        finally:
            adapter.close()
        raw = database.connection.execute(
            """SELECT payload FROM raw_payloads rp JOIN raw_observations ro USING(raw_payload_id)
                WHERE ro.raw_observation_id = ?""",
            (result.raw_observation_id,),
        ).fetchone()[0]

    assert result.outcome == "success"
    assert result.count == 37
    assert result.request_count == 1
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/user/detail"
    assert dict(requests[0].url.params) == {"user_id": "1001"}
    assert b'total_illusts":37' in bytes(raw).replace(b" ", b"")
    assert "/user/illusts" not in str(requests[0].url)


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (401, "authentication_required"),
        (403, "authorization_denied"),
        (404, "unavailable"),
        (410, "deleted"),
        (429, "rate_limited"),
        (503, "transient_provider"),
    ],
)
def test_pixiv_probe_retains_typed_http_failures(tmp_path: Path, status: int, outcome: str) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": "redacted fixture"})

    with CatalogDatabase(tmp_path / f"catalog-{status}.sqlite3") as database:
        plan = _pixiv_plan(database)
        adapter = _adapter(handler)
        try:
            result = LibraryCountProbeService(
                database, pixiv_adapter=adapter, clock=lambda: NOW
            ).probe(plan)
        finally:
            adapter.close()

    assert result.outcome == outcome
    assert result.count is None
    assert result.raw_observation_id is not None
    assert calls == 1


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        json.dumps({"profile": {}}).encode(),
        json.dumps({"profile": {"total_illusts": True}}).encode(),
        json.dumps({"profile": {"total_illusts": 1.5}}).encode(),
        json.dumps({"profile": {"total_illusts": -1}}).encode(),
    ],
)
def test_pixiv_probe_rejects_malformed_counts_and_retains_response(
    tmp_path: Path, payload: bytes
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        plan = _pixiv_plan(database)
        adapter = _adapter(
            lambda _request: httpx.Response(
                200, content=payload, headers={"content-type": "application/json"}
            )
        )
        try:
            result = LibraryCountProbeService(
                database, pixiv_adapter=adapter, clock=lambda: NOW
            ).probe(plan)
        finally:
            adapter.close()

    assert result.outcome == "malformed_response"
    assert result.count is None
    assert result.raw_observation_id is not None
    assert result.request_count == 1


def test_booru_count_probe_is_unsupported_without_transport_use(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = writer.upsert_account(AccountRecord("x", "9001", NOW)).id
            attribution_id = writer.upsert_attribution(
                AttributionRecord(
                    "danbooru",
                    "44",
                    "danbooru-adapter-v1",
                    NOW,
                    primary_name="artist_a",
                )
            ).id
        plan = plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"attribution:{attribution_id}",
            selection_note="operator selected provider attribution",
        )

        result = LibraryCountProbeService(database, clock=lambda: NOW).probe(plan)

    assert result.outcome == "unsupported"
    assert result.request_count == 0
    assert result.raw_observation_id is None


def test_planned_capability_versions_match_the_live_adapters(tmp_path: Path) -> None:
    """A planned target's capability versions must equal the live adapter's so the
    execution service's adapter/schema checks never reject a fresh current plan.

    Regression for capability version strings drifting from the adapter constants
    (a mismatched adapter_version made every booru attribution run fail closed)."""

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            pixiv_account_id = writer.upsert_account(AccountRecord("pixiv", "1001", NOW)).id
            seed_id = writer.upsert_account(AccountRecord("x", "9001", NOW)).id
            danbooru_id = writer.upsert_attribution(
                AttributionRecord(
                    "danbooru",
                    "44",
                    "danbooru-adapter-v1",
                    NOW,
                    primary_name="artist_a",
                )
            ).id
            aibooru_id = writer.upsert_attribution(
                AttributionRecord(
                    "aibooru",
                    "45",
                    "danbooru-adapter-v1",
                    NOW,
                    primary_name="artist_b",
                )
            ).id
        pixiv_plan = plan_library_expansion(database, f"account:{pixiv_account_id}")
        danbooru_plan = plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"attribution:{danbooru_id}",
            selection_note="operator selected danbooru attribution",
        )
        aibooru_plan = plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"attribution:{aibooru_id}",
            selection_note="operator selected aibooru attribution",
        )

    pixiv = PixivAdapter(transport=httpx.MockTransport(lambda _request: httpx.Response(500)))
    danbooru = DanbooruAdapter(
        DANBOORU,
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(500))),
    )
    aibooru = DanbooruAdapter(
        AIBOORU,
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(500))),
    )
    try:
        assert pixiv_plan.selected is not None
        pixiv_capability = pixiv_plan.selected.target.capability
        assert pixiv_capability.adapter_version == pixiv.adapter_version
        assert pixiv_capability.schema_version == pixiv.schema_version

        assert danbooru_plan.selected is not None
        danbooru_capability = danbooru_plan.selected.target.capability
        assert danbooru_capability.adapter_version == danbooru.adapter_version
        assert danbooru_capability.schema_version == danbooru.schema_version

        assert aibooru_plan.selected is not None
        aibooru_capability = aibooru_plan.selected.target.capability
        assert aibooru_capability.adapter_version == aibooru.adapter_version
        assert aibooru_capability.schema_version == aibooru.schema_version
    finally:
        pixiv.close()
        danbooru._client.close()
        aibooru._client.close()
