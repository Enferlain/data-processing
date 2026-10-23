"""Danbooru-family pool collection tests (OpenSpec add-danbooru-pool-collection).

A single pool fetch lands one ordered pool observation: members keep their
provider-declared positions and native ids, posts link only when already
retained, unchanged pools re-observe idempotently by digest, reorderings land
as new observations, and nothing creates a work-grouping conclusion.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from media_catalog.adapters import AdapterOperation, AdapterRequest, ResponseEnvelope
from media_catalog.adapters.danbooru.adapter import DanbooruAdapter
from media_catalog.adapters.danbooru.config import DANBOORU
from media_catalog.database import CatalogDatabase
from media_catalog.remote_sync.pools import fetch_pool

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
POOL_ID = "17001"
MEMBERS = [
    "4478170",
    "4478171",
    "4478172",
    "4478173",
    "4478174",
    "4478175",
    "4478176",
    "4478177",
    "4478178",
    "4478179",
]
RETAINED = {"4478170", "4478172"}


class _StubAdapter:
    """Transport-shaped stand-in returning a fixed response envelope."""

    def __init__(self, *, payload: bytes, status_code: int = 200) -> None:
        self.instance_key = "danbooru"
        self.adapter_version = "test-v1"
        self.schema_version = "test-v1"
        self._payload = payload
        self._status = status_code

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        assert request.operation is AdapterOperation.FETCH_POOL
        return ResponseEnvelope(
            provider="danbooru",
            instance="danbooru",
            operation=request.operation,
            request_identity="danbooru:fetch_pool:" + POOL_ID,
            status_code=self._status,
            headers={"content-type": "application/json"},
            payload=self._payload,
            observed_at="2026-10-23T07:00:00Z",
            adapter_version="test-v1",
            schema_version="test-v1",
        )


def _catalog(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        connection.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name) "
            "VALUES ('danbooru', 'Danbooru')"
        )
        platform = int(
            connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
            ).fetchone()[0]
        )
        for native in RETAINED:
            connection.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform, native),
            )
        connection.commit()


def _pool_payload(name: str = f"danbooru_pool_{POOL_ID}.json") -> bytes:
    return (FIXTURES / name).read_bytes()


def test_pool_fetch_records_ordered_membership(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _catalog(catalog)
    with CatalogDatabase(catalog) as database:
        report = fetch_pool(
            database,
            _StubAdapter(payload=_pool_payload()),
            17001,
            clock=lambda: "2026-10-23T07:00:00Z",
        )
        connection = database.connection
        assert report["outcome"] == "success"
        assert report["pool_observation"]["members"] == 10
        observations = connection.execute(
            "SELECT pool_observation_id FROM pool_observations"
        ).fetchall()
        assert len(observations) == 1
        members = connection.execute(
            """SELECT position, post_native_id, post_id FROM pool_member_observations
                ORDER BY position"""
        ).fetchall()
        assert [row["position"] for row in members] == list(range(1, 11))
        assert [row["post_native_id"] for row in members] == MEMBERS
        linked = {row["post_native_id"] for row in members if row["post_id"] is not None}
        assert linked == RETAINED
        # Post-view membership exists for the retained posts, keyed by pool.
        post_view = {
            row["native_post_id"]
            for row in connection.execute(
                """SELECT p.native_post_id FROM post_pool_observations ppo
                     JOIN posts p ON p.post_id = ppo.post_id"""
            )
        }
        assert post_view == RETAINED
        # Evidence only: no works, no relationships, no grouping conclusions.
        assert connection.execute("SELECT COUNT(*) FROM works").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM relationships").fetchone()[0] == 0
        run = connection.execute(
            """SELECT status, termination_outcome, request_count, page_count, record_count
                  FROM remote_runs WHERE remote_run_id = ?""",
            (report["remote_run_id"],),
        ).fetchone()
        assert run["status"] == "complete"
        assert run["termination_outcome"] == "success"
        assert (run["request_count"], run["page_count"], run["record_count"]) == (1, 1, 1)
        # The raw report anchors to the pool object with run provenance.
        raw = connection.execute(
            """SELECT object_kind, native_id, remote_run_id FROM raw_observations
                WHERE object_kind = 'pool'"""
        ).fetchall()
        assert len(raw) == 1
        assert raw[0]["native_id"] == POOL_ID
        assert raw[0]["remote_run_id"] == report["remote_run_id"]


def test_unchanged_refetch_is_idempotent(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _catalog(catalog)
    with CatalogDatabase(catalog) as database:
        first = fetch_pool(
            database,
            _StubAdapter(payload=_pool_payload()),
            17001,
            clock=lambda: "2026-10-23T07:00:00Z",
        )
        second = fetch_pool(
            database,
            _StubAdapter(payload=_pool_payload()),
            17001,
            clock=lambda: "2026-10-23T08:00:00Z",
        )
        connection = database.connection
        assert second["outcome"] == "success"
        assert second["pool_observation"]["outcome_kind"] == "existing"
        assert (
            second["pool_observation"]["pool_observation_id"]
            == first["pool_observation"]["pool_observation_id"]
        )
        assert connection.execute("SELECT COUNT(*) FROM pool_observations").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM pool_member_observations").fetchone()[0] == 10
        )
        # Every fetch still retains its own raw report and run.
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM raw_observations WHERE object_kind = 'pool'"
            ).fetchone()[0]
            == 2
        )
        assert second["remote_run_id"] != first["remote_run_id"]


def test_reordered_membership_lands_a_new_observation(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _catalog(catalog)
    with CatalogDatabase(catalog) as database:
        fetch_pool(
            database,
            _StubAdapter(payload=_pool_payload()),
            17001,
            clock=lambda: "2026-10-23T07:00:00Z",
        )
        fetch_pool(
            database,
            _StubAdapter(payload=_pool_payload(f"danbooru_pool_{POOL_ID}_reordered.json")),
            17001,
            clock=lambda: "2026-10-23T08:00:00Z",
        )
        connection = database.connection
        assert connection.execute("SELECT COUNT(*) FROM pool_observations").fetchone()[0] == 2
        latest = connection.execute(
            """SELECT pool_observation_id FROM pool_observations
                ORDER BY pool_observation_id DESC LIMIT 1"""
        ).fetchone()[0]
        order = [
            row["post_native_id"]
            for row in connection.execute(
                """SELECT post_native_id FROM pool_member_observations
                    WHERE pool_observation_id = ? ORDER BY position""",
                (latest,),
            )
        ]
        assert order == MEMBERS[1:] + MEMBERS[:1]


@pytest.mark.parametrize(
    ("status_code", "payload", "outcome"),
    [
        (404, b'{"success": false}', "unavailable"),
        (200, b"not json at all", "malformed_response"),
        (200, b'{"id": 17001, "post_ids": [1, "x"]}', "malformed_response"),
        (200, b'{"id": 999, "post_ids": []}', "malformed_response"),
    ],
)
def test_failure_outcomes_are_typed(
    tmp_path: Path, status_code: int, payload: bytes, outcome: str
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _catalog(catalog)
    with CatalogDatabase(catalog) as database:
        report = fetch_pool(
            database,
            _StubAdapter(payload=payload, status_code=status_code),
            17001,
            clock=lambda: "2026-10-23T07:00:00Z",
        )
        connection = database.connection
        assert report["outcome"] == outcome
        assert report["pool_observation"] is None
        assert connection.execute("SELECT COUNT(*) FROM pool_observations").fetchone()[0] == 0
        run = connection.execute(
            """SELECT status, termination_outcome, request_count, record_count FROM remote_runs
                WHERE remote_run_id = ?""",
            (report["remote_run_id"],),
        ).fetchone()
        assert run["termination_outcome"] == outcome
        assert run["status"] == "failed"
        assert run["request_count"] == 1
        assert run["record_count"] == 0
        # Every response retains its raw report, malformed or an error body.
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM raw_observations WHERE object_kind = 'pool'"
            ).fetchone()[0]
            == 1
        )


def test_pool_observations_are_storage_immutable(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _catalog(catalog)
    with CatalogDatabase(catalog) as database:
        fetch_pool(
            database,
            _StubAdapter(payload=_pool_payload()),
            17001,
            clock=lambda: "2026-10-23T07:00:00Z",
        )
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            database.connection.execute("UPDATE pool_observations SET pool_native_id = 'x'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            database.connection.execute("DELETE FROM pool_observations")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            database.connection.execute("UPDATE pool_member_observations SET position = 99")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            database.connection.execute("DELETE FROM pool_member_observations")


def test_adapter_requests_the_pool_endpoint() -> None:
    requested: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        requested["url"] = str(request.url)
        return httpx.Response(200, content=_pool_payload())

    adapter = DanbooruAdapter(
        DANBOORU,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    envelope = adapter.fetch(AdapterRequest(operation=AdapterOperation.FETCH_POOL, target=POOL_ID))
    assert requested["url"].endswith(f"/pools/{POOL_ID}.json")
    assert envelope.status_code == 200


class _RaisingAdapter:
    instance_key = "danbooru"
    adapter_version = "test-v1"
    schema_version = "test-v1"

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        raise RuntimeError("transport exploded")


def test_transport_failure_leaves_an_auditable_run(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _catalog(catalog)
    with CatalogDatabase(catalog) as database:
        with pytest.raises(RuntimeError, match="transport exploded"):
            fetch_pool(
                database,
                _RaisingAdapter(),
                17001,
                clock=lambda: "2026-10-23T07:00:00Z",
            )
        connection = database.connection
        run = connection.execute(
            "SELECT status, termination_outcome, request_count FROM remote_runs"
        ).fetchone()
        assert run["status"] == "failed"
        assert run["termination_outcome"] == "local_persistence"
        assert run["request_count"] == 0
        assert connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 0
