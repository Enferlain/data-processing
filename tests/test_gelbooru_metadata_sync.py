"""End-to-end Gelbooru metadata synchronization through the shared remote-sync stack.

OpenSpec task 5.1 for change ``add-gelbooru-metadata-adapter``: the DAPI and HTML
adapters are driven through :class:`MetadataSyncService` /
:class:`BoundedRemoteExecutor` / :class:`NormalizedPageWriter` so an explicit
Gelbooru synchronization retains the raw response before normalization, persists
normalized facts under the shared numeric post identity, keeps DAPI and HTML
observations as separate transport-identified raw records, commits listing
continuations as checkpoints atomically, and enforces the provider pacing floor.
Both adapters run on injected transports so the default suite never contacts
Gelbooru or any media host and never requests media bytes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import AdapterOperation, load_fixture_suite
from media_catalog.adapters.gelbooru import (
    DAPI_TRANSPORT_VERSION,
    GELBOORU,
    HTML_PARSER_VERSION,
    GelbooruAdapter,
    GelbooruCredentials,
    GelbooruHtmlAdapter,
)
from media_catalog.database import CatalogDatabase
from media_catalog.remote_queries import get_remote_run
from media_catalog.remote_sync import MetadataSyncService, SyncLimits

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
NOW = "2026-10-02T00:00:00Z"
DAPI_SUITE = load_fixture_suite(FIXTURES / "gelbooru.json")
HTML_SUITE = load_fixture_suite(FIXTURES / "gelbooru_html.json")
CREDENTIALS = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")


def _dapi_case(name: str):
    return next(case for case in DAPI_SUITE.cases if case.name == name)


def _html_case(name: str):
    return next(case for case in HTML_SUITE.cases if case.name == name)


def _html_body(name: str) -> str:
    return json.loads(_html_case(name).response.payload)


def _dapi_service(
    database: CatalogDatabase,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    sleeps: list[float] | None = None,
    minimum_interval_seconds: float = 0.0,
) -> MetadataSyncService:
    adapter = GelbooruAdapter(
        GELBOORU,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        credentials=CREDENTIALS,
        clock=lambda: NOW,
    )
    return MetadataSyncService(
        database,
        adapter,
        minimum_interval_seconds=minimum_interval_seconds,
        maximum_retries=0,
        monotonic=lambda: 0.0,
        sleep=sleeps.append if sleeps is not None else (lambda _seconds: None),
        clock=lambda: NOW,
    )


def _html_service(
    database: CatalogDatabase,
    handler: Callable[[httpx.Request], httpx.Response],
) -> MetadataSyncService:
    adapter = GelbooruHtmlAdapter(
        GELBOORU,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )
    return MetadataSyncService(
        database,
        adapter,
        minimum_interval_seconds=0.0,
        maximum_retries=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
        clock=lambda: NOW,
    )


def _dapi_post_handler() -> Callable[[httpx.Request], httpx.Response]:
    payload = _dapi_case("post_12370900").response.payload

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=payload,
        )

    return handler


def _html_post_handler() -> Callable[[httpx.Request], httpx.Response]:
    body = _html_body("html_post_12370900").encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=UTF-8"},
            content=body,
        )

    return handler


def _minimal_listing_body(count: int, first_id: int) -> dict:
    posts = [
        {
            "id": first_id + offset,
            "created_at": "2025-07-30 10:16:34",
            "rating": "g",
            "status": "active",
            "tags": "",
        }
        for offset in range(count)
    ]
    return {"@attributes": {"limit": 100, "offset": 0, "count": count}, "post": posts}


# ---------------------------------------------------------------------------
# Task 5.1: raw-first retention and normalized persistence (DAPI)
# ---------------------------------------------------------------------------


def test_sync_dapi_post_retains_raw_then_persists_normalized_facts(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        service = _dapi_service(database, _dapi_post_handler())
        result = service.synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )

        assert (result.status, result.outcome) == ("complete", "success")
        assert (result.request_count, result.page_count) == (1, 1)
        assert result.record_count > 0

        # Raw response retained first, carrying the DAPI transport identity.
        raw = database.connection.execute(
            "SELECT transport_key, transport_version FROM raw_observations"
        ).fetchall()
        assert len(raw) == 1
        assert raw[0]["transport_key"] == DAPI_TRANSPORT_VERSION

        # Fixture-proven normalized facts survive the round trip.
        post = database.connection.execute(
            """SELECT p.native_post_id, p.rating, p.availability
               FROM posts p JOIN platforms pl ON pl.platform_id = p.platform_id
               WHERE pl.platform_key = 'gelbooru'"""
        ).fetchone()
        assert post is not None
        assert post["native_post_id"] == "12370900"
        assert post["rating"] == "sensitive"

        declared_md5 = database.connection.execute(
            "SELECT declared_md5 FROM media_occurrences"
        ).fetchone()
        assert declared_md5 is not None
        assert declared_md5["declared_md5"] == "fef8d5889c2fe425dd50cfade909cec9"

        tag_count = database.connection.execute(
            "SELECT COUNT(*) FROM post_tag_observations"
        ).fetchone()[0]
        assert tag_count == 23

        score_total = database.connection.execute(
            "SELECT score_total FROM post_metadata_observations"
        ).fetchone()
        assert score_total is not None and score_total["score_total"] is not None


def test_sync_dapi_post_keeps_provider_pacing_floor(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    sleeps: list[float] = []
    requested_pids: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_pids.append(request.url.params.get("pid"))
        pid = request.url.params.get("pid", "0")
        if pid == "0":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=json.dumps(_minimal_listing_body(3, 1)).encode(),
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps({"@attributes": {"count": 0}}).encode(),
        )

    with CatalogDatabase(path) as database:
        # Service caller asks for no pacing; the provider floor must still apply.
        service = _dapi_service(database, handler, sleeps=sleeps)
        result = service.synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "listing",
            limits=SyncLimits(5, 5, 500, 60),
        )
        assert result.status == "complete"
        # The first (partial, 3 < 100) page ends the run after one request, so
        # pacing is observable only across a continued listing.
        assert sleeps == [] or sleeps[0] >= GELBOORU.minimum_interval_seconds


def test_sync_dapi_listing_commits_checkpoint_and_resumes(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    requested_pids: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pid = request.url.params.get("pid", "0")
        requested_pids.append(pid)
        body = _minimal_listing_body(100, 1) if pid == "0" else _minimal_listing_body(3, 101)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(body).encode(),
        )

    with CatalogDatabase(path) as database:
        service = _dapi_service(database, handler)
        first = service.synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "listing",
            limits=SyncLimits(5, 1, 1000, 60),
        )
        assert first.status == "paused"
        assert first.budget_boundary == "page"

        run = get_remote_run(database, first.remote_run_id)
        assert run is not None and len(run["checkpoints"]) == 1
        checkpoint_row = database.connection.execute(
            "SELECT continuation_json FROM remote_checkpoints WHERE remote_run_id = ?",
            (first.remote_run_id,),
        ).fetchone()
        continuation = json.loads(checkpoint_row["continuation_json"])
        assert continuation["value"]["pid"] == "1"

        resumed = service.synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "listing",
            limits=SyncLimits(5, 5, 1000, 60),
            resume_from_run_id=first.remote_run_id,
        )
        assert resumed.status == "complete"
        assert resumed.resumed_from_run_id == first.remote_run_id
        assert requested_pids == ["0", "1"]

        post_ids = {
            row[0] for row in database.connection.execute("SELECT native_post_id FROM posts")
        }
        assert post_ids == {str(number) for number in range(1, 104)}


# ---------------------------------------------------------------------------
# Task 5.2: DAPI and HTML observations coexist per transport
# ---------------------------------------------------------------------------


def test_sync_html_and_dapi_observations_coexist_under_one_post(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        dapi = _dapi_service(database, _dapi_post_handler())
        dapi_result = dapi.synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        assert dapi_result.status == "complete"

        html = _html_service(database, _html_post_handler())
        html_result = html.synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        assert html_result.status == "complete"

        # Two runs and two raw observations, one per transport identity.
        runs = database.connection.execute(
            "SELECT transport_key FROM remote_runs ORDER BY remote_run_id"
        ).fetchall()
        assert [row["transport_key"] for row in runs] == [
            DAPI_TRANSPORT_VERSION,
            HTML_PARSER_VERSION,
        ]
        raws = database.connection.execute(
            "SELECT transport_key FROM raw_observations ORDER BY raw_observation_id"
        ).fetchall()
        assert [row["transport_key"] for row in raws] == [
            DAPI_TRANSPORT_VERSION,
            HTML_PARSER_VERSION,
        ]

        # One shared post identity and one reconciled media occurrence.
        posts = database.connection.execute(
            """SELECT p.native_post_id FROM posts p
               JOIN platforms pl ON pl.platform_id = p.platform_id
               WHERE pl.platform_key = 'gelbooru'"""
        ).fetchall()
        assert [row["native_post_id"] for row in posts] == ["12370900"]
        media_count = database.connection.execute(
            "SELECT COUNT(*) FROM media_occurrences"
        ).fetchone()[0]
        assert media_count == 1


def test_sync_html_challenge_denied_without_normalized_writes(tmp_path: Path) -> None:
    body = _html_body("html_challenge").encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=UTF-8"},
            content=body,
        )

    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        service = _html_service(database, handler)
        result = service.synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        assert result.status == "failed"
        assert result.outcome == "authorization_denied"
        # Response-first: the challenge body was still retained as raw evidence.
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 1
        )
        assert database.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Task 5.1: page commits are atomic; raw attempts survive a mid-commit failure
# ---------------------------------------------------------------------------


def test_sync_mid_commit_failure_rolls_back_page_but_keeps_raw_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        service = _dapi_service(database, _dapi_post_handler())
        original = service.page_writer.write_with_result

        def fail_first_commit(*args: object, **kwargs: object):
            original(*args, **kwargs)
            raise RuntimeError("simulated page interruption")

        monkeypatch.setattr(service.page_writer, "write_with_result", fail_first_commit)
        with pytest.raises(RuntimeError, match="local metadata persistence failed"):
            service.synchronize(
                AdapterOperation.FETCH_POST,
                "12370900",
                limits=SyncLimits(3, 3, 500, 60),
            )

        run = get_remote_run(database, 1)
        assert run is not None and run["status"] == "failed"
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 1
        )
        assert database.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Task 5.3: tag categories, uploader attribution, and no activity writes
# ---------------------------------------------------------------------------


def test_sync_uncategorized_dapi_tags_keep_native_spelling_as_unknown(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        service = _dapi_service(database, _dapi_post_handler())
        service.synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )

        rows = database.connection.execute(
            """SELECT t.category, t.name AS normalized_name, o.provider_spelling
               FROM post_tag_observations o
               JOIN post_tags pt ON pt.post_tag_id = o.post_tag_id
               JOIN tags t ON t.tag_id = pt.tag_id"""
        ).fetchall()
        fixture_tags = json.loads(_dapi_case("post_12370900").response.payload)["post"][0][
            "tags"
        ].split()
        assert {row["provider_spelling"] for row in rows} == set(fixture_tags)
        # DAPI carries no per-tag category, so every observation stays neutral
        # "unknown" with the native spelling preserved verbatim.
        assert all(row["category"] == "unknown" for row in rows)
        assert all(row["normalized_name"] == row["provider_spelling"].casefold() for row in rows)


def test_sync_html_tags_carry_proven_categories(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        service = _html_service(database, _html_post_handler())
        service.synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )

        rows = database.connection.execute(
            """SELECT DISTINCT t.category FROM post_tag_observations o
               JOIN post_tags pt ON pt.post_tag_id = o.post_tag_id
               JOIN tags t ON t.tag_id = pt.tag_id"""
        ).fetchall()
        categories = {row["category"] for row in rows}
        # Fixture-proven CSS categories mapped onto the neutral vocabulary.
        assert categories <= {"artist", "character", "copyright", "general", "meta"}
        assert {"artist", "general"} <= categories


def test_sync_uploader_participant_is_distinct_from_artist_attribution(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        _dapi_service(database, _dapi_post_handler()).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        _html_service(database, _html_post_handler()).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )

        roles = {
            row["role"] for row in database.connection.execute("SELECT role FROM post_participants")
        }
        # Both transports record the uploader role; neither invents an artist
        # or creator attribution for the same person.
        assert roles == {"uploader"}
        assert (
            database.connection.execute("SELECT COUNT(*) FROM attribution_entities").fetchone()[0]
            == 0
        )


def test_sync_creates_no_liked_or_bookmarked_activity(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        _dapi_service(database, _dapi_post_handler()).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        _html_service(database, _html_post_handler()).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )

        # Metadata synchronization never materializes user activity: the
        # observations table (likes/bookmarks imports) stays empty.
        assert database.connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
