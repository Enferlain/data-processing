from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import LookupStrategy
from media_catalog.adapters.e621 import E621, E621Adapter, E621Credentials, E621Instance
from media_catalog.candidate_lookup import (
    CandidateLookupService,
    LookupLimits,
    get_lookup_run,
)
from media_catalog.database import CatalogDatabase
from media_catalog.discovery import DiscoveryService
from media_catalog.records import AccountRecord, PostRecord
from media_catalog.writer import CatalogWriter

NOW = "2026-08-13T00:00:00Z"
PIXIV_URL = "https://www.pixiv.net/artworks/9001"
SOURCE_MD5 = "abcdef0123456789abcdef0123456789"


def _post_payload(post_id: int, *, source: str = PIXIV_URL) -> dict[str, object]:
    return {
        "id": post_id,
        "sources": [source],
        "uploader_id": 42,
        "file": {
            "md5": SOURCE_MD5,
            "ext": "jpg",
            "size": 10,
            "width": 20,
            "height": 30,
            "url": None,
        },
        "tags": {"artist": ["artist_a"], "general": ["solo"]},
        "flags": {"deleted": False},
    }


def _alias_payload(*, status: str = "active") -> list[dict[str, object]]:
    return [
        {
            "id": 8001,
            "antecedent_name": "artist_old",
            "consequent_name": "artist_canonical",
            "status": status,
            "post_count": 12,
        }
    ]


def _adapter(
    handler,
    *,
    page_size: int = 320,
    credentials: E621Credentials | None = None,
) -> E621Adapter:
    return E621Adapter(
        E621Instance(page_size=page_size),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        credentials=credentials,
        clock=lambda: NOW,
    )


def _service(database: CatalogDatabase, adapter: E621Adapter, *, monotonic=None):
    return CandidateLookupService(
        database,
        adapter,
        minimum_interval_seconds=0,
        maximum_retries=0,
        monotonic=monotonic or (lambda: 0.0),
        sleep=lambda _seconds: None,
        clock=lambda: NOW,
    )


def _seed_pixiv_post(database: CatalogDatabase) -> int:
    with database.transaction():
        return (
            CatalogWriter(database)
            .upsert_post(PostRecord("pixiv", "9001", NOW, canonical_url=PIXIV_URL))
            .id
        )


def _seed_x_account(database: CatalogDatabase) -> int:
    with database.transaction():
        return CatalogWriter(database).upsert_account(AccountRecord("x", "900", NOW)).id


def test_e621_service_persists_post_and_alias_evidence_with_raw_provenance(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/posts.json":
            return httpx.Response(200, json=[_post_payload(5001)], request=request)
        return httpx.Response(200, json=_alias_payload(), request=request)

    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        post_id = _seed_pixiv_post(database)
        account_id = _seed_x_account(database)
        adapter = _adapter(transport, credentials=E621Credentials("e621-user", "secret-key"))
        service = _service(database, adapter)

        post_plan = service.plan(
            f"post:{post_id}",
            (LookupStrategy.SOURCE_POST_URL,),
            limits=LookupLimits(requests=1, pages=1, results=10, seconds=30),
        )
        post_result = service.execute(post_plan)[0]
        assert post_result.status == "complete"
        assert post_result.result_count == 1

        alias_plan = service.plan(
            f"account:{account_id}",
            (LookupStrategy.ARTIST_ALIAS,),
            limits=LookupLimits(requests=1, pages=1, results=10, seconds=30),
            search_term="artist_old",
        )
        alias_result = service.execute(alias_plan)[0]
        assert alias_result.status == "complete"
        assert alias_result.result_count == 1

        post_row = database.connection.execute(
            """SELECT result_kind, raw_observation_id, post_candidate_id
               FROM candidate_lookup_results WHERE candidate_lookup_run_id = ?""",
            (post_result.candidate_lookup_run_id,),
        ).fetchone()
        assert post_row["result_kind"] == "post_match"
        assert post_row["post_candidate_id"] is not None
        retained = database.connection.execute(
            """SELECT payload FROM raw_observations
               JOIN raw_payloads USING(raw_payload_id)
              WHERE raw_observation_id = ?""",
            (post_row["raw_observation_id"],),
        ).fetchone()[0]
        assert PIXIV_URL.encode() in retained
        provenance = database.connection.execute(
            """SELECT p.raw_observation_id, m.raw_observation_id
               FROM posts p JOIN media_occurrences m USING(post_id)
              WHERE p.native_post_id = '5001'"""
        ).fetchone()
        assert tuple(provenance) == (
            post_row["raw_observation_id"],
            post_row["raw_observation_id"],
        )

        alias_row = database.connection.execute(
            """SELECT result_kind, raw_observation_id, account_candidate_id
               FROM candidate_lookup_results WHERE candidate_lookup_run_id = ?""",
            (alias_result.candidate_lookup_run_id,),
        ).fetchone()
        assert alias_row["result_kind"] == "weak_lead"
        assert alias_row["account_candidate_id"] is None
        assert (
            database.connection.execute(
                """SELECT COUNT(*) FROM tag_alias_observations
               WHERE raw_observation_id = ? AND status = 'active'""",
                (alias_row["raw_observation_id"],),
            ).fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute(
                """SELECT COUNT(*) FROM attribution_snapshots WHERE raw_observation_id = ?""",
                (alias_row["raw_observation_id"],),
            ).fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM post_candidate_decisions").fetchone()[
                0
            ]
            == 0
        )
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM account_candidate_decisions"
            ).fetchone()[0]
            == 0
        )

    assert len(requests) == 2
    assert all(request.url.host == "e621.net" for request in requests)
    assert all(request.headers["user-agent"] == E621.user_agent for request in requests)

    public = json.dumps(get_lookup_run(path, post_result.candidate_lookup_run_id))
    assert PIXIV_URL not in public
    assert "secret-key" not in public
    assert "source:" not in public


@pytest.mark.parametrize(
    ("boundary", "limits", "payload_count"),
    [
        ("request", LookupLimits(requests=1, pages=2, results=10, seconds=30), 1),
        ("page", LookupLimits(requests=2, pages=1, results=10, seconds=30), 1),
        ("result", LookupLimits(requests=2, pages=2, results=1, seconds=30), 2),
    ],
)
def test_e621_service_does_not_send_an_unadmitted_next_request(
    tmp_path: Path,
    boundary: str,
    limits: LookupLimits,
    payload_count: int,
) -> None:
    requested: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(
            200,
            json=[_post_payload(5001 + index) for index in range(payload_count)],
            request=request,
        )

    path = tmp_path / f"catalog-{boundary}.sqlite3"
    with CatalogDatabase(path) as database:
        post_id = _seed_pixiv_post(database)
        adapter = _adapter(transport, page_size=1 if boundary in {"request", "page"} else 320)
        service = _service(database, adapter)
        result = service.execute(
            service.plan(
                f"post:{post_id}",
                (LookupStrategy.SOURCE_POST_URL,),
                limits=limits,
            )
        )[0]

        assert result.status == "paused"
        assert result.budget_boundary == boundary
        assert len(requested) == 1
        assert result.request_count == 1
        if boundary == "result":
            assert result.page_count == 0
            assert result.result_count == 0
        else:
            assert result.page_count == 1
            assert result.result_count == 1


def test_e621_time_budget_is_checked_before_page_commit(tmp_path: Path) -> None:
    requested = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested += 1
        return httpx.Response(200, json=[_post_payload(5001)], request=request)

    tick_values = [0.0, 0.0, 100.0]
    tick_index = 0

    def monotonic() -> float:
        nonlocal tick_index
        value = tick_values[min(tick_index, len(tick_values) - 1)]
        tick_index += 1
        return value

    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        post_id = _seed_pixiv_post(database)
        adapter = _adapter(transport)
        service = _service(database, adapter, monotonic=monotonic)
        result = service.execute(
            service.plan(
                f"post:{post_id}",
                (LookupStrategy.SOURCE_POST_URL,),
                limits=LookupLimits(requests=2, pages=2, results=10, seconds=1),
            )
        )[0]
        assert result.status == "paused"
        assert result.budget_boundary == "time"
        assert requested == 1
        assert result.page_count == 0
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM posts WHERE native_post_id = '5001'"
            ).fetchone()[0]
            == 0
        )


def test_e621_retry_retains_both_raw_attempts_but_commits_one_result(tmp_path: Path) -> None:
    attempts = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"message": "retry"}, request=request)
        return httpx.Response(200, json=[_post_payload(5001)], request=request)

    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        post_id = _seed_pixiv_post(database)
        adapter = _adapter(transport)
        service = CandidateLookupService(
            database,
            adapter,
            minimum_interval_seconds=0,
            maximum_retries=1,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        )
        result = service.execute(
            service.plan(
                f"post:{post_id}",
                (LookupStrategy.SOURCE_POST_URL,),
                limits=LookupLimits(2, 1, 10, 30),
            )
        )[0]

        assert result.status == "complete"
        assert result.request_count == 2
        assert result.result_count == 1
        assert attempts == 2
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM candidate_lookup_requests"
            ).fetchone()[0]
            == 2
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 2
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM candidate_lookup_results").fetchone()[
                0
            ]
            == 1
        )
        assert database.connection.execute("SELECT COUNT(*) FROM match_evidence").fetchone()[0] == 1


def test_e621_full_page_checkpoint_resumes_at_committed_b_id_without_duplicates(
    tmp_path: Path,
) -> None:
    requested: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if len(requested) == 1:
            return httpx.Response(
                200,
                json=[_post_payload(5002), _post_payload(5001)],
                request=request,
            )
        return httpx.Response(200, json=[], request=request)

    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        post_id = _seed_pixiv_post(database)
        adapter = _adapter(transport, page_size=2)
        service = _service(database, adapter)
        plan = service.plan(
            f"post:{post_id}",
            (LookupStrategy.SOURCE_POST_URL,),
            limits=LookupLimits(requests=1, pages=2, results=10, seconds=30),
        )
        paused = service.execute(plan)[0]
        assert paused.status == "paused"
        assert paused.budget_boundary == "request"
        checkpoint = database.connection.execute(
            "SELECT continuation_json, page_count, result_count FROM candidate_lookup_checkpoints"
        ).fetchone()
        assert json.loads(checkpoint[0])["page"] == "b5001"
        assert tuple(checkpoint[1:]) == (1, 2)

        resumed = service.resume(
            paused.candidate_lookup_run_id,
            limits=LookupLimits(requests=1, pages=2, results=10, seconds=30),
        )
        assert resumed.status == "complete"
        assert resumed.predecessor_run_id == paused.candidate_lookup_run_id
        assert "page=b5001" in requested[1]
        assert (
            database.connection.execute(
                """SELECT COUNT(*) FROM posts
                   WHERE platform_id = (
                       SELECT platform_id FROM platforms WHERE platform_key = 'e621'
                   )"""
            ).fetchone()[0]
            == 2
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM candidate_lookup_results").fetchone()[
                0
            ]
            == 2
        )
        assert database.connection.execute("SELECT COUNT(*) FROM match_evidence").fetchone()[0] == 2

        with pytest.raises(ValueError, match="not resumable"):
            service.resume(resumed.candidate_lookup_run_id, limits=LookupLimits(1, 1, 10, 30))


def test_e621_stale_seed_is_rejected_before_run_or_network(tmp_path: Path) -> None:
    requested = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested += 1
        return httpx.Response(200, json=[_post_payload(5001)], request=request)

    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        post_id = _seed_pixiv_post(database)
        adapter = _adapter(transport)
        service = _service(database, adapter)
        plan = service.plan(
            f"post:{post_id}",
            (LookupStrategy.SOURCE_POST_URL,),
            limits=LookupLimits(1, 1, 10, 30),
        )
        with database.transaction():
            database.connection.execute(
                "UPDATE posts SET canonical_url = ? WHERE post_id = ?",
                ("https://www.pixiv.net/artworks/9002", post_id),
            )
        with pytest.raises(ValueError, match="stale"):
            service.execute(plan)
        assert requested == 0
        assert (
            database.connection.execute("SELECT COUNT(*) FROM candidate_lookup_runs").fetchone()[0]
            == 0
        )


def test_e621_reobservation_preserves_rejected_candidate_state(tmp_path: Path) -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_post_payload(5001)], request=request)

    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        post_id = _seed_pixiv_post(database)
        adapter = _adapter(transport)
        service = _service(database, adapter)
        limits = LookupLimits(1, 1, 10, 30)
        first = service.execute(
            service.plan(f"post:{post_id}", (LookupStrategy.SOURCE_POST_URL,), limits=limits)
        )[0]
        candidate_id = database.connection.execute(
            "SELECT post_candidate_id FROM post_match_candidates"
        ).fetchone()[0]
        reviewed = DiscoveryService(database).review(f"post:{candidate_id}", "rejected")
        assert reviewed["decision"] == "rejected"

        second = service.execute(
            service.plan(f"post:{post_id}", (LookupStrategy.SOURCE_POST_URL,), limits=limits)
        )[0]
        assert second.status == "complete"
        candidate = database.connection.execute(
            "SELECT current_state FROM post_match_candidates WHERE post_candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        assert candidate[0] == "rejected"
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM post_candidate_decisions WHERE post_candidate_id = ?",
                (candidate_id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM post_match_candidates").fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM posts WHERE native_post_id = '5001'"
            ).fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute(
                """SELECT COUNT(*) FROM media_occurrences
               WHERE post_id = (SELECT post_id FROM posts WHERE native_post_id = '5001')"""
            ).fetchone()[0]
            == 1
        )
        assert first.result_count == second.result_count == 1


def test_e621_service_drops_unapproved_alias_before_persisting_attribution(
    tmp_path: Path,
) -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_alias_payload(status="deleted"), request=request)

    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        account_id = _seed_x_account(database)
        adapter = _adapter(transport)
        service = _service(database, adapter)
        result = service.execute(
            service.plan(
                f"account:{account_id}",
                (LookupStrategy.ARTIST_ALIAS,),
                limits=LookupLimits(1, 1, 10, 30),
                search_term="artist_old",
            )
        )[0]

        assert result.status == "complete"
        assert result.result_count == 0
        assert (
            database.connection.execute("SELECT COUNT(*) FROM tag_alias_observations").fetchone()[0]
            == 0
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM attribution_entities").fetchone()[0]
            == 0
        )
