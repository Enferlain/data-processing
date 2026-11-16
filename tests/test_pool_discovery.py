"""Danbooru pool search (bead data-processing-rip, change
add-danbooru-pool-discovery): discovery plus membership in one request —
adapter request parts, payload parsing, the run/recording contract, and the
artist-name discovery loop with prior-run skipping."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from media_catalog.adapters import AdapterOperation, AdapterRequest, ResponseEnvelope
from media_catalog.adapters.danbooru.adapter import DanbooruAdapter
from media_catalog.adapters.danbooru.config import DANBOORU
from media_catalog.database import CatalogDatabase
from media_catalog.remote_sync.pool_discovery import (
    _parse_pool_search,
    discover_pools,
    ranked_artist_names,
    search_pools,
)

SEARCH_PAYLOAD = json.dumps(
    [
        {
            "id": 11225,
            "name": "Artist_Series",
            "post_ids": [2408422, 2408421, 2408424],
        },
        {"id": 7, "name": "Tiny", "post_ids": []},
    ]
).encode()


class _FakeAdapter:
    instance_key = "danbooru"
    adapter_version = "test-v1"
    schema_version = "danbooru-json-v1"

    def __init__(self, payload: bytes = SEARCH_PAYLOAD, status: int = 200) -> None:
        self._payload = payload
        self._status = status
        self.requests: list[AdapterRequest] = []

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        self.requests.append(request)
        return ResponseEnvelope(
            provider="danbooru",
            instance="danbooru",
            operation=request.operation,
            request_identity=f"test:{request.target}",
            status_code=self._status,
            headers={"content-type": "application/json"},
            payload=self._payload,
            observed_at="2026-11-15T20:00:00Z",
            adapter_version=self.adapter_version,
            schema_version=self.schema_version,
        )


def _adapter() -> DanbooruAdapter:
    import httpx

    return DanbooruAdapter(DANBOORU, client=httpx.Client())


def test_request_parts_search_pools() -> None:
    adapter = _adapter()
    endpoint, params, identity = adapter._request_parts(
        AdapterRequest(operation=AdapterOperation.SEARCH_POOLS, target="ama_mitsuki")
    )
    assert endpoint == "/pools.json"
    assert params["search[name_matches]"] == "ama_mitsuki"
    assert identity == "danbooru:search_pools:ama_mitsuki"
    with pytest.raises(ValueError, match="1-100 characters"):
        adapter._request_parts(
            AdapterRequest(operation=AdapterOperation.SEARCH_POOLS, target="x" * 101)
        )


def test_parse_pool_search_accepts_captured_shape_and_rejects_garbage() -> None:
    pools = _parse_pool_search(SEARCH_PAYLOAD)
    assert pools is not None
    assert pools[0]["pool_native_id"] == "11225"
    assert pools[0]["post_native_ids"] == ("2408422", "2408421", "2408424")
    assert pools[1]["post_native_ids"] == ()
    assert _parse_pool_search(b"{}") is None
    assert _parse_pool_search(json.dumps([{"id": True, "post_ids": []}]).encode()) is None
    assert _parse_pool_search(json.dumps([{"id": 5, "post_ids": [True]}]).encode()) is None


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database, database.transaction():
        connection = database.connection
        platform = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
        ).fetchone()
        assert platform is not None
        danbooru_id = int(platform[0])
        # tags are unique per (platform, category, name); create once
        tag_ids: dict[str, int] = {}
        for artist in ("some_artist", "rare"):
            tag = connection.execute(
                """INSERT INTO tags (platform_id, category, name, normalization_version)
                   VALUES (?, 'artist', ?, 'test-v1')""",
                (danbooru_id, artist),
            )
            tag_ids[artist] = int(tag.lastrowid)
        for native, artist in (
            # 2408422 is a payload member: the writer must link this post
            ("2408422", "some_artist"),
            ("d-2", "some_artist"),
            ("d-4", "some_artist"),
            ("d-3", "rare"),
            ("d-5", "rare"),
            ("d-6", "rare"),
        ):
            post = connection.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (danbooru_id, native),
            )
            connection.execute(
                """INSERT INTO post_tags (post_id, tag_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (int(post.lastrowid), tag_ids[artist]),
            )
    return path


def _clock() -> Any:
    return lambda: "2026-11-15T20:00:01Z"


def test_search_pools_records_run_raw_and_observations(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        adapter = _FakeAdapter()
        result = search_pools(database, adapter, "some_artist", clock=_clock())
    assert result["pools_found"] == 2
    assert [pool["pool_native_id"] for pool in result["pools"]] == ["11225", "7"]
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        assert (
            connection.execute(
                "SELECT count(*) FROM remote_runs WHERE operation = 'search_pools'"
            ).fetchone()[0]
            == 1
        )
        # pool 11225 observation recorded with ordered members; 7 is empty
        members = connection.execute(
            """SELECT pm.position, pm.post_native_id FROM pool_member_observations pm
                 JOIN pool_observations po ON po.pool_observation_id = pm.pool_observation_id
                WHERE po.pool_native_id = '11225' ORDER BY pm.position"""
        ).fetchall()
        assert [tuple(row) for row in members] == [(1, "2408422"), (2, "2408421"), (3, "2408424")]
        # the writer linked the retained member post into pool 11225
        linked = connection.execute(
            """SELECT p.native_post_id FROM post_pool_observations o
                 JOIN posts p ON p.post_id = o.post_id"""
        ).fetchall()
        assert [tuple(row) for row in linked] == [("2408422",)]
        # every observation anchors to the retained search raw report
        assert (
            connection.execute(
                """SELECT count(*) FROM pool_observations
                    WHERE raw_observation_id IS NULL
                       OR raw_observation_id NOT IN (SELECT raw_observation_id
                                                       FROM raw_observations)"""
            ).fetchone()[0]
            == 0
        )


def test_discover_skips_searched_names_and_respects_budget(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        adapter = _FakeAdapter()
        first = search_pools(database, adapter, "some_artist", clock=_clock())

    assert first["outcome"] == "success"

    class _Factory:
        calls = 0

        def __call__(self, client: object) -> _FakeAdapter:
            _Factory.calls += 1
            return _FakeAdapter()

    class _NullClient:
        def __enter__(self) -> _NullClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    with CatalogDatabase(catalog) as database:
        result = discover_pools(
            database,
            _Factory(),
            "danbooru",
            clock=_clock(),
            names_limit=10,
            request_budget=1,
            client_factory=_NullClient,
        )
        ranked_names = ranked_artist_names(database.connection, "danbooru", limit=10)
    # some_artist was already searched (complete run) and is skipped; rare
    # is eligible and consumes the single-request budget
    assert result["names_searched"] == 1
    assert result["names_skipped_already_searched"] == 1
    assert result["requests_used"] == 1
    assert ranked_names == [("rare", 3), ("some_artist", 3)]
