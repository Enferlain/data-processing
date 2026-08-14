"""Task 6.3: e621 artist-library expansion execution and resume contracts."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path

import httpx

from media_catalog.adapters import load_fixture_suite
from media_catalog.adapters.e621 import E621, E621Adapter
from media_catalog.adapters.e621.config import ADAPTER_VERSION
from media_catalog.database import CatalogDatabase
from media_catalog.library import (
    ArtistLibraryExpansionService,
    ExpansionLimits,
    plan_library_expansion,
)
from media_catalog.records import AccountRecord, AttributionRecord, TagObservationRecord
from media_catalog.remote_queries import get_remote_run
from media_catalog.writer import CatalogWriter

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
NOW = "2026-08-13T00:00:00Z"
TAG_ID = "12345"
CANONICAL_NAME = "artist_a"
SUITE = load_fixture_suite(FIXTURES / "e621.json")


def _body(name: str) -> object:
    case = next(case for case in SUITE.cases if case.name == name)
    return json.loads(case.response.payload)


def _seed_plan(database: CatalogDatabase, limits: ExpansionLimits):
    writer = CatalogWriter(database)
    with database.transaction():
        seed_id = writer.upsert_account(AccountRecord("x", "9001", NOW)).id
        attribution_id = writer.upsert_attribution(
            AttributionRecord(
                "e621",
                f"tag:{TAG_ID}",
                ADAPTER_VERSION,
                NOW,
                instance_host="e621.net",
            )
        ).id
        writer.upsert_tag_record(
            TagObservationRecord(
                "e621",
                "artist",
                CANONICAL_NAME,
                CANONICAL_NAME,
                NOW,
                "provider-tag-v1",
                provider_tag_id=TAG_ID,
                native_category="artist",
                native_category_code=1,
            )
        )
    return plan_library_expansion(
        database,
        f"account:{seed_id}",
        target=f"attribution:{attribution_id}",
        selection_note="operator selected the reviewed e621 artist tag",
        limits=limits,
    )


def _adapter(handler: Callable[[httpx.Request], httpx.Response]) -> E621Adapter:
    return E621Adapter(
        E621,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )


def _response(body: object) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps(body).encode(),
    )


def test_e621_expansion_pauses_and_resumes_target_scoped_without_recursive_associations(
    tmp_path: Path,
) -> None:
    first_page = _body("listing_first")
    assert isinstance(first_page, list)
    first_page = [copy.deepcopy(entry) for entry in first_page]
    first_page[0]["relationships"] = {"parent_id": 4999, "has_children": False}

    null_url = _body("null_media_post")
    assert isinstance(null_url, dict)
    null_url["id"] = 5104
    sparse = {
        "id": 5103,
        "rating": "s",
        "uploader_id": 42,
        "tags": {"general": ["sparse"], "artist": [CANONICAL_NAME]},
        "relationships": {"parent_id": 0, "has_children": False},
        "flags": {"deleted": False},
    }
    first_page = [null_url, sparse, first_page[0], first_page[1]]
    requested_pages: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("tags") == CANONICAL_NAME
        requested_pages.append(request.url.params.get("page"))
        if request.url.params.get("page") is None:
            return _response(first_page)
        assert request.url.params.get("page") == "b5101"
        return _response([])

    limits = ExpansionLimits(requests=1, pages=2, records=100, seconds=60)
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        plan = _seed_plan(database, limits)
        adapter = _adapter(handler)
        first_service = ArtistLibraryExpansionService(
            database,
            adapter,
            minimum_interval_seconds=0,
            maximum_retries=0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        )
        try:
            first = first_service.run(plan)
        finally:
            adapter._client.close()

        assert first.sync.status == "paused"
        assert first.sync.budget_boundary == "request"
        first_run = get_remote_run(database, first.sync.remote_run_id)
        assert first_run is not None
        assert first_run["status"] == "paused"
        assert len(first_run["checkpoints"]) == 1
        continuation_json = database.connection.execute(
            "SELECT continuation_json FROM remote_checkpoints WHERE remote_run_id = ?",
            (first.sync.remote_run_id,),
        ).fetchone()[0]
        assert json.loads(continuation_json)["value"]["page"] == "b5101"

        later = plan_library_expansion(
            database,
            plan.seed,
            target=plan.selected.target.reference if plan.selected is not None else None,
            selection_note=plan.selected.authority.note if plan.selected is not None else None,
            limits=limits,
        )
        adapter = _adapter(handler)
        second_service = ArtistLibraryExpansionService(
            database,
            adapter,
            minimum_interval_seconds=0,
            maximum_retries=0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        )
        try:
            second = second_service.resume(later, first.library_expansion_execution_id)
        finally:
            adapter._client.close()

        assert second.sync.status == "complete"
        assert second.sync.resumed_from_run_id == first.sync.remote_run_id
        assert requested_pages == [None, "b5101"]
        assert CANONICAL_NAME not in json.dumps(second.as_dict(), sort_keys=True)
        origins = database.connection.execute(
            "SELECT origin_kind, origin_reference FROM remote_runs ORDER BY remote_run_id"
        ).fetchall()
        assert [tuple(row) for row in origins] == [
            ("library_expansion", plan.digest),
            ("library_expansion", plan.digest),
        ]
        lineage = database.connection.execute(
            """SELECT execution_kind, predecessor_execution_id
                 FROM library_expansion_executions
                ORDER BY library_expansion_execution_id"""
        ).fetchall()
        assert [tuple(row) for row in lineage] == [("initial", None), ("resume", 1)]

        # Only listed top-level posts are associated.  The retained parent
        # relation may materialize post 4999, but it is not recursively expanded.
        associated = database.connection.execute(
            """SELECT p.native_post_id, lep.library_expansion_execution_id, lep.details_required
                 FROM library_expansion_posts lep JOIN posts p USING(post_id)
                ORDER BY p.native_post_id"""
        ).fetchall()
        assert [row[0] for row in associated] == ["5101", "5102", "5103", "5104"]
        assert all(row[1] == first.library_expansion_execution_id for row in associated)
        assert {row[0]: row[2] for row in associated} == {
            "5101": 0,
            "5102": 0,
            "5103": 1,
            "5104": 0,
        }
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM posts WHERE native_post_id = '4999'"
            ).fetchone()[0]
            == 1
        )
        assert database.connection.execute("SELECT COUNT(*) FROM post_relations").fetchone()[0] == 1
        assert database.connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        assert (
            database.connection.execute("SELECT COUNT(*) FROM remote_checkpoints").fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 2
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM remote_requests").fetchone()[0] == 2
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM library_expansion_posts").fetchone()[
                0
            ]
            == 4
        )
