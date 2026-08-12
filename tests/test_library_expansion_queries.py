from __future__ import annotations

import json
from pathlib import Path

import httpx

from media_catalog.acquisition import AcquisitionSelection, plan_acquisition
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.database import CatalogDatabase
from media_catalog.library import (
    ArtistLibraryExpansionService,
    LibraryExpansionQueryService,
    plan_library_expansion,
)
from media_catalog.records import (
    AccountRecord,
    LibraryExpansionProbeRecord,
    MediaOccurrenceRecord,
    PostRecord,
)
from media_catalog.writer import CatalogWriter

NOW = "2026-08-12T20:00:00Z"


def _expanded(database: CatalogDatabase):
    writer = CatalogWriter(database)
    with database.transaction():
        account_id = writer.upsert_account(AccountRecord("pixiv", "1001", NOW)).id
    plan = plan_library_expansion(database, f"account:{account_id}")
    adapter = PixivAdapter(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"illusts": [{"id": 2001}]})
            )
        ),
        refresh_token_env=None,
        clock=lambda: NOW,
    )
    try:
        result = ArtistLibraryExpansionService(
            database,
            adapter,
            minimum_interval_seconds=0,
            maximum_retries=0,
            clock=lambda: NOW,
        ).run(plan)
    finally:
        adapter.close()
    return plan, result


def test_library_queries_are_bounded_redacted_and_current_schema_read_only(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        plan, result = _expanded(database)
    before_bytes = path.read_bytes()
    before_entries = sorted(item.name for item in tmp_path.iterdir())

    service = LibraryExpansionQueryService(path)
    listed = service.runs(limit=1)
    shown = service.show(result.library_expansion_execution_id)
    posts = service.posts(result.library_expansion_plan_id, limit=1)

    assert listed["count"] == 1
    assert shown is not None
    assert shown["target"] == plan.selected.target.reference
    assert shown["incomplete_detail_count"] == 1
    assert shown["media_filter"] == {"expansion_plan_id": result.library_expansion_plan_id}
    assert posts["results"][0]["native_post_id"] == "2001"
    assert posts["results"][0]["details_required"] is True
    public = json.dumps({"listed": listed, "shown": shown, "posts": posts}, sort_keys=True)
    assert "artist:" not in public
    assert "remote_url" not in public
    assert "raw_payload" not in public
    assert "app-api.pixiv.net" not in public
    assert path.read_bytes() == before_bytes
    assert sorted(item.name for item in tmp_path.iterdir()) == before_entries


def test_probe_history_reports_truncation_only_when_more_rows_exist(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        _plan, result = _expanded(database)
        writer = CatalogWriter(database)
        record = LibraryExpansionProbeRecord(
            result.library_expansion_plan_id,
            "pixiv-account-count",
            "library-expansion-v1",
            "pixiv-app-api-v1",
            "pixiv-normalized-v1",
            1,
            60,
            "unsupported",
            NOW,
            NOW,
        )
        with database.transaction():
            for _ in range(100):
                writer.record_library_expansion_probe(record)
        exact = LibraryExpansionQueryService(database).show(result.library_expansion_execution_id)
        with database.transaction():
            writer.record_library_expansion_probe(record)
        overflow = LibraryExpansionQueryService(database).show(
            result.library_expansion_execution_id
        )

    assert exact is not None
    assert exact["probes_truncated"] is False
    assert len(exact["probes"]) == 100
    assert all("request_identity" not in probe for probe in exact["probes"])
    assert all("payload" not in probe for probe in exact["probes"])
    assert overflow is not None
    assert overflow["probes_truncated"] is True
    assert len(overflow["probes"]) == 100


def test_target_scoped_media_selectors_feed_existing_acquisition_planner(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        _plan, result = _expanded(database)
        writer = CatalogWriter(database)
        discovered_post_id = database.connection.execute(
            "SELECT post_id FROM posts WHERE native_post_id = '2001'"
        ).fetchone()[0]
        with database.transaction():
            occurrence_id = writer.upsert_media(
                discovered_post_id,
                MediaOccurrenceRecord(
                    "2001:p0",
                    0,
                    "image",
                    remote_url="https://i.pximg.net/img-original/image.jpg?token=secret",
                    observed_at=NOW,
                ),
            ).id
            unrelated_post_id = writer.upsert_post(PostRecord("pixiv", "9999", NOW)).id
            writer.upsert_media(
                unrelated_post_id,
                MediaOccurrenceRecord(
                    "9999:p0",
                    0,
                    "image",
                    remote_url="https://i.pximg.net/img-original/unrelated.jpg",
                    observed_at=NOW,
                ),
            )

        media = LibraryExpansionQueryService(database).media(result.library_expansion_plan_id)
        selector = media["results"][0]["variants"][0]["selection"]
        preview = plan_acquisition(
            database,
            [AcquisitionSelection(occurrence_id, "primary")],
            max_items=1,
            clock=lambda: NOW,
        )

    assert media["count"] == 1
    assert media["results"][0]["media_occurrence_id"] == occurrence_id
    assert selector == f"{occurrence_id}:primary"
    assert preview.items[0].media_occurrence_id == occurrence_id
    assert preview.items[0].variant_key == "primary"
    assert "token=secret" not in json.dumps(media, sort_keys=True)
