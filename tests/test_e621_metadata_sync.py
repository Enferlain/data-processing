"""End-to-end e621 metadata synchronization through the shared remote-sync stack.

These tests cover OpenSpec task 4.1 for change ``add-e621-metadata-adapter``: the
already-created :class:`E621Adapter` is driven through
:class:`MetadataSyncService` / :class:`BoundedRemoteExecutor` /
:class:`NormalizedPageWriter` so an explicit e621 synchronization retains the raw
response before normalization, persists normalized facts and counters, commits a
compatible target-scoped ``b<ID>`` continuation/checkpoint atomically, and keeps
the >=1s provider pacing floor regardless of the service caller.  The adapter is
exercised with an injected transport so the default suite never contacts e621 or
any media host and never requests media bytes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import AdapterOperation, load_fixture_suite
from media_catalog.adapters.e621 import (
    CONTINUATION_VERSION,
    E621,
    E621Adapter,
    E621Credentials,
)
from media_catalog.database import CatalogDatabase
from media_catalog.remote_queries import get_remote_run, list_attributions
from media_catalog.remote_sync import MetadataSyncService, SyncLimits

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
NOW = "2026-08-13T00:00:00Z"
SUITE = load_fixture_suite(FIXTURES / "e621.json")


def _case(name: str):
    return next(case for case in SUITE.cases if case.name == name)


def _body(name: str) -> object:
    return json.loads(_case(name).response.payload)


def _json_response(
    body: object,
    status: int = 200,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    response_headers = {"content-type": "application/json"}
    if headers is not None:
        response_headers.update(headers)
    return httpx.Response(
        status,
        headers=response_headers,
        content=json.dumps(body, ensure_ascii=False).encode(),
    )


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    credentials: E621Credentials | None = None,
) -> E621Adapter:
    return E621Adapter(
        E621,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        credentials=credentials,
        clock=lambda: NOW,
    )


def _service(
    database: CatalogDatabase,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    sleeps: list[float] | None = None,
    minimum_interval_seconds: float = 0.0,
    maximum_retries: int = 0,
    monotonic: Callable[[], float] | None = None,
    credentials: E621Credentials | None = None,
) -> MetadataSyncService:
    return MetadataSyncService(
        database,
        _adapter(handler, credentials=credentials),
        minimum_interval_seconds=minimum_interval_seconds,
        maximum_retries=maximum_retries,
        monotonic=monotonic or (lambda: 0.0),
        sleep=sleeps.append if sleeps is not None else (lambda _seconds: None),
        clock=lambda: NOW,
    )


def _record_hosts(
    handler: Callable[[httpx.Request], httpx.Response],
    requested_hosts: list[str],
) -> Callable[[httpx.Request], httpx.Response]:
    def wrapper(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host or "")
        return handler(request)

    return wrapper


def _listing_handler() -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        if page is None:
            return _json_response(_body("listing_first"))
        if page == "b5101":
            return _json_response(_body("listing_continuation"))
        return _json_response([])

    return handler


# ---------------------------------------------------------------------------
# Explicit post fetch: raw retention, normalized facts, and counters (task 4.1)
# ---------------------------------------------------------------------------


def test_sync_fetch_post_retains_raw_then_persists_normalized_facts(
    tmp_path: Path,
) -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host or "")
        return _json_response(_body("normal_post"))

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        connection = database.connection
        result = _service(database, handler).synchronize(
            AdapterOperation.FETCH_POST,
            "5001",
            limits=SyncLimits(1, 1, 10, 10),
        )
        assert result.status == "complete"
        assert result.outcome == "success"
        assert (result.request_count, result.page_count, result.record_count) == (1, 1, 2)
        # Raw response is retained exactly once before normalization produces any state.
        assert connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 1
        assert (
            connection.execute("SELECT object_kind FROM raw_observations").fetchone()[0] == "post"
        )

        rating, availability = connection.execute(
            "SELECT rating, availability FROM posts WHERE native_post_id = '5001'"
        ).fetchone()
        assert (rating, availability) == ("s", "available")

        md5, file_size, width, height, has_variants, media_availability = connection.execute(
            """SELECT mo.declared_md5, mo.declared_file_size, mo.width, mo.height,
                      mo.variants_json IS NOT NULL, mo.availability
               FROM media_occurrences mo JOIN posts p USING (post_id)
               WHERE p.native_post_id = '5001'"""
        ).fetchone()
        assert md5 == "abcdef0123456789abcdef0123456789"
        assert (file_size, width, height) == (234567, 1600, 1200)
        assert has_variants == 1
        assert media_availability == "available"

        # Score/counts/pools are retained as typed post observations.
        post_id = connection.execute(
            "SELECT post_id FROM posts WHERE native_post_id = '5001'"
        ).fetchone()[0]
        metadata = connection.execute(
            "SELECT score_total, favorite_count, comment_count FROM post_metadata_observations"
        ).fetchone()
        assert (metadata[0], metadata[1], metadata[2]) == (18, 12, 3)
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM post_pool_observations WHERE post_id = ?", (post_id,)
            ).fetchone()[0]
            == 1
        )

        # The uploader is retained only as a participant role, never as authorship.
        assert (
            connection.execute(
                """SELECT COUNT(*) FROM post_participants pp
                   JOIN posts p USING (post_id) WHERE p.native_post_id = '5001'"""
            ).fetchone()[0]
            == 1
        )
        # Parent relationship is retained without fan-out.
        assert connection.execute("SELECT COUNT(*) FROM post_relations").fetchone()[0] == 1
        # Metadata sync contacts only the provider metadata host, never a media host.
        assert requested_hosts == ["e621.net"]


def test_sync_fetch_attribution_persists_artist_record_not_account(
    tmp_path: Path,
) -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host or "")
        return _json_response(_body("artist_record"))

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        connection = database.connection
        result = _service(database, handler).synchronize(
            AdapterOperation.FETCH_ATTRIBUTION,
            "6001",
            limits=SyncLimits(1, 1, 10, 10),
        )
        assert result.status == "complete"
        assert result.record_count == 1
        # An artist record is attribution evidence, never an account.
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
        attributions = list_attributions(database, platform="e621")
        assert len(attributions) == 1
        assert attributions[0]["url_count"] == 2
        assert requested_hosts == ["e621.net"]


def test_sync_normalization_failure_retains_raw_without_normalized_state(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(_body("malformed_post"))

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        connection = database.connection
        result = _service(database, handler).synchronize(
            AdapterOperation.FETCH_POST,
            "5001",
            limits=SyncLimits(1, 1, 10, 10),
        )
        assert result.status == "failed"
        assert result.outcome == "malformed_response"
        # The raw response is retained before normalization is attempted.
        assert connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 1
        # No normalized state or continuation/checkpoint is committed on failure.
        assert connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM remote_checkpoints").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("status", "headers", "outcome", "retry_after"),
    [
        (401, {}, "authentication_required", None),
        (403, {}, "authorization_denied", None),
        (429, {"retry-after": "2"}, "rate_limited", "2026-08-13T00:00:02Z"),
        (503, {}, "transient_provider", None),
        (503, {"retry-after": "3"}, "rate_limited", "2026-08-13T00:00:03Z"),
    ],
)
def test_sync_http_failures_are_typed_and_retain_retry_metadata(
    tmp_path: Path,
    status: int,
    headers: dict[str, str],
    outcome: str,
    retry_after: str | None,
) -> None:
    payload = {"message": "provider failure"}

    def handler(_request: httpx.Request) -> httpx.Response:
        return _json_response(payload, status, headers=headers)

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        result = _service(database, handler).synchronize(
            AdapterOperation.FETCH_POST,
            "5001",
            limits=SyncLimits(1, 1, 10, 10),
        )
        assert result.status == "failed"
        assert result.outcome == outcome
        assert result.retry_after == retry_after
        assert result.diagnostic is not None
        assert "provider" in result.diagnostic
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 1
        )
        assert database.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
        run = get_remote_run(database, result.remote_run_id)
        assert run is not None
        assert run["termination_outcome"] == outcome
        assert run["retry_after"] == retry_after


def test_sync_retry_retains_each_attempt_before_normalizing_success(
    tmp_path: Path,
) -> None:
    responses = iter(
        (
            _json_response({"message": "slow down"}, 429, headers={"retry-after": "0"}),
            _json_response(_body("normal_post")),
        )
    )
    requested: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        requested.append(1)
        return next(responses)

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        result = _service(
            database,
            handler,
            maximum_retries=1,
        ).synchronize(
            AdapterOperation.FETCH_POST,
            "5001",
            limits=SyncLimits(2, 1, 10, 10),
        )
        assert result.status == "complete"
        assert result.request_count == 2
        assert len(requested) == 2
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 2
        )
        statuses = [
            row[0]
            for row in database.connection.execute(
                "SELECT status_code FROM remote_requests ORDER BY attempt_number"
            )
        ]
        assert statuses == [429, 200]
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM posts WHERE native_post_id = '5001'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    ("operation", "target", "fixture", "object_kind"),
    [
        (AdapterOperation.FETCH_TAG, "fox", "tag_record", "tag"),
        (AdapterOperation.FETCH_TAG_ALIAS, "fox_tail", "active_alias", "tag_alias"),
    ],
)
def test_sync_tag_and_alias_operations_count_one_top_level_record(
    tmp_path: Path,
    operation: AdapterOperation,
    target: str,
    fixture: str,
    object_kind: str,
) -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host or "")
        return _json_response(_body(fixture))

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        result = _service(database, handler).synchronize(
            operation,
            target,
            limits=SyncLimits(1, 1, 1, 10),
        )
        assert result.status == "complete"
        assert result.record_count == 1
        assert requested_hosts == ["e621.net"]
        assert (
            database.connection.execute("SELECT object_kind FROM raw_observations").fetchone()[0]
            == object_kind
        )


@pytest.mark.parametrize(
    ("fixture", "target"),
    [
        ("normal_post", "5001"),
        ("deleted_post", "5002"),
        ("null_media_post", "5003"),
        ("video_post", "5004"),
    ],
)
def test_sync_metadata_never_requests_returned_media_hosts(
    tmp_path: Path,
    fixture: str,
    target: str,
) -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host or "")
        return _json_response(_body(fixture))

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        result = _service(database, handler).synchronize(
            AdapterOperation.FETCH_POST,
            target,
            limits=SyncLimits(1, 1, 10, 10),
        )
        assert result.status == "complete"
    assert requested_hosts == ["e621.net"]


# ---------------------------------------------------------------------------
# Bounded listing: atomic page+checkpoint commit and compatible resume (task 4.1)
# ---------------------------------------------------------------------------


def test_sync_listing_commits_page_and_checkpoint_atomically_then_resumes(
    tmp_path: Path,
) -> None:
    requested_hosts: list[str] = []
    handler = _record_hosts(_listing_handler(), requested_hosts)
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        connection = database.connection
        first = _service(database, handler).synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "artist_a",
            limits=SyncLimits(1, 1, 20, 20),
        )
        assert first.status == "paused"

        # The page, counters, and continuation/checkpoint commit atomically before the pause.
        run = get_remote_run(database, first.remote_run_id)
        assert run is not None and run["status"] == "paused"
        assert (run["page_count"], run["record_count"]) == (1, 4)
        assert len(run["checkpoints"]) == 1
        checkpoint = run["checkpoints"][0]
        assert checkpoint["continuation_adapter"] == "e621"
        assert checkpoint["continuation_version"] == CONTINUATION_VERSION
        assert checkpoint["last_page_identity"] == "e621:list_account_posts:artist_a:first"
        assert connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 2

        # Resume is target-scoped: a different target cannot reuse the checkpoint.
        with pytest.raises(ValueError):
            _service(database, handler).synchronize(
                AdapterOperation.LIST_ACCOUNT_POSTS,
                "artist_b",
                limits=SyncLimits(2, 2, 20, 20),
                resume_from_run_id=first.remote_run_id,
            )

        # A compatible resume continues the b<ID> lineage through to completion.
        resumed = _service(database, handler).synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "artist_a",
            limits=SyncLimits(2, 2, 20, 20),
            resume_from_run_id=first.remote_run_id,
        )
        assert resumed.status == "complete"
        assert resumed.resumed_from_run_id == first.remote_run_id
        post_ids = {row[0] for row in connection.execute("SELECT native_post_id FROM posts")}
        assert post_ids == {"5102", "5101", "5100"}

    assert requested_hosts and all(host == "e621.net" for host in requested_hosts)


def test_sync_listing_resume_survives_database_reopen_without_duplicate_posts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite3"
    requested_pages: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_pages.append(request.url.params.get("page"))
        return _listing_handler()(request)

    with CatalogDatabase(path) as database:
        paused = _service(database, handler).synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "artist_a",
            limits=SyncLimits(1, 2, 20, 20),
        )
        assert paused.status == "paused"
        assert paused.budget_boundary == "request"

    with CatalogDatabase(path) as database:
        resumed = _service(database, handler).synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "artist_a",
            limits=SyncLimits(2, 2, 20, 20),
            resume_from_run_id=paused.remote_run_id,
        )
        assert resumed.status == "complete"
        assert resumed.resumed_from_run_id == paused.remote_run_id
        rows = database.connection.execute(
            "SELECT native_post_id FROM posts ORDER BY native_post_id"
        ).fetchall()
        assert [row[0] for row in rows] == ["5100", "5101", "5102"]
        assert (
            database.connection.execute(
                "SELECT COUNT(DISTINCT native_post_id) FROM posts"
            ).fetchone()[0]
            == 3
        )
        # The first run has one request; the resumed run has exactly the two
        # committed-boundary requests (b5101 and the empty b5100 page).
        assert requested_pages == [None, "b5101", "b5100"]


def test_sync_listing_request_page_record_and_time_boundaries_admit_no_extra_page(
    tmp_path: Path,
) -> None:
    cases = (
        (SyncLimits(1, 3, 20, 20), "request", 1, 1),
        (SyncLimits(3, 1, 20, 20), "page", 1, 1),
        (SyncLimits(3, 3, 3, 20), "record", 1, 0),
    )
    for limits, boundary, request_count, checkpoint_count in cases:
        requested_pages: list[str | None] = []

        def make_handler(
            pages: list[str | None],
        ) -> Callable[[httpx.Request], httpx.Response]:
            def handler(request: httpx.Request) -> httpx.Response:
                pages.append(request.url.params.get("page"))
                return _listing_handler()(request)

            return handler

        with CatalogDatabase(tmp_path / f"{boundary}.sqlite3") as database:
            result = _service(database, make_handler(requested_pages)).synchronize(
                AdapterOperation.LIST_ACCOUNT_POSTS,
                "artist_a",
                limits=limits,
            )
            assert result.status == "paused"
            assert result.budget_boundary == boundary
            assert len(requested_pages) == request_count
            assert (
                database.connection.execute("SELECT COUNT(*) FROM remote_checkpoints").fetchone()[0]
                == checkpoint_count
            )
            if boundary == "record":
                assert database.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0

    class Elapsed:
        calls = 0

        def __call__(self) -> float:
            self.calls += 1
            return 0.0 if self.calls == 1 else 1.0

    elapsed = Elapsed()
    requested: list[int] = []

    def time_handler(_request: httpx.Request) -> httpx.Response:
        requested.append(1)
        return _json_response(_body("normal_post"))

    with CatalogDatabase(tmp_path / "time.sqlite3") as database:
        result = _service(
            database,
            time_handler,
            monotonic=elapsed,
        ).synchronize(
            AdapterOperation.FETCH_POST,
            "5001",
            limits=SyncLimits(1, 1, 10, 0.5),
        )
        assert result.status == "paused"
        assert result.budget_boundary == "time"
        assert result.request_count == 0
        assert requested == []
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 0
        )


def test_sync_mid_commit_failure_rolls_back_page_but_keeps_raw_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_pages: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_pages.append(request.url.params.get("page"))
        return _listing_handler()(request)

    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        service = _service(database, handler)
        original = service.page_writer.write_with_result
        writes = 0

        def fail_second_commit(*args: object, **kwargs: object):
            nonlocal writes
            writes += 1
            result = original(*args, **kwargs)
            if writes == 2:
                raise RuntimeError("simulated page interruption")
            return result

        monkeypatch.setattr(service.page_writer, "write_with_result", fail_second_commit)
        with pytest.raises(RuntimeError, match="local metadata persistence failed"):
            service.synchronize(
                AdapterOperation.LIST_ACCOUNT_POSTS,
                "artist_a",
                limits=SyncLimits(3, 3, 20, 20),
            )

        run = get_remote_run(database, 1)
        assert run is not None and run["status"] == "failed"
        assert (run["page_count"], run["record_count"]) == (1, 4)
        assert len(run["checkpoints"]) == 1
        assert run["checkpoints"][0]["last_page_identity"].endswith(":first")
        assert requested_pages == [None, "b5101"]
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 2
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM remote_requests").fetchone()[0] == 2
        )
        post_ids = {
            row[0] for row in database.connection.execute("SELECT native_post_id FROM posts")
        }
        assert post_ids == {"5101", "5102"}
        assert "5100" not in post_ids


def test_sync_reobservation_is_idempotent_while_raw_history_grows(
    tmp_path: Path,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _json_response(_body("normal_post"))

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        service = _service(database, handler)
        for _ in range(2):
            result = service.synchronize(
                AdapterOperation.FETCH_POST,
                "5001",
                limits=SyncLimits(1, 1, 10, 10),
            )
            assert result.status == "complete"
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM posts WHERE native_post_id = '5001'"
            ).fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM media_occurrences").fetchone()[0] == 1
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 2
        )


def test_sync_authenticated_request_keeps_credentials_out_of_durable_state(
    tmp_path: Path,
) -> None:
    username = "e621-test-user"
    api_key = "e621-test-api-key"
    seen_authorization: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_authorization.append(request.headers["authorization"])
        return _json_response(_body("normal_post"))

    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        result = _service(
            database,
            handler,
            credentials=E621Credentials(username, api_key),
        ).synchronize(
            AdapterOperation.FETCH_POST,
            "5001",
            limits=SyncLimits(1, 1, 10, 10),
        )
        assert result.status == "complete"
        assert seen_authorization and username not in seen_authorization[0]
        assert api_key not in seen_authorization[0]
        run = get_remote_run(database, result.remote_run_id)
        assert run is not None
        assert username not in repr(run)
        assert api_key not in repr(run)
        assert username not in repr(result)
        assert api_key not in repr(result)
        assert username.encode() not in path.read_bytes()
        assert api_key.encode() not in path.read_bytes()


def test_sync_pacing_floor_is_not_weakened_by_service_caller(tmp_path: Path) -> None:
    handler = _listing_handler()
    sleeps: list[float] = []
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        result = _service(
            database,
            handler,
            sleeps=sleeps,
            minimum_interval_seconds=0.0,
        ).synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "artist_a",
            limits=SyncLimits(3, 3, 20, 20),
        )
        assert result.status == "complete"
    # The service caller passed a 0s floor, but e621's >=1s provider floor still governs pacing.
    assert sleeps and max(sleeps) >= 1.0
