"""Per-provider expansion matrix: every registered capability pauses and resumes."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import load_fixture_suite
from media_catalog.adapters.danbooru import AIBOORU, DANBOORU, DanbooruAdapter
from media_catalog.adapters.e621 import E621, E621Adapter
from media_catalog.adapters.e621.config import ADAPTER_VERSION as E621_ADAPTER_VERSION
from media_catalog.adapters.e621.config import PROVIDER_KEY as E621_PROVIDER_KEY
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.database import CatalogDatabase
from media_catalog.library import (
    ArtistLibraryExpansionService,
    ExpansionLimits,
    plan_library_expansion,
)
from media_catalog.records import AccountRecord, AttributionRecord, TagObservationRecord
from media_catalog.writer import CatalogWriter

NOW = "2026-10-03T00:00:00Z"
FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
LIMITS = ExpansionLimits(requests=1, pages=2, records=20, seconds=60)


def _e621_first_page() -> list[dict[str, object]]:
    suite = load_fixture_suite(FIXTURES / "e621.json")
    case = next(case for case in suite.cases if case.name == "listing_first")
    body = json.loads(case.response.payload)
    assert isinstance(body, list)
    return body


class ProviderCase:
    """One registered expansion capability and its wire-level pause/resume shape."""

    def __init__(
        self,
        setup: Callable[[CatalogWriter], tuple[int, str]],
        adapter: Callable[[httpx.MockTransportHandler], object],
        handler: Callable[[httpx.Request], httpx.Response],
        expected_posts: tuple[str, ...],
        resume_marker: tuple[str, str],
    ) -> None:
        self.setup = setup
        self.adapter = adapter
        self.handler = handler
        self.expected_posts = expected_posts
        self.resume_marker = resume_marker


def _pixiv_setup(writer: CatalogWriter) -> tuple[int, str]:
    with writer.database.transaction():
        seed_id = writer.upsert_account(AccountRecord("x", "9001", NOW)).id
        target_id = writer.upsert_account(AccountRecord("pixiv", "1001", NOW)).id
    return seed_id, f"account:{target_id}"


def _pixiv_adapter(handler: httpx.MockTransportHandler) -> PixivAdapter:
    return PixivAdapter(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        refresh_token_env=None,
        clock=lambda: NOW,
    )


def _pixiv_handler(request: httpx.Request) -> httpx.Response:
    if request.url.params.get("offset") == "1":
        return httpx.Response(200, json={"illusts": [{"id": 2002}], "next_url": None})
    return httpx.Response(
        200,
        json={
            "illusts": [{"id": 2001}],
            "next_url": "https://app-api.pixiv.net/v1/user/illusts?user_id=1001&offset=1",
        },
    )


def _booru_setup(platform: str, attribution_id: str, primary_name: str, host: str):
    def setup(writer: CatalogWriter) -> tuple[int, str]:
        with writer.database.transaction():
            seed_id = writer.upsert_account(AccountRecord("x", "9100", NOW)).id
            target_id = writer.upsert_attribution(
                AttributionRecord(
                    platform,
                    attribution_id,
                    "danbooru-native-v1",
                    NOW,
                    instance_host=host,
                    primary_name=primary_name,
                )
            ).id
        return seed_id, f"attribution:{target_id}"

    return setup


def _danbooru_adapter(handler: httpx.MockTransportHandler) -> DanbooruAdapter:
    return DanbooruAdapter(DANBOORU, client=_client(handler), clock=lambda: NOW)


def _aibooru_adapter(handler: httpx.MockTransportHandler) -> DanbooruAdapter:
    return DanbooruAdapter(AIBOORU, client=_client(handler), clock=lambda: NOW)


def _e621_adapter(handler: httpx.MockTransportHandler) -> E621Adapter:
    return E621Adapter(E621, client=_client(handler), clock=lambda: NOW)


def _client(handler: httpx.MockTransportHandler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _keyset_handler(first_id: int) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == f"b{first_id}":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[{"id": first_id}])

    return handler


def _e621_setup(writer: CatalogWriter) -> tuple[int, str]:
    with writer.database.transaction():
        seed_id = writer.upsert_account(AccountRecord("x", "9200", NOW)).id
        target_id = writer.upsert_attribution(
            AttributionRecord(E621_PROVIDER_KEY, "tag:12345", E621_ADAPTER_VERSION, NOW)
        ).id
        writer.upsert_tag_record(
            TagObservationRecord(
                E621_PROVIDER_KEY,
                "artist",
                "artist_a",
                "artist_a",
                NOW,
                "provider-tag-v1",
                provider_tag_id="12345",
                native_category="artist",
                native_category_code=1,
            )
        )
    return seed_id, f"attribution:{target_id}"


def _e621_handler(request: httpx.Request) -> httpx.Response:
    if request.url.params.get("page") == "b5101":
        return httpx.Response(200, json=[])
    return httpx.Response(200, json=_e621_first_page())


CASES: dict[str, ProviderCase] = {
    "pixiv": ProviderCase(
        _pixiv_setup,
        _pixiv_adapter,
        _pixiv_handler,
        ("2001", "2002"),
        ("offset", "1"),
    ),
    "danbooru": ProviderCase(
        _booru_setup("danbooru", "44", "artist_a", "danbooru.donmai.us"),
        _danbooru_adapter,
        _keyset_handler(5001),
        ("5001",),
        ("page", "b5001"),
    ),
    "aibooru": ProviderCase(
        _booru_setup("aibooru", "55", "artist_b", "aibooru.online"),
        _aibooru_adapter,
        _keyset_handler(7001),
        ("7001",),
        ("page", "b7001"),
    ),
    "e621": ProviderCase(
        _e621_setup,
        _e621_adapter,
        _e621_handler,
        ("5101", "5102"),
        ("page", "b5101"),
    ),
}


@pytest.mark.parametrize("platform", sorted(CASES))
def test_every_registered_capability_pauses_and_resumes_from_its_continuation(
    tmp_path: Path, platform: str
) -> None:
    case = CASES[platform]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return case.handler(request)

    with CatalogDatabase(tmp_path / f"{platform}.sqlite3") as database:
        writer = CatalogWriter(database)
        seed_id, target_reference = case.setup(writer)

        def plan():
            return plan_library_expansion(
                database,
                f"account:{seed_id}",
                target=target_reference,
                selection_note=f"matrix selected the {platform} target",
                limits=LIMITS,
            )

        service = ArtistLibraryExpansionService(
            database,
            case.adapter(handler),
            minimum_interval_seconds=0,
            maximum_retries=0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        )
        first_plan = plan()
        first = service.run(first_plan)
        later = plan()
        assert later.digest == first_plan.digest
        second = service.resume(later, first.library_expansion_execution_id)
        posts = [
            row[0]
            for row in database.connection.execute(
                "SELECT native_post_id FROM posts ORDER BY native_post_id"
            ).fetchall()
        ]
        lineage = database.connection.execute(
            """SELECT execution_kind, predecessor_execution_id
                 FROM library_expansion_executions
                ORDER BY library_expansion_execution_id"""
        ).fetchall()

    assert first.sync.status == "paused", platform
    assert first.sync.budget_boundary == "request", platform
    assert second.sync.status == "complete", platform
    assert posts == sorted(case.expected_posts), platform
    assert tuple(lineage[0]) == ("initial", None), platform
    assert tuple(lineage[1]) == ("resume", first.library_expansion_execution_id), platform
    marker_name, marker_value = case.resume_marker
    assert len(requests) == 2, platform
    assert requests[1].url.params.get(marker_name) == marker_value, platform
