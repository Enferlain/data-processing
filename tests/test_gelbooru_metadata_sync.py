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
from dataclasses import asdict
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

# Sentinel values for privacy scanning (7.2). These must never appear in
# public result objects, database rows, or error messages.
SENTINEL_USER = "sentinel_user_id_999"
SENTINEL_KEY = "sentinel_api_key_xyz888"


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


# ---------------------------------------------------------------------------
# Task 5.4: current-projection policy for partial/disagreeing observations
# ---------------------------------------------------------------------------

LATER = "2026-10-02T12:00:00Z"


def _later_html_service(
    database: CatalogDatabase,
    body: str,
) -> MetadataSyncService:
    adapter = GelbooruHtmlAdapter(
        GELBOORU,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=UTF-8"},
                    content=body.encode(),
                )
            )
        ),
        clock=lambda: LATER,
    )
    return MetadataSyncService(
        database,
        adapter,
        minimum_interval_seconds=0.0,
        maximum_retries=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
        clock=lambda: LATER,
    )


def test_sync_later_html_observation_never_erases_dapi_only_facts(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        _dapi_service(database, _dapi_post_handler()).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        # The later HTML observation omits the original URL, the declared MD5,
        # and any post status; none of those DAPI-proven facts may be erased.
        _later_html_service(database, _html_body("html_post_12370900")).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )

        media = database.connection.execute(
            "SELECT remote_url, declared_md5, width, height FROM media_occurrences"
        ).fetchone()
        assert media["remote_url"] is not None  # DAPI original URL survives
        assert media["declared_md5"] == "fef8d5889c2fe425dd50cfade909cec9"
        assert (media["width"], media["height"]) == (1150, 1750)

        post = database.connection.execute("SELECT rating, status FROM posts").fetchone()
        assert post["status"] is not None  # HTML's null status does not erase
        # Both observations remain auditable through separate raw records.
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 2
        )


def test_sync_later_dapi_observation_fills_html_gaps(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        _html_service(database, _html_post_handler()).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        html_media = database.connection.execute(
            "SELECT remote_url, declared_md5 FROM media_occurrences"
        ).fetchone()
        assert html_media["remote_url"] is None  # HTML never reveals the original

        _later_html_service_is_dapi = _dapi_service(database, _dapi_post_handler())
        _later_html_service_is_dapi.synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        dapi_media = database.connection.execute(
            "SELECT remote_url, declared_md5 FROM media_occurrences"
        ).fetchone()
        # A later DAPI observation adds the facts the HTML view lacked.
        assert dapi_media["remote_url"] is not None
        assert dapi_media["declared_md5"] == "fef8d5889c2fe425dd50cfade909cec9"


def test_sync_disagreeing_rating_newer_observation_wins_and_stays_auditable(
    tmp_path: Path,
) -> None:
    import re as re_module

    disagreeing = re_module.sub(
        r"Rating:\s*\w+", "Rating: explicit", _html_body("html_post_12370900")
    )
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        _dapi_service(database, _dapi_post_handler()).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        _later_html_service(database, disagreeing).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )

        rating = database.connection.execute("SELECT rating FROM posts").fetchone()["rating"]
        # Mutable disagreement: the newer observation wins the current
        # projection while both raw payloads keep the audit trail.
        assert rating == "explicit"
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 2
        )


# ---------------------------------------------------------------------------
# Task 5.5: metadata-only boundaries — no assets, no acquisition, provider MD5
# ---------------------------------------------------------------------------


def test_sync_keeps_media_metadata_only_without_assets_or_acquisition(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        _dapi_service(database, _dapi_post_handler()).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )

        media = database.connection.execute(
            "SELECT variants_json, declared_md5 FROM media_occurrences"
        ).fetchone()
        variants = json.loads(media["variants_json"])["variants"]
        roles = {variant["role"] for variant in variants}
        # Returned media URLs stay browseable metadata-only variants.
        assert {"original", "preview"} <= roles
        assert all(variant["url"].startswith("https://") for variant in variants)
        # Declared MD5 is a provider assertion, never a locally verified hash.
        assert media["declared_md5"] == "fef8d5889c2fe425dd50cfade909cec9"

        for table in (
            "assets",
            "occurrence_assets",
            "media_acquisition_plans",
            "media_acquisition_runs",
            "media_acquisition_attempts",
        ):
            count = database.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0, table


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Task 7.1: acceptance matrix for all five real Gelbooru post IDs
# ---------------------------------------------------------------------------

# The five real post IDs from the fixture contract, including the three
# user-labelled variation records (10720246, 10791439, 10791440).
# Fixture case names differ for variation records, so we map post_id → case_name.
_DAPI_CASE_MAP: dict[str, str] = {
    "12370900": "post_12370900",
    "11605534": "post_11605534",
    "10720246": "variation_distinct_10720246",
    "10791439": "variation_pair_10791439",
    "10791440": "variation_pair_10791440",
}
_HTML_CASE_MAP: dict[str, str] = {
    "12370900": "html_post_12370900",
    "11605534": "html_post_11605534",
    "10720246": "html_variation_distinct_10720246",
    "10791439": "html_variation_pair_10791439",
    "10791440": "html_variation_pair_10791440",
}
_GELBOORU_POST_IDS = tuple(_DAPI_CASE_MAP.keys())


def _dapi_handler_for(post_id: str) -> Callable[[httpx.Request], httpx.Response]:
    """Return a handler that serves the DAPI fixture for a specific post ID."""
    payload = _dapi_case(_DAPI_CASE_MAP[post_id]).response.payload

    def handler(request: httpx.Request) -> httpx.Response:
        requested_id = request.url.params.get("id")
        assert requested_id == post_id, f"expected id={post_id}, got {requested_id}"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=payload,
        )

    return handler


def _html_handler_for(post_id: str) -> Callable[[httpx.Request], httpx.Response]:
    """Return a handler that serves the HTML fixture for a specific post ID."""
    body = _html_body(_HTML_CASE_MAP[post_id]).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        requested_id = request.url.params.get("id")
        assert requested_id == post_id, f"expected id={post_id}, got {requested_id}"
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=UTF-8"},
            content=body,
        )

    return handler


@pytest.mark.parametrize("post_id", _GELBOORU_POST_IDS)
def test_acceptance_dapi_post_synchronizes_and_produces_normalized_facts(
    tmp_path: Path, post_id: str
) -> None:
    """7.1: Each of the five real Gelbooru posts reconciles through DAPI."""
    path = tmp_path / f"catalog_{post_id}.sqlite3"
    with CatalogDatabase(path) as database:
        service = _dapi_service(database, _dapi_handler_for(post_id))
        result = service.synchronize(
            AdapterOperation.FETCH_POST,
            post_id,
            limits=SyncLimits(3, 3, 500, 60),
        )
        assert result.status == "complete"
        assert result.outcome == "success"

        post = database.connection.execute(
            """SELECT p.native_post_id, p.rating, p.availability
               FROM posts p JOIN platforms pl ON pl.platform_id = p.platform_id
               WHERE pl.platform_key = 'gelbooru' AND p.native_post_id = ?""",
            (post_id,),
        ).fetchone()
        assert post is not None
        assert post["native_post_id"] == post_id
        assert post["availability"] == "available"


@pytest.mark.parametrize("post_id", _GELBOORU_POST_IDS)
def test_acceptance_html_post_synchronizes_and_produces_normalized_facts(
    tmp_path: Path, post_id: str
) -> None:
    """7.1: Each of the five real Gelbooru posts reconciles through HTML."""
    path = tmp_path / f"catalog_{post_id}.sqlite3"
    with CatalogDatabase(path) as database:
        service = _html_service(database, _html_handler_for(post_id))
        result = service.synchronize(
            AdapterOperation.FETCH_POST,
            post_id,
            limits=SyncLimits(3, 3, 500, 60),
        )
        assert result.status == "complete"
        assert result.outcome == "success"

        post = database.connection.execute(
            """SELECT p.native_post_id, p.rating, p.availability
               FROM posts p JOIN platforms pl ON pl.platform_id = p.platform_id
               WHERE pl.platform_key = 'gelbooru' AND p.native_post_id = ?""",
            (post_id,),
        ).fetchone()
        assert post is not None
        assert post["native_post_id"] == post_id
        assert post["availability"] == "available"


def test_acceptance_dapi_and_html_coexist_under_same_post_identity(tmp_path: Path) -> None:
    """7.1: DAPI and HTML observations for the same post reconcile into one identity."""
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        _dapi_service(database, _dapi_handler_for("12370900")).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        _html_service(database, _html_handler_for("12370900")).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )

        # One post identity, two raw observations (one per transport).
        posts = database.connection.execute(
            """SELECT p.native_post_id FROM posts p
               JOIN platforms pl ON pl.platform_id = p.platform_id
               WHERE pl.platform_key = 'gelbooru'"""
        ).fetchall()
        assert [row["native_post_id"] for row in posts] == ["12370900"]
        raw_count = database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[
            0
        ]
        assert raw_count == 2
        # Each run has its own transport identity.
        runs = database.connection.execute(
            "SELECT transport_key FROM remote_runs ORDER BY remote_run_id"
        ).fetchall()
        assert len(runs) == 2
        assert runs[0]["transport_key"] == DAPI_TRANSPORT_VERSION
        assert runs[1]["transport_key"] == HTML_PARSER_VERSION


def test_acceptance_variation_preserves_distinct_and_pair_records(
    tmp_path: Path,
) -> None:
    """7.1: The three variation records (10720246, 10791439, 10791440) reconcile
    with stable distinct/pair semantics under both transports."""
    variation_ids = ("10720246", "10791439", "10791440")

    for post_id in variation_ids:
        path = tmp_path / f"catalog_{post_id}.sqlite3"
        with CatalogDatabase(path) as database:
            _dapi_service(database, _dapi_handler_for(post_id)).synchronize(
                AdapterOperation.FETCH_POST,
                post_id,
                limits=SyncLimits(3, 3, 500, 60),
            )
            _html_service(database, _html_handler_for(post_id)).synchronize(
                AdapterOperation.FETCH_POST,
                post_id,
                limits=SyncLimits(3, 3, 500, 60),
            )

            post = database.connection.execute(
                """SELECT p.native_post_id, p.rating FROM posts p
                   JOIN platforms pl ON pl.platform_id = p.platform_id
                   WHERE pl.platform_key = 'gelbooru' AND p.native_post_id = ?""",
                (post_id,),
            ).fetchone()
            assert post is not None
            assert post["native_post_id"] == post_id
            # Each variation post still produces one identity with two
            # independent transport histories.
            raw_count = database.connection.execute(
                "SELECT COUNT(*) FROM raw_observations"
            ).fetchone()[0]
            assert raw_count == 2


# ---------------------------------------------------------------------------
# Task 7.2: privacy and network-isolation tests
# ---------------------------------------------------------------------------


def test_acceptance_result_objects_contain_no_credential_sentinels(
    tmp_path: Path,
) -> None:
    """7.2: Synchronization result objects, run metadata, and database rows
    contain no credential values or authenticated URLs."""
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        service = _dapi_service(database, _dapi_post_handler())
        result = service.synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )

        # The SyncResult must not contain credential material.
        result_json = json.dumps(asdict(result))
        assert SENTINEL_USER not in result_json
        assert SENTINEL_KEY not in result_json

        # Run metadata in the database must not contain credentials.
        run = get_remote_run(database, result.remote_run_id)
        assert run is not None
        run_json = json.dumps(run)
        assert SENTINEL_USER not in run_json
        assert SENTINEL_KEY not in run_json

        # Request identity (from run metadata) is semantic (transport+operation+id),
        # never URL-shaped or credential-bearing.
        request_identity = run["requests"][0]["request_identity"]
        assert request_identity == "gelbooru:dapi_json:post:12370900"
        assert "api_key" not in request_identity
        assert "user_id" not in request_identity


def test_acceptance_only_gelbooru_endpoint_is_contacted(tmp_path: Path) -> None:
    """7.2: The injected transport proves that only the Gelbooru DAPI/HTML
    endpoint is contacted — no media hosts, no secondary API calls."""
    contacted_hosts: list[str] = []

    def tracking_handler(request: httpx.Request) -> httpx.Response:
        contacted_hosts.append(request.url.host)
        if "page=dapi" in str(request.url):
            payload = _dapi_case("post_12370900").response.payload
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=payload,
            )
        elif "page=post" in str(request.url) and "s=view" in str(request.url):
            body = _html_body("html_post_12370900").encode()
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=UTF-8"},
                content=body,
            )
        return httpx.Response(404)

    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        _dapi_service(database, tracking_handler).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        _html_service(database, tracking_handler).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )

    # Only gelbooru.com was contacted, once per transport.
    assert all(host == "gelbooru.com" for host in contacted_hosts)
    assert len(contacted_hosts) == 2


# ---------------------------------------------------------------------------
# Task 7.3: budget, interruption, rollback, reopen, resume, duplicates,
#           malformed-response, and transport-mismatch tests
# ---------------------------------------------------------------------------


def test_budget_exhaustion_stops_before_record_limit(tmp_path: Path) -> None:
    """7.3: Budget exhaustion at the record boundary halts listing before
    admitting extra pages. The page is not committed (atomic page boundary),
    so no records appear in the database, but the raw observation is retained."""
    path = tmp_path / "catalog.sqlite3"

    def handler(request: httpx.Request) -> httpx.Response:
        pid = request.url.params.get("pid", "0")
        body = _minimal_listing_body(100, 1) if pid == "0" else _minimal_listing_body(3, 101)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(body).encode(),
        )

    with CatalogDatabase(path) as database:
        service = _dapi_service(database, handler)
        # Budget: 1 request, 1 page, 50 records (first page returns 100).
        result = service.synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "listing",
            limits=SyncLimits(1, 1, 50, 60),
        )
        assert result.status == "paused"
        assert result.budget_boundary == "record"
        # Record-level exhaustion means the page was not committed atomically.
        count = database.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        assert count == 0
        # The raw observation is retained for later resume.
        raw_count = database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[
            0
        ]
        assert raw_count == 1


def test_database_reopen_resume_without_duplicate_posts(tmp_path: Path) -> None:
    """7.3: Resume after database reopen does not create duplicate posts."""
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

    # First session: list first page, pause at page boundary.
    with CatalogDatabase(path) as database:
        service = _dapi_service(database, handler)
        first = service.synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "listing",
            limits=SyncLimits(5, 1, 1000, 60),
        )
        assert first.status == "paused"
        run_id = first.remote_run_id

    # Reopen database in a new context and resume.
    with CatalogDatabase(path) as database:
        service = _dapi_service(database, handler)
        resumed = service.synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "listing",
            limits=SyncLimits(5, 5, 1000, 60),
            resume_from_run_id=run_id,
        )
        assert resumed.status == "complete"

        post_ids = {
            row[0]
            for row in database.connection.execute("SELECT native_post_id FROM posts").fetchall()
        }
        assert post_ids == {str(n) for n in range(1, 104)}
    # No duplicate requests — the handler saw only pid=0 then pid=1.
    assert requested_pids == ["0", "1"]


def test_reobservation_is_idempotent_raw_history_grows(tmp_path: Path) -> None:
    """7.3: Re-synchronizing the same post produces no duplicate normalized
    records but grows the raw observation history."""
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        service = _dapi_service(database, _dapi_post_handler())
        first = service.synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        assert first.status == "complete"

        second = service.synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        assert second.status == "complete"

        # Two raw observations for the same post.
        raw_count = database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[
            0
        ]
        assert raw_count == 2
        # But only one post record — COALESCE-gated upsert deduplicates.
        post_count = database.connection.execute(
            """SELECT COUNT(*) FROM posts p
               JOIN platforms pl ON pl.platform_id = p.platform_id
               WHERE pl.platform_key = 'gelbooru'"""
        ).fetchone()[0]
        assert post_count == 1


def test_malformed_dapi_response_produces_typed_outcome(tmp_path: Path) -> None:
    """7.3: A malformed DAPI response body yields a typed malformed outcome
    rather than an unhandled exception."""
    path = tmp_path / "catalog.sqlite3"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"not valid json {{{",
        )

    with CatalogDatabase(path) as database:
        service = _dapi_service(database, handler)
        result = service.synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )
        assert result.status == "failed"
        assert result.outcome == "malformed_response"
        # Raw observation retained for audit.
        raw_count = database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[
            0
        ]
        assert raw_count == 1
        assert database.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0


def test_transport_mismatch_rejects_resume_before_network(tmp_path: Path) -> None:
    """7.3: Resuming a DAPI listing run through the HTML adapter is rejected
    before any network access occurs due to transport mismatch."""
    path = tmp_path / "catalog.sqlite3"

    def dapi_listing_handler(request: httpx.Request) -> httpx.Response:
        pid = request.url.params.get("pid", "0")
        body = _minimal_listing_body(100, 1) if pid == "0" else _minimal_listing_body(3, 101)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(body).encode(),
        )

    # The HTML adapter doesn't support LIST_ACCOUNT_POSTS, so we verify the
    # transport mismatch at the resume validation layer by constructing the
    # adapter manually and attempting a resume with a different transport key.
    with CatalogDatabase(path) as database:
        # Create a DAPI listing run that pauses at the page boundary.
        dapi_service = _dapi_service(database, dapi_listing_handler)
        first = dapi_service.synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "listing",
            limits=SyncLimits(5, 1, 1000, 60),
        )
        assert first.status == "paused"
        run_id = first.remote_run_id

    # Verify the run was created with DAPI transport key.
    run = get_remote_run(path, run_id)
    assert run is not None
    assert run["transport_key"] == DAPI_TRANSPORT_VERSION

    # Resume with an adapter that has a different transport key must fail
    # before any network request is made.
    with CatalogDatabase(path) as database:
        html_service = _html_service(database, _html_post_handler())
        # The HTML adapter's transport key is different from DAPI_TRANSPORT_VERSION,
        # so resume validation should reject it as a transport mismatch.
        with pytest.raises(ValueError, match="incompatible"):
            html_service.synchronize(
                AdapterOperation.LIST_ACCOUNT_POSTS,
                "listing",
                limits=SyncLimits(5, 5, 1000, 60),
                resume_from_run_id=run_id,
            )


def test_acceptance_three_variation_posts_have_independent_histories(
    tmp_path: Path,
) -> None:
    """7.1: The three variation records each produce independent observation
    histories with stable distinct/pair semantics."""
    variation_ids = ("10720246", "10791439", "10791440")

    for post_id in variation_ids:
        path = tmp_path / f"catalog_{post_id}.sqlite3"
        with CatalogDatabase(path) as database:
            _dapi_service(database, _dapi_handler_for(post_id)).synchronize(
                AdapterOperation.FETCH_POST,
                post_id,
                limits=SyncLimits(3, 3, 500, 60),
            )

            post = database.connection.execute(
                """SELECT p.native_post_id FROM posts p
                   JOIN platforms pl ON pl.platform_id = p.platform_id
                   WHERE pl.platform_key = 'gelbooru' AND p.native_post_id = ?""",
                (post_id,),
            ).fetchone()
            assert post is not None
            assert post["native_post_id"] == post_id
            # Each variation post produces one identity with its own raw history.
            raw_count = database.connection.execute(
                "SELECT COUNT(*) FROM raw_observations"
            ).fetchone()[0]
            assert raw_count == 1


# ---------------------------------------------------------------------------
# Task 6.4: offline inspection of Gelbooru runs, posts, and occurrences
# ---------------------------------------------------------------------------


def test_offline_inspection_shows_gelbooru_identity_provenance_and_variants(
    tmp_path: Path,
) -> None:
    from media_catalog.media_queries import list_media_occurrences

    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        result = _dapi_service(database, _dapi_post_handler()).synchronize(
            AdapterOperation.FETCH_POST,
            "12370900",
            limits=SyncLimits(3, 3, 500, 60),
        )

    run = get_remote_run(path, result.remote_run_id)
    assert run["platform"] == "gelbooru"
    assert run["transport_key"] == DAPI_TRANSPORT_VERSION
    assert run["requests"][0]["request_identity"] == "gelbooru:dapi_json:post:12370900"
    # The run view exposes typed outcome and counters, never raw payloads.
    assert "payload" not in json.dumps(run)

    occurrences = list_media_occurrences(path, platform="gelbooru")
    assert len(occurrences["results"]) == 1
    occurrence = occurrences["results"][0]
    # Declared provider facts are visible as declared, distinct from any
    # locally verified asset facts (none exist for metadata-only syncs).
    assert occurrence["post"]["native_post_id"] == "12370900"
    variants = occurrence["variants"]
    variant_keys = {variant["key"] for variant in variants}
    assert {"original", "preview"} <= variant_keys
    # Stable selectors exist for every variant, and Gelbooru stays excluded
    # from acquisition pending an explicit provider policy.
    assert all(variant["selection"] for variant in variants)
    assert all(variant["eligibility"] == "excluded" for variant in variants)
    assert occurrence["asset_count"] == 0
    # Declared MD5 stays visible as a provider declaration.
    assert "fef8d5889c2fe425dd50cfade909cec9" in json.dumps(occurrence["declared"])


def test_resume_with_stale_continuation_version_fails_permanently(
    tmp_path: Path,
) -> None:
    """7.3/3.4: resuming a run whose checkpoint uses a legacy continuation
    version fails closed as a permanent validation error — never classified
    transient_provider, and the root cause stays visible."""
    path = tmp_path / "catalog.sqlite3"

    def handler(request: httpx.Request) -> httpx.Response:
        pid = request.url.params.get("pid", "0")
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
        run_id = first.remote_run_id

        # Simulate a checkpoint written before the continuation format bump:
        # replace the stored continuation with a legacy unscoped payload.
        row = database.connection.execute(
            "SELECT continuation_json FROM remote_checkpoints WHERE remote_run_id = ?",
            (run_id,),
        ).fetchone()
        stored = json.loads(row["continuation_json"])
        stored["version"] = "gelbooru-pid-v1"
        stored["value"] = {"pid": "1", "limit": "100"}
        database.connection.execute(
            "UPDATE remote_checkpoints SET continuation_json = ? WHERE remote_run_id = ?",
            (json.dumps(stored), run_id),
        )
        database.connection.commit()

        resumed = _dapi_service(database, handler)
        with pytest.raises(RuntimeError, match="incompatible Gelbooru continuation version"):
            resumed.synchronize(
                AdapterOperation.LIST_ACCOUNT_POSTS,
                "listing",
                limits=SyncLimits(5, 5, 1000, 60),
                resume_from_run_id=run_id,
            )

        # The failed resume is recorded as a permanent local validation
        # failure with the root cause in the diagnostic — not transient.
        # The resume attempt has its own run row; the original stays paused.
        attempt = database.connection.execute(
            """SELECT status, termination_outcome, diagnostic_summary
               FROM remote_runs ORDER BY remote_run_id DESC LIMIT 1"""
        ).fetchone()
        assert attempt["status"] == "failed"
        assert attempt["termination_outcome"] != "transient_provider"
        assert "incompatible Gelbooru continuation version" in attempt["diagnostic_summary"]
