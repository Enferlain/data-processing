from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from media_catalog.adapters import (
    AdapterOperation,
    AdapterRequest,
    Continuation,
    NormalizedItem,
    NormalizedPage,
    ResponseEnvelope,
    adapter_transport_identity,
    validate_transport_pair,
)
from media_catalog.database import CatalogDatabase, available_migrations, current_schema_version
from media_catalog.records import (
    RawRecord,
    RemoteCheckpointRecord,
    RemoteRequestRecord,
    RemoteRunRecord,
)
from media_catalog.remote_queries import get_remote_run
from media_catalog.remote_sync import MetadataSyncService, SyncLimits

NOW = "2026-08-14T00:00:00Z"


class _TransportAdapter:
    provider_key = "gelbooru"
    instance_key = "gelbooru"
    adapter_version = "gelbooru-native-v2"
    schema_version = "gelbooru-dapi-json-v1"

    def __init__(self, transport_key: str, transport_version: str, pages: list[NormalizedPage]):
        self.transport_key = transport_key
        self.transport_version = transport_version
        self.pages = pages
        self.fetch_count = 0
        self.requests: list[AdapterRequest] = []

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        self.fetch_count += 1
        self.requests.append(request)
        return ResponseEnvelope(
            provider=self.provider_key,
            instance=self.instance_key,
            operation=request.operation,
            request_identity=f"gelbooru:{self.transport_key}:{self.fetch_count}",
            status_code=200,
            headers={"content-type": "application/json"},
            payload=json.dumps({"page": self.fetch_count}).encode(),
            observed_at=NOW,
            adapter_version=self.adapter_version,
            schema_version=self.schema_version,
            transport_key=self.transport_key,
            transport_version=self.transport_version,
        )

    def normalize(self, _response: ResponseEnvelope) -> NormalizedPage:
        return self.pages[self.fetch_count - 1]


class _LegacyAdapter(_TransportAdapter):
    def __init__(self, pages: list[NormalizedPage]):
        super().__init__("unused", "unused-v1", pages)
        del self.transport_key
        del self.transport_version

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        self.fetch_count += 1
        self.requests.append(request)
        return ResponseEnvelope(
            provider=self.provider_key,
            instance=self.instance_key,
            operation=request.operation,
            request_identity=f"gelbooru:legacy:{self.fetch_count}",
            status_code=200,
            headers={"content-type": "application/json"},
            payload=b"{}",
            observed_at=NOW,
            adapter_version=self.adapter_version,
            schema_version=self.schema_version,
        )


def _page(native_id: str, continuation: Continuation | None = None) -> NormalizedPage:
    return NormalizedPage(
        (NormalizedItem("post", native_id, {"platform": "gelbooru", "native_id": native_id}),),
        continuation,
    )


def test_transport_pair_validation_is_optional_bounded_and_secret_free() -> None:
    assert validate_transport_pair(None, None) == (None, None)
    assert validate_transport_pair("dapi_json", "gelbooru-dapi-v1") == (
        "dapi_json",
        "gelbooru-dapi-v1",
    )
    with pytest.raises(ValueError, match="supplied together"):
        validate_transport_pair("dapi_json", None)
    with pytest.raises(ValueError, match="bounded"):
        validate_transport_pair("dapi_json", "x" * 201)
    with pytest.raises(ValueError, match="non-secret"):
        validate_transport_pair("https://gelbooru.com", "gelbooru-v1")
    with pytest.raises(ValueError, match="non-secret"):
        validate_transport_pair("dapi_json", "gelbooru-v1?api_key=secret")
    with pytest.raises(ValueError, match="non-secret"):
        validate_transport_pair("bearer_token_v1", "gelbooru-v1")
    with pytest.raises(ValueError, match="non-secret"):
        validate_transport_pair("dapi_json", "client-secret-v1")


def test_legacy_adapters_keep_null_transport_material_and_request_identity() -> None:
    adapter = _LegacyAdapter([_page("1")])
    assert adapter_transport_identity(adapter) == (None, None)
    request = AdapterRequest(AdapterOperation.FETCH_POST, "1")
    assert (request.transport_key, request.transport_version) == (None, None)
    assert request.target == "1"


def test_explicit_transport_is_copied_to_request_and_all_remote_provenance(
    tmp_path: Path,
) -> None:
    adapter = _TransportAdapter(
        "dapi_json",
        "gelbooru-dapi-v1",
        [_page("1", Continuation("gelbooru", "gelbooru-pid-v1", {"pid": 1}))],
    )
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        result = MetadataSyncService(
            database,
            adapter,
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        ).synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "1",
            limits=SyncLimits(1, 2, 10, 10),
        )
        assert result.status == "paused"
        assert adapter.requests[0].transport_key == "dapi_json"
        assert adapter.requests[0].transport_version == "gelbooru-dapi-v1"
        run = get_remote_run(database, result.remote_run_id)
        assert run is not None
        assert (run["transport_key"], run["transport_version"]) == (
            "dapi_json",
            "gelbooru-dapi-v1",
        )
        assert (run["requests"][0]["transport_key"], run["requests"][0]["transport_version"]) == (
            "dapi_json",
            "gelbooru-dapi-v1",
        )
        assert (
            run["checkpoints"][0]["transport_key"],
            run["checkpoints"][0]["transport_version"],
        ) == ("dapi_json", "gelbooru-dapi-v1")
        raw = database.connection.execute(
            "SELECT transport_key, transport_version FROM raw_observations"
        ).fetchone()
        assert tuple(raw) == ("dapi_json", "gelbooru-dapi-v1")


def test_explicit_transport_mismatch_rejects_resume_before_network(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    first = _TransportAdapter(
        "dapi_json",
        "gelbooru-dapi-v1",
        [_page("1", Continuation("gelbooru", "gelbooru-pid-v1", {"pid": 1}))],
    )
    with CatalogDatabase(path) as database:
        paused = MetadataSyncService(
            database,
            first,
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        ).synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "1",
            limits=SyncLimits(1, 2, 10, 10),
        )
        assert paused.status == "paused"
        mismatched = _TransportAdapter("html_post", "gelbooru-html-v1", [_page("2")])
        with pytest.raises(ValueError, match="incompatible"):
            MetadataSyncService(
                database,
                mismatched,
                minimum_interval_seconds=0,
                maximum_retries=0,
                monotonic=lambda: 0.0,
                sleep=lambda _seconds: None,
                clock=lambda: NOW,
            ).synchronize(
                AdapterOperation.LIST_ACCOUNT_POSTS,
                "1",
                limits=SyncLimits(1, 1, 10, 10),
                resume_from_run_id=paused.remote_run_id,
            )
        assert mismatched.fetch_count == 0


def test_transport_columns_upgrade_without_changing_ids_or_integrity(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with sqlite3.connect(path) as connection:
        for version, _name, sql in available_migrations()[:10]:
            connection.executescript(sql)
            connection.execute(f"PRAGMA user_version = {version}")
        platform_id = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'gelbooru'"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO posts (post_id, platform_id, native_post_id, first_seen_at, last_seen_at) "
            "VALUES (501, ?, '1', ?, ?)",
            (platform_id, NOW, NOW),
        )
        connection.commit()
    with CatalogDatabase(path) as database:
        assert database.schema_version == current_schema_version()
        assert database.connection.execute("SELECT post_id FROM posts").fetchone()[0] == 501
        assert database.doctor()["ok"] is True
        columns = {
            row["name"] for row in database.connection.execute("PRAGMA table_info(remote_runs)")
        }
        assert {"transport_key", "transport_version"} <= columns
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                """INSERT INTO remote_runs (
                       platform_id, operation, target, adapter_version, schema_version,
                       request_budget, page_budget, record_budget, time_budget_seconds,
                       started_at, transport_key
                   ) VALUES (
                       ?, 'fetch_post', '1', 'adapter-v1', 'schema-v1', 1, 1, 1, 1, ?, 'dapi_json'
                   )""",
                (platform_id, NOW),
            )


@pytest.mark.parametrize(
    "record",
    [
        lambda: RawRecord(b"x", "application/json", "post", "1", NOW, transport_key="x"),
        lambda: RemoteRunRecord(
            "gelbooru",
            "fetch_post",
            "1",
            "adapter-v1",
            "schema-v1",
            1,
            1,
            1,
            1,
            NOW,
            transport_version="v1",
        ),
        lambda: RemoteRequestRecord(
            1,
            1,
            "gelbooru:fetch_post:1",
            "fetch_post",
            "1",
            "success",
            NOW,
            transport_key="dapi_json",
        ),
        lambda: RemoteCheckpointRecord(
            1,
            "list_account_posts",
            "1",
            "gelbooru",
            "v1",
            '{"adapter":"gelbooru","version":"v1","value":{}}',
            NOW,
            transport_version="v1",
        ),
    ],
)
def test_persisted_records_require_transport_pairs(record) -> None:
    with pytest.raises(ValueError, match="supplied together"):
        record()
