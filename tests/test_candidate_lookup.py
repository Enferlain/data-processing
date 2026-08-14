from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import LookupStrategy
from media_catalog.adapters.danbooru import AIBOORU, DANBOORU, DanbooruAdapter
from media_catalog.candidate_lookup import (
    CandidateLookupService,
    LookupLimits,
    get_lookup_run,
    list_lookup_runs,
    plan_candidate_lookup,
)
from media_catalog.database import CatalogDatabase, current_schema_version
from media_catalog.discovery import DiscoveryService
from media_catalog.records import AccountRecord, AssetRecord, MediaOccurrenceRecord, PostRecord
from media_catalog.writer import CatalogWriter


def _seed_post(database: CatalogDatabase) -> int:
    with database.transaction():
        return (
            CatalogWriter(database)
            .upsert_post(
                PostRecord(
                    "x",
                    "1837662117949800671",
                    "2026-08-11T00:00:00Z",
                    canonical_url="https://x.com/thiccwithaq/status/1837662117949800671",
                )
            )
            .id
        )


def _lookup_payload() -> bytes:
    return json.dumps(
        [
            {
                "id": 8186581,
                "source": "https://twitter.com/thiccwithaq/status/1837662117949800671",
                "md5": "072b69605a05873a2443626b7600ed69",
                "tag_string_artist": "nyantcha",
                "tag_string_character": "",
                "tag_string_copyright": "",
                "tag_string_general": "",
                "tag_string_meta": "",
                "is_deleted": False,
            }
        ]
    ).encode()


def test_plan_is_read_only_redacted_and_bounded(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        post_id = _seed_post(database)
    before = path.read_bytes()
    plan = plan_candidate_lookup(
        path,
        f"post:{post_id}",
        DANBOORU,
        (LookupStrategy.SOURCE_POST_URL, LookupStrategy.VERIFIED_MD5),
        limits=LookupLimits(requests=2, pages=2, results=10, seconds=30),
    )
    assert path.read_bytes() == before
    assert len(plan.items) == 1
    assert plan.items[0].material.values == (
        "https://x.com/thiccwithaq/status/1837662117949800671",
        "https://twitter.com/thiccwithaq/status/1837662117949800671",
    )
    public = json.dumps(plan.as_dict())
    assert "thiccwithaq" not in public
    assert plan.exclusions == ({"strategy": "verified_md5", "reason": "missing_seed_material"},)


def test_unsupported_strategy_is_excluded_through_neutral_context(tmp_path: Path) -> None:
    # OpenSpec task 5.1: unsupported-strategy exclusions now consult the neutral
    # planning context's capabilities rather than a provider-specific instance.
    # AIBooru does not support artist_text, so it is excluded without a request.
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database, database.transaction():
        account_id = (
            CatalogWriter(database)
            .upsert_account(AccountRecord("x", "900", "2026-08-11T00:00:00Z"))
            .id
        )
    plan = plan_candidate_lookup(
        path,
        f"account:{account_id}",
        AIBOORU,
        (LookupStrategy.ARTIST_TEXT,),
        limits=LookupLimits(1, 1, 10, 30),
        search_term="anything",
    )
    assert plan.provider == "aibooru"
    assert plan.items == ()
    assert plan.exclusions == (
        {"strategy": "artist_text", "reason": "unsupported_provider_capability"},
    )
    assert plan.digest


def test_lookup_executes_persists_and_never_decides(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = _lookup_payload() if "twitter.com" in str(request.url) else b"[]"
        return httpx.Response(
            200,
            content=payload,
            headers={"content-type": "application/json"},
        )

    with (
        CatalogDatabase(path) as database,
        httpx.Client(transport=httpx.MockTransport(transport)) as client,
    ):
        post_id = _seed_post(database)
        adapter = DanbooruAdapter(DANBOORU, client=client)
        service = CandidateLookupService(
            database,
            adapter,
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
        )
        plan = service.plan(
            f"post:{post_id}",
            (LookupStrategy.SOURCE_POST_URL,),
            limits=LookupLimits(requests=2, pages=2, results=10, seconds=30),
        )
        result = service.execute(plan)[0]
        assert result.status == "complete"
        assert result.result_count == 1
        assert (
            database.connection.execute("SELECT COUNT(*) FROM candidate_lookup_results").fetchone()[
                0
            ]
            == 1
        )
        candidate = database.connection.execute(
            "SELECT relation_kind, current_state FROM post_match_candidates"
        ).fetchone()
        assert tuple(candidate) == ("sourced_from", "pending")
        assert (
            database.connection.execute("SELECT COUNT(*) FROM post_candidate_decisions").fetchone()[
                0
            ]
            == 0
        )
        run_id = result.candidate_lookup_run_id

    assert len(requests) == 2
    assert {request.url.path for request in requests} == {"/posts.json"}
    detail = get_lookup_run(path, run_id)
    assert detail is not None
    rendered = json.dumps(detail)
    assert "thiccwithaq" not in rendered
    assert "twitter.com" not in rendered
    assert list_lookup_runs(path)["count"] == 1


def test_schema_seven_constraints_and_upgrade(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        assert database.schema_version == current_schema_version()
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                """INSERT INTO candidate_lookup_runs (
                       platform_id, strategy, strategy_version, adapter_version, schema_version,
                       seed_revision, plan_digest, query_kind, material_digest,
                       private_query_json, request_limit, page_limit, result_limit,
                       time_limit_seconds, started_at
                   ) VALUES (
                       1, 'not_real', 'x', 'x', 'x', 'x', ?, 'x', ?, '{}', 1, 1, 1, 1, 'x'
                   )""",
                ("a" * 64, "b" * 64),
            )


@pytest.mark.parametrize(
    "urls, expected_candidates",
    [([], 0), ([{"url": "https://www.pixiv.net/users/77"}], 1)],
)
def test_artist_lookup_keeps_names_weak_but_recognizes_stable_urls(
    tmp_path: Path,
    urls: list[dict[str, str]],
    expected_candidates: int,
) -> None:
    path = tmp_path / "catalog.sqlite3"
    payload = json.dumps(
        [
            {
                "id": 12,
                "name": "possible_artist",
                "other_names": ["possible alias"],
                "urls": urls,
                "is_active": True,
            }
        ]
    ).encode()

    def transport(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"content-type": "application/json"})

    with (
        CatalogDatabase(path) as database,
        httpx.Client(transport=httpx.MockTransport(transport)) as client,
    ):
        with database.transaction():
            account_id = (
                CatalogWriter(database)
                .upsert_account(AccountRecord("x", "900", "2026-08-11T00:00:00Z"))
                .id
            )
        service = CandidateLookupService(
            database,
            DanbooruAdapter(DANBOORU, client=client),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
        )
        plan = service.plan(
            f"account:{account_id}",
            (LookupStrategy.ARTIST_EXACT_NAME,),
            limits=LookupLimits(1, 1, 10, 30),
            search_term="possible_artist",
        )
        result = service.execute(plan)[0]
        assert result.status == "complete"
        assert (
            database.connection.execute("SELECT COUNT(*) FROM account_match_candidates").fetchone()[
                0
            ]
            == expected_candidates
        )
        kind = database.connection.execute(
            "SELECT result_kind FROM candidate_lookup_results"
        ).fetchone()[0]
        assert kind == ("account_match" if expected_candidates else "weak_lead")
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM account_candidate_decisions"
            ).fetchone()[0]
            == 0
        )


def test_lookup_resume_starts_from_last_committed_alias_page(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    requested: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        payload = _lookup_payload() if "twitter.com" in str(request.url) else b"[]"
        return httpx.Response(200, content=payload, headers={"content-type": "application/json"})

    with (
        CatalogDatabase(path) as database,
        httpx.Client(transport=httpx.MockTransport(transport)) as client,
    ):
        post_id = _seed_post(database)
        service = CandidateLookupService(
            database,
            DanbooruAdapter(DANBOORU, client=client),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
        )
        plan = service.plan(
            f"post:{post_id}",
            (LookupStrategy.SOURCE_POST_URL,),
            limits=LookupLimits(1, 2, 10, 30),
        )
        paused = service.execute(plan)[0]
        assert paused.status == "paused"
        assert paused.budget_boundary == "request"
        resumed = service.resume(paused.candidate_lookup_run_id, limits=LookupLimits(1, 1, 10, 30))
        assert resumed.status == "complete"
        assert resumed.predecessor_run_id == paused.candidate_lookup_run_id
        assert len(requested) == 2
        assert "x.com" in requested[0]
        assert "twitter.com" in requested[1]
        assert (
            database.connection.execute("SELECT COUNT(*) FROM post_match_candidates").fetchone()[0]
            == 1
        )


def test_source_and_verified_hash_strengthen_one_pending_candidate(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"

    def transport(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_lookup_payload(),
            headers={"content-type": "application/json"},
        )

    with (
        CatalogDatabase(path) as database,
        httpx.Client(transport=httpx.MockTransport(transport)) as client,
    ):
        post_id = _seed_post(database)
        with database.transaction():
            writer = CatalogWriter(database)
            occurrence_id = writer.upsert_media(
                post_id,
                MediaOccurrenceRecord(
                    "x:0",
                    0,
                    "image",
                    observed_at="2026-08-11T00:00:00Z",
                ),
            ).id
            writer.link_asset(
                occurrence_id,
                AssetRecord(
                    "a" * 64,
                    "072b69605a05873a2443626b7600ed69",
                    None,
                    10,
                    "managed",
                    None,
                    "2026-08-11T00:00:00Z",
                    "sha256-stream-v1",
                ),
            )
        service = CandidateLookupService(
            database,
            DanbooruAdapter(DANBOORU, client=client),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
        )
        for strategy in (LookupStrategy.VERIFIED_MD5, LookupStrategy.SOURCE_POST_URL):
            plan = service.plan(
                f"post:{post_id}",
                (strategy,),
                limits=LookupLimits(3, 3, 10, 30),
            )
            assert service.execute(plan)[0].status == "complete"
        candidate = database.connection.execute(
            """SELECT post_candidate_id, relation_kind, current_state, evidence_generation
               FROM post_match_candidates"""
        ).fetchone()
        assert candidate["relation_kind"] == "sourced_from"
        assert candidate["current_state"] == "pending"
        assert candidate["evidence_generation"] == 2
        assert (
            database.connection.execute(
                """SELECT COUNT(*) FROM post_candidate_characteristics
               WHERE characteristic = 'exact_bytes'"""
            ).fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM post_candidate_decisions").fetchone()[
                0
            ]
            == 0
        )


def test_stale_plan_is_rejected_before_network_or_run_creation(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    requests = 0

    def transport(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, content=b"[]")

    with (
        CatalogDatabase(path) as database,
        httpx.Client(transport=httpx.MockTransport(transport)) as client,
    ):
        post_id = _seed_post(database)
        service = CandidateLookupService(
            database,
            DanbooruAdapter(DANBOORU, client=client),
            minimum_interval_seconds=0,
        )
        plan = service.plan(
            f"post:{post_id}",
            (LookupStrategy.SOURCE_POST_URL,),
            limits=LookupLimits(1, 1, 10, 30),
        )
        with database.transaction():
            database.connection.execute(
                "UPDATE posts SET canonical_url = ? WHERE post_id = ?",
                ("https://x.com/changed/status/1837662117949800671", post_id),
            )
        with pytest.raises(ValueError, match="stale"):
            service.execute(plan)
        assert requests == 0
        assert (
            database.connection.execute("SELECT COUNT(*) FROM candidate_lookup_runs").fetchone()[0]
            == 0
        )


def test_new_lookup_evidence_preserves_rejected_review(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    request_number = 0

    def transport(_request: httpx.Request) -> httpx.Response:
        nonlocal request_number
        request_number += 1
        body = json.loads(_lookup_payload())
        body[0]["score"] = request_number
        return httpx.Response(
            200,
            content=json.dumps(body).encode(),
            headers={"content-type": "application/json"},
        )

    with (
        CatalogDatabase(path) as database,
        httpx.Client(transport=httpx.MockTransport(transport)) as client,
    ):
        post_id = _seed_post(database)
        service = CandidateLookupService(
            database,
            DanbooruAdapter(DANBOORU, client=client),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
        )
        for run_number in range(2):
            plan = service.plan(
                f"post:{post_id}",
                (LookupStrategy.SOURCE_POST_URL,),
                limits=LookupLimits(2, 2, 10, 30),
            )
            assert service.execute(plan)[0].status == "complete"
            if run_number == 0:
                candidate_id = database.connection.execute(
                    "SELECT post_candidate_id FROM post_match_candidates"
                ).fetchone()[0]
                DiscoveryService(database).review(f"post:{candidate_id}", "rejected")
        candidate = database.connection.execute(
            """SELECT current_state, evidence_generation
               FROM post_match_candidates WHERE post_candidate_id = ?""",
            (candidate_id,),
        ).fetchone()
        assert candidate["current_state"] == "rejected"
        assert candidate["evidence_generation"] == 4
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM post_candidate_decisions WHERE post_candidate_id = ?",
                (candidate_id,),
            ).fetchone()[0]
            == 1
        )


def test_complete_lookup_run_cannot_be_resumed(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"

    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"[]", request=request)

    with (
        CatalogDatabase(path) as database,
        httpx.Client(transport=httpx.MockTransport(transport)) as client,
    ):
        post_id = _seed_post(database)
        service = CandidateLookupService(
            database,
            DanbooruAdapter(DANBOORU, client=client),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
        )
        plan = service.plan(
            f"post:{post_id}",
            (LookupStrategy.SOURCE_POST_URL,),
            limits=LookupLimits(2, 2, 10, 30),
        )
        complete = service.execute(plan)[0]
        assert complete.status == "complete"
        with pytest.raises(ValueError, match="not resumable"):
            service.resume(complete.candidate_lookup_run_id, limits=LookupLimits(1, 1, 10, 30))
