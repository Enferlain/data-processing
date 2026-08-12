from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import AdapterOperation
from media_catalog.adapters.danbooru import DANBOORU, DanbooruAdapter
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.database import CatalogDatabase
from media_catalog.library import (
    ArtistLibraryExpansionService,
    ExpansionLimits,
    LibraryCountProbeService,
    plan_library_expansion,
    replan_library_execution,
)
from media_catalog.records import AccountRecord, AttributionRecord
from media_catalog.remote_sync import MetadataSyncService, SyncLimits
from media_catalog.remote_sync.service import RemoteSyncOrigin
from media_catalog.writer import CatalogWriter

NOW = "2026-08-12T20:00:00Z"
LATER = "2026-08-12T21:00:00Z"


def _plan(database: CatalogDatabase, *, limits: ExpansionLimits | None = None):
    writer = CatalogWriter(database)
    with database.transaction():
        account_id = writer.upsert_account(AccountRecord("pixiv", "1001", NOW)).id
    return plan_library_expansion(database, f"account:{account_id}", limits=limits)


def _service(
    database: CatalogDatabase,
    handler,
) -> tuple[ArtistLibraryExpansionService, PixivAdapter]:
    adapter = PixivAdapter(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        refresh_token_env=None,
        clock=lambda: NOW,
    )
    return (
        ArtistLibraryExpansionService(
            database,
            adapter,
            minimum_interval_seconds=0,
            maximum_retries=0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        ),
        adapter,
    )


def test_expansion_commits_origin_execution_and_sparse_post_atomically(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"illusts": [{"id": 2001, "title": "summary", "type": "illust"}]},
        )

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        plan = _plan(database)
        service, adapter = _service(database, handler)
        try:
            result = service.run(plan)
        finally:
            adapter.close()
        run = database.connection.execute(
            """SELECT origin_kind, origin_reference, status, termination_outcome
                 FROM remote_runs WHERE remote_run_id = ?""",
            (result.sync.remote_run_id,),
        ).fetchone()
        association = database.connection.execute(
            """SELECT lep.details_required, p.native_post_id, lep.raw_observation_id
                 FROM library_expansion_posts lep JOIN posts p USING(post_id)
                WHERE lep.library_expansion_execution_id = ?""",
            (result.library_expansion_execution_id,),
        ).fetchone()
        event_count = database.connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    assert result.sync.status == "complete"
    assert tuple(run) == ("library_expansion", plan.digest, "complete", "success")
    assert tuple(association) == (1, "2001", association["raw_observation_id"])
    assert association["raw_observation_id"] is not None
    assert event_count == 0
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/user/illusts"


def test_stale_plan_is_rejected_before_run_creation_or_network(tmp_path: Path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"illusts": []})

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        plan = _plan(database)
        with database.transaction():
            CatalogWriter(database).upsert_account(
                AccountRecord("pixiv", "1001", LATER, display_name="changed")
            )
        service, adapter = _service(database, handler)
        try:
            with pytest.raises(ValueError, match="stale library expansion plan"):
                service.run(plan)
        finally:
            adapter.close()
        assert database.connection.execute("SELECT COUNT(*) FROM remote_runs").fetchone()[0] == 0
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM library_expansion_executions"
            ).fetchone()[0]
            == 0
        )
    assert calls == 0


def test_probe_observation_does_not_make_existing_plan_stale(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/user/detail":
            return httpx.Response(
                200,
                json={"user": {"id": 1001}, "profile": {"total_illusts": 1}},
            )
        return httpx.Response(200, json={"illusts": [{"id": 2001}]})

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        plan = _plan(database)
        service, adapter = _service(database, handler)
        try:
            probe = LibraryCountProbeService(
                database, pixiv_adapter=adapter, clock=lambda: NOW
            ).probe(plan)
            fresh = plan_library_expansion(database, plan.seed)
            result = service.run(plan)
        finally:
            adapter.close()

    assert probe.outcome == "success"
    assert fresh.digest != plan.digest
    assert fresh.execution_revision == plan.execution_revision
    assert result.sync.status == "complete"
    assert [request.url.path for request in requests] == [
        "/v1/user/detail",
        "/v1/user/illusts",
    ]


def test_paused_expansion_resumes_from_committed_continuation_without_duplicates(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/user/detail":
            return httpx.Response(
                200,
                json={"user": {"id": 1001}, "profile": {"total_illusts": 2}},
            )
        if request.url.params.get("offset") == "1":
            return httpx.Response(200, json={"illusts": [{"id": 2002}], "next_url": None})
        return httpx.Response(
            200,
            json={
                "illusts": [{"id": 2001}],
                "next_url": "https://app-api.pixiv.net/v1/user/illusts?user_id=1001&offset=1",
            },
        )

    limits = ExpansionLimits(requests=1, pages=2, records=10, seconds=60)
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        plan = _plan(database, limits=limits)
        first_service, first_adapter = _service(database, handler)
        try:
            probe = LibraryCountProbeService(
                database, pixiv_adapter=first_adapter, clock=lambda: NOW
            ).probe(plan)
            fresh = plan_library_expansion(database, plan.seed, limits=limits)
            first = first_service.run(fresh)
        finally:
            first_adapter.close()
        replanned = replan_library_execution(database, first.library_expansion_execution_id)
        later = plan_library_expansion(database, plan.seed, limits=limits)
        second_service, second_adapter = _service(database, handler)
        try:
            second = second_service.resume(later, first.library_expansion_execution_id)
        finally:
            second_adapter.close()
        posts = database.connection.execute(
            "SELECT native_post_id FROM posts ORDER BY native_post_id"
        ).fetchall()
        lineage = database.connection.execute(
            """SELECT execution_kind, predecessor_execution_id
                 FROM library_expansion_executions
                ORDER BY library_expansion_execution_id"""
        ).fetchall()
        origins = database.connection.execute(
            "SELECT origin_reference FROM remote_runs ORDER BY remote_run_id"
        ).fetchall()

    assert probe.outcome == "success"
    assert replanned.estimate.state == "count"
    assert replanned.digest == fresh.digest
    assert fresh.digest != plan.digest
    assert fresh.execution_revision == plan.execution_revision
    assert first.sync.status == "paused"
    assert first.sync.budget_boundary == "request"
    assert second.sync.status == "complete"
    assert [row[0] for row in posts] == ["2001", "2002"]
    assert tuple(lineage[0]) == ("initial", None)
    assert tuple(lineage[1]) == ("resume", first.library_expansion_execution_id)
    assert [row[0] for row in origins] == [fresh.digest, fresh.digest]
    assert len(requests) == 3
    assert requests[2].url.params["offset"] == "1"


def test_typed_provider_failure_keeps_execution_and_raw_response(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        plan = _plan(database)
        service, adapter = _service(
            database,
            lambda _request: httpx.Response(401, json={"error": "fixture"}),
        )
        try:
            result = service.run(plan)
        finally:
            adapter.close()
        raw_count = database.connection.execute(
            "SELECT COUNT(*) FROM raw_observations WHERE remote_run_id = ?",
            (result.sync.remote_run_id,),
        ).fetchone()[0]

    assert result.sync.status == "failed"
    assert result.sync.outcome == "authentication_required"
    assert raw_count == 1


def test_completed_expansion_cannot_be_resumed(tmp_path: Path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"illusts": []})

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        plan = _plan(database)
        first_service, first_adapter = _service(database, handler)
        try:
            first = first_service.run(plan)
        finally:
            first_adapter.close()
        second_service, second_adapter = _service(database, handler)
        try:
            with pytest.raises(ValueError, match="only a paused"):
                second_service.resume(plan, first.library_expansion_execution_id)
        finally:
            second_adapter.close()
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM library_expansion_executions"
            ).fetchone()[0]
            == 1
        )
    assert calls == 1


def test_origin_binding_failure_rolls_back_run_before_network(tmp_path: Path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"illusts": []})

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        adapter = PixivAdapter(
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            refresh_token_env=None,
            clock=lambda: NOW,
        )
        service = MetadataSyncService(
            database,
            adapter,
            minimum_interval_seconds=0,
            maximum_retries=0,
            clock=lambda: NOW,
        )

        def fail_binding(writer, remote_run_id, created_at):
            del writer, remote_run_id, created_at
            raise RuntimeError("simulated origin association failure")

        def ignore_page(writer, binding, retained_page, write_result):
            del writer, binding, retained_page, write_result

        origin = RemoteSyncOrigin(
            "library_expansion",
            "d" * 64,
            fail_binding,
            ignore_page,
        )
        try:
            with pytest.raises(RuntimeError, match="simulated origin association failure"):
                service.synchronize(
                    AdapterOperation.LIST_ACCOUNT_POSTS,
                    "1001",
                    limits=SyncLimits(1, 1, 1, 60),
                    origin=origin,
                )
        finally:
            adapter.close()

        assert database.connection.execute("SELECT COUNT(*) FROM remote_runs").fetchone()[0] == 0
    assert calls == 0


def test_danbooru_attribution_renders_retained_primary_name_privately(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = writer.upsert_account(AccountRecord("x", "9001", NOW)).id
            attribution_id = writer.upsert_attribution(
                AttributionRecord(
                    "danbooru",
                    "44",
                    "danbooru-native-v1",
                    NOW,
                    primary_name="artist_a",
                )
            ).id
        plan = plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"attribution:{attribution_id}",
            selection_note="selected provider attribution",
        )
        client = httpx.Client(transport=httpx.MockTransport(handler))
        adapter = DanbooruAdapter(DANBOORU, client=client, clock=lambda: NOW)
        try:
            result = ArtistLibraryExpansionService(
                database,
                adapter,
                minimum_interval_seconds=0,
                maximum_retries=0,
                clock=lambda: NOW,
            ).run(plan)
        finally:
            client.close()

    assert result.sync.status == "complete"
    assert len(requests) == 1
    assert requests[0].url.params["tags"] == "artist_a"
    assert "artist_a" not in str(result.as_dict())
    assert "artist:44" not in str(requests[0].url)
