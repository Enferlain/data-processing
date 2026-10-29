from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import AdapterOperation, AdapterRequest, ResponseEnvelope
from media_catalog.adapters.fixtures import load_fixture_suite
from media_catalog.adapters.gelbooru import (
    ADAPTER_VERSION,
    GELBOORU,
    GELBOORU_INSTANCES,
    SAFEBOORU,
    SAFEBOORU_DAPI_SCHEMA_VERSION,
    GelbooruAdapter,
    GelbooruCredentials,
    GelbooruInstance,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
SUITE = load_fixture_suite(FIXTURES / "safebooru.json")
NOW = "2026-10-28T00:00:00Z"


def test_family_registry_and_instance_policy() -> None:
    assert set(GELBOORU_INSTANCES) == {"gelbooru", "safebooru"}
    assert GELBOORU_INSTANCES["safebooru"] is SAFEBOORU
    assert GELBOORU.dapi_credentials_required is True
    assert SAFEBOORU.dapi_credentials_required is False
    assert SAFEBOORU.dapi_schema_version == SAFEBOORU_DAPI_SCHEMA_VERSION


def test_instance_platform_keys_must_be_lowercase_slugs() -> None:
    with pytest.raises(ValueError, match="lowercase platform key"):
        GelbooruInstance(platform_key="Safebooru")


def test_captured_contract_normalizes_under_the_safebooru_identity() -> None:
    case = SUITE.cases[0]
    adapter = GelbooruAdapter(SAFEBOORU, client=httpx.Client())
    page = adapter.normalize(
        ResponseEnvelope(
            provider="gelbooru",
            instance="safebooru",
            operation=AdapterOperation.FETCH_POST,
            request_identity=case.request_identity,
            status_code=case.response.status_code,
            headers=dict(case.response.headers),
            payload=case.response.payload,
            observed_at=NOW,
            adapter_version=ADAPTER_VERSION,
            schema_version=SAFEBOORU_DAPI_SCHEMA_VERSION,
        )
    )
    expected = case.expected
    post = next(item for item in page.items if item.object_kind == "post")
    assert post.native_id == expected["post_ids"][0]
    # The captured safebooru contract declares no creation time and a null
    # score; both stay absent rather than being invented.
    assert post.data["created_at"] is None
    assert post.data["score"] is None
    assert post.data["rating"] == expected["rating"]
    assert post.data["source"] == expected["source"]
    occurrence = next(item for item in page.items if item.object_kind == "media_occurrence")
    # This engine generation exposes `hash`, not `md5`: no declared MD5 fact.
    assert occurrence.data["declared_md5"] is None
    assert (occurrence.data["width"], occurrence.data["height"]) == (
        expected["width"],
        expected["height"],
    )
    assert [variant["role"] for variant in occurrence.data["variants"]] == expected["variants"]
    tags = [item for item in page.items if item.object_kind == "post_tag"]
    assert len(tags) == expected["tag_count"]


def test_wire_request_is_anonymous_for_safebooru() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            stream=httpx.ByteStream(SUITE.cases[0].response.payload),
            headers={"content-type": "application/json"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GelbooruAdapter(SAFEBOORU, client=client)
    envelope = adapter.fetch(
        AdapterRequest(operation=AdapterOperation.FETCH_POST, target="7272295")
    )
    assert len(requests) == 1
    params = dict(requests[0].url.params)
    assert "user_id" not in params
    assert "api_key" not in params
    assert params["s"] == "post"
    assert params["id"] == "7272295"
    assert requests[0].url.host == "safebooru.org"
    assert envelope.schema_version == SAFEBOORU_DAPI_SCHEMA_VERSION
    assert envelope.instance == "safebooru"


def test_gelbooru_dapi_cli_selects_the_safebooru_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import media_catalog.cli as cli_module
    from media_catalog.cli import main
    from media_catalog.database import CatalogDatabase
    from media_catalog.remote_sync import SyncResult

    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass

    constructed: list[tuple[object, object]] = []

    class FakeDapiAdapter:
        adapter_version = "gelbooru-v1"
        schema_version = "safebooru-json-v1"
        instance_key = "safebooru"

        def __init__(self, instance: object, *, client: object, credentials: object) -> None:
            constructed.append((instance, credentials))

    class FakeService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def synchronize(self, *_args: object, **_kwargs: object) -> SyncResult:
            return SyncResult(
                remote_run_id=1,
                platform="safebooru",
                operation="fetch_post",
                target="7272295",
                status="complete",
                outcome="success",
                request_count=1,
                page_count=1,
                record_count=1,
                resumed_from_run_id=None,
            )

    monkeypatch.setattr(cli_module, "GelbooruAdapter", FakeDapiAdapter)
    monkeypatch.setattr(cli_module, "MetadataSyncService", FakeService)
    monkeypatch.delenv("SAFEBOORU_USER_ID", raising=False)
    monkeypatch.delenv("SAFEBOORU_API_KEY", raising=False)

    main(
        [
            "metadata",
            "gelbooru-dapi-post",
            str(catalog),
            "7272295",
            "--instance",
            "safebooru",
            "--json",
        ]
    )
    # Anonymous policy: no safebooru env vars configured, credentials None.
    assert constructed == [(SAFEBOORU, None)]


def test_gelbooru_still_refuses_credentialless_dapi_before_network() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    adapter = GelbooruAdapter(GELBOORU, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ValueError, match="DAPI requests require credentials"):
        adapter.fetch(AdapterRequest(operation=AdapterOperation.FETCH_POST, target="12370900"))
    assert calls == []


def test_optional_credentials_resolution() -> None:
    assert GelbooruCredentials.optional_from_environment(SAFEBOORU, {}) is None
    with pytest.raises(ValueError, match="configure both"):
        GelbooruCredentials.optional_from_environment(SAFEBOORU, {SAFEBOORU.user_id_env: "1"})
    pair = GelbooruCredentials.optional_from_environment(
        SAFEBOORU, {SAFEBOORU.user_id_env: "1", SAFEBOORU.api_key_env: "sentinel"}
    )
    assert pair is not None
    assert pair.secret_values() == ("1", "sentinel")


def test_notes_flow_parses_the_captured_empty_shape(tmp_path: Path) -> None:
    from media_catalog.database import CatalogDatabase
    from media_catalog.remote_sync.enrichment import fetch_notes

    class _SafebooruNotesAdapter:
        instance_key = "safebooru"
        adapter_version = "safebooru-test-v1"
        schema_version = "safebooru-json-v1"

        def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
            return ResponseEnvelope(
                provider="gelbooru",
                instance="safebooru",
                operation=request.operation,
                request_identity="safebooru:dapi_json:notes:7272295",
                status_code=200,
                headers={"content-type": "text/xml; charset=utf-8"},
                payload=(FIXTURES / "safebooru_notes_7272295.xml").read_bytes(),
                observed_at=NOW,
                adapter_version=self.adapter_version,
                schema_version=self.schema_version,
            )

    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        # The safebooru platform row comes from migration 0020; the retained
        # post is the enrichment precondition.
        platform_id = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'safebooru'"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)"
            " VALUES (?, '7272295', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (platform_id,),
        )
        connection.commit()
        report = fetch_notes(database, _SafebooruNotesAdapter(), "7272295", clock=lambda: NOW)
        assert report["outcome"] == "success"
        assert report["observations"] == 0


def test_safebooru_sync_persists_through_the_real_service(tmp_path: Path) -> None:
    from media_catalog.database import CatalogDatabase
    from media_catalog.remote_sync import MetadataSyncService, SyncLimits

    payload = SUITE.cases[0].response.payload

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=httpx.ByteStream(payload),
            headers={"content-type": "application/json"},
        )

    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database:
        adapter = GelbooruAdapter(
            SAFEBOORU, client=httpx.Client(transport=httpx.MockTransport(handler))
        )
        result = MetadataSyncService(database, adapter).synchronize(
            AdapterOperation.FETCH_POST, "7272295", limits=SyncLimits(1, 1, 100, 60)
        )
        assert (result.status, result.outcome) == ("complete", "success")
        row = database.connection.execute(
            "SELECT p.native_post_id, pl.platform_key FROM posts p"
            " JOIN platforms pl USING(platform_id)"
        ).fetchone()
        assert tuple(row) == ("7272295", "safebooru")
