from __future__ import annotations

import json
from pathlib import Path

from media_catalog.adapters import (
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    AdapterRequest,
    Continuation,
    NormalizedItem,
    NormalizedPage,
    ResponseEnvelope,
)
from media_catalog.database import CatalogDatabase
from media_catalog.remote_queries import get_remote_run, list_post_external_references
from media_catalog.remote_sync import MetadataSyncService, SyncLimits

NOW = "2026-08-10T00:00:00Z"


class FixtureAdapter:
    provider_key = "pixiv"
    instance_key = "pixiv"
    adapter_version = "fixture-adapter-v1"
    schema_version = "fixture-schema-v1"

    def __init__(
        self,
        pages: list[NormalizedPage],
        *,
        normalization_failure: bool = False,
    ) -> None:
        self.pages = pages
        self.normalization_failure = normalization_failure
        self.fetch_count = 0

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        self.fetch_count += 1
        payload = json.dumps({"page": self.fetch_count}).encode()
        return ResponseEnvelope(
            provider=self.provider_key,
            instance=self.instance_key,
            operation=request.operation,
            request_identity=f"pixiv:{request.operation.value}:{request.target}:{self.fetch_count}",
            status_code=200,
            headers={"content-type": "application/json"},
            payload=payload,
            observed_at=NOW,
            adapter_version=self.adapter_version,
            schema_version=self.schema_version,
        )

    def normalize(self, response: ResponseEnvelope) -> NormalizedPage:
        if self.normalization_failure:
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "fixture normalization failed")
        return self.pages[self.fetch_count - 1]


class FailingTransportAdapter(FixtureAdapter):
    def __init__(self, secret: str) -> None:
        super().__init__([])
        self._secret = secret

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        raise RuntimeError(f"transport rejected credential {self._secret}")


def _post(native_id: str, **extra: object) -> NormalizedItem:
    data: dict[str, object] = {
        "platform": "pixiv",
        "native_id": native_id,
        "availability": "available",
        "observation_time": NOW,
    }
    data.update(extra)
    return NormalizedItem("post", native_id, data)


def test_sync_retains_raw_then_atomically_persists_page_and_public_run(tmp_path: Path) -> None:
    page = NormalizedPage(
        (
            _post("10", title="Title"),
            NormalizedItem(
                "post_tag",
                "10:general:tag",
                {
                    "platform": "pixiv",
                    "post_id": "10",
                    "category": "general",
                    "normalized_name": "tag",
                    "spelling": "Tag",
                },
            ),
        )
    )
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        result = MetadataSyncService(
            database,
            FixtureAdapter([page]),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        ).synchronize(
            AdapterOperation.FETCH_POST,
            "10",
            limits=SyncLimits(1, 1, 10, 10),
        )
        assert result.status == "complete"
        assert (result.request_count, result.page_count, result.record_count) == (1, 1, 1)
        assert database.connection.execute("SELECT title FROM posts").fetchone()[0] == "Title"
        assert database.connection.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 1
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute("SELECT object_kind FROM raw_observations").fetchone()[0]
            == "post"
        )
        public = get_remote_run(database, result.remote_run_id)
        assert public is not None and public["status"] == "complete"
        assert "payload" not in public


def test_normalization_failure_retains_raw_without_normalized_state(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        result = MetadataSyncService(
            database,
            FixtureAdapter([], normalization_failure=True),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        ).synchronize(
            AdapterOperation.FETCH_POST,
            "10",
            limits=SyncLimits(1, 1, 10, 10),
        )
        assert result.outcome == "malformed_response"
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0]
            == 1
        )
        assert database.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
        assert (
            database.connection.execute("SELECT COUNT(*) FROM remote_checkpoints").fetchone()[0]
            == 0
        )


def test_oversized_page_pauses_without_partial_records_or_checkpoint(tmp_path: Path) -> None:
    page = NormalizedPage(tuple(_post(str(index)) for index in range(3)))
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        result = MetadataSyncService(
            database,
            FixtureAdapter([page]),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        ).synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "7",
            limits=SyncLimits(1, 1, 2, 10),
        )
        assert result.status == "paused"
        assert result.budget_boundary == "record"
        assert database.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
        assert (
            database.connection.execute("SELECT COUNT(*) FROM remote_checkpoints").fetchone()[0]
            == 0
        )


def test_listing_resume_uses_only_committed_compatible_checkpoint(tmp_path: Path) -> None:
    first = NormalizedPage(
        (_post("1"),), Continuation("pixiv", "fixture-schema-v1", {"offset": 1})
    )
    second = NormalizedPage((_post("2"),))
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        paused = MetadataSyncService(
            database,
            FixtureAdapter([first, second]),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        ).synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "7",
            limits=SyncLimits(1, 2, 10, 10),
        )
        assert paused.status == "paused" and paused.page_count == 1
        resumed_adapter = FixtureAdapter([second])
        resumed = MetadataSyncService(
            database,
            resumed_adapter,
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        ).synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "7",
            limits=SyncLimits(1, 1, 10, 10),
            resume_from_run_id=paused.remote_run_id,
        )
        assert resumed.status == "complete"
        assert resumed.resumed_from_run_id == paused.remote_run_id
        assert database.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 2


def test_external_evidence_and_directional_relations_are_persisted_idempotently(
    tmp_path: Path,
) -> None:
    page = NormalizedPage(
        (
            _post("10"),
            NormalizedItem(
                "external_reference",
                "10:source",
                {
                    "platform": "pixiv",
                    "post_id": "10",
                    "reference_kind": "source_url",
                    "value": "https://artist.example/post/10",
                },
            ),
            NormalizedItem(
                "external_reference",
                "10:pixiv:99",
                {
                    "platform": "pixiv",
                    "post_id": "10",
                    "target_platform": "pixiv",
                    "object_kind": "post",
                    "identifier_kind": "stable_id",
                    "native_identifier": "99",
                },
            ),
            NormalizedItem(
                "post_relation",
                "9:parent_of:10",
                {
                    "platform": "pixiv",
                    "source_post_id": "9",
                    "target_post_id": "10",
                    "relation_type": "parent_of",
                },
            ),
        )
    )
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        service = MetadataSyncService(
            database,
            FixtureAdapter([page]),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        )
        result = service.synchronize(
            AdapterOperation.FETCH_POST,
            "10",
            limits=SyncLimits(1, 1, 10, 10),
        )
        post_id = database.connection.execute(
            "SELECT post_id FROM posts WHERE native_post_id = '10'"
        ).fetchone()[0]
        references = list_post_external_references(database, post_id)
        assert len(references) == 2
        assert references[1]["target_native_identifier"] == "99"
        assert database.connection.execute("SELECT COUNT(*) FROM post_relations").fetchone()[0] == 1
        assert result.status == "complete"


def test_sentinel_credentials_do_not_enter_catalog_diagnostics_or_results(tmp_path: Path) -> None:
    sentinel = "credential-sentinel-do-not-store"
    path = tmp_path / "catalog.sqlite3"
    adapter = FailingTransportAdapter(sentinel)
    with CatalogDatabase(path) as database:
        result = MetadataSyncService(
            database,
            adapter,
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        ).synchronize(
            AdapterOperation.FETCH_POST,
            "10",
            limits=SyncLimits(1, 1, 10, 10),
        )
        assert result.status == "failed"
        assert result.outcome == "transient_provider"
        assert sentinel not in repr(result)
        assert sentinel not in json.dumps(result.as_dict())
        assert sentinel not in repr(get_remote_run(database, result.remote_run_id))
    assert sentinel.encode() not in path.read_bytes()
