"""Expansion-plan-scoped acquisition planning resolved from committed associations."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import httpx
import pytest

from media_catalog.acquisition import (
    AcquisitionSelection,
    plan_acquisition,
    plan_expansion_acquisition,
)
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.cli import main
from media_catalog.database import CatalogDatabase
from media_catalog.library import (
    ArtistLibraryExpansionService,
    ExpansionLimits,
    plan_library_expansion,
)
from media_catalog.records import AccountRecord, MediaOccurrenceRecord
from media_catalog.writer import CatalogWriter

NOW = "2026-10-03T00:00:00Z"
LIMITS = ExpansionLimits(requests=1, pages=2, records=10, seconds=60)


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.params.get("offset") == "1":
        return httpx.Response(200, json={"illusts": [{"id": 2002}], "next_url": None})
    return httpx.Response(
        200,
        json={
            "illusts": [{"id": 2001}],
            "next_url": "https://app-api.pixiv.net/v1/user/illusts?user_id=1001&offset=1",
        },
    )


def _committed_expansion(tmp_path: Path, *, with_media: bool) -> tuple[Path, int, list[int]]:
    """Run a pause/resume pixiv expansion and optionally attach occurrences."""
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        writer = CatalogWriter(database)
        with database.transaction():
            account_id = writer.upsert_account(AccountRecord("pixiv", "1001", NOW)).id

        def plan():
            return plan_library_expansion(database, f"account:{account_id}", limits=LIMITS)

        adapter = PixivAdapter(
            client=httpx.Client(transport=httpx.MockTransport(_handler)),
            refresh_token_env=None,
            clock=lambda: NOW,
        )
        service = ArtistLibraryExpansionService(
            database,
            adapter,
            minimum_interval_seconds=0,
            maximum_retries=0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        )
        first_plan = plan()
        first = service.run(first_plan)
        service.resume(plan(), first.library_expansion_execution_id)
        adapter.close()
        occurrence_ids: list[int] = []
        if with_media:
            with database.transaction():
                for native_id in ("2001", "2002"):
                    post_id = int(
                        database.connection.execute(
                            "SELECT post_id FROM posts WHERE native_post_id = ?",
                            (native_id,),
                        ).fetchone()[0]
                    )
                    occurrence_ids.append(
                        writer.upsert_media(
                            post_id,
                            MediaOccurrenceRecord(
                                f"{native_id}:p0",
                                0,
                                "image",
                                remote_url=f"https://i.pximg.net/img-original/{native_id}.jpg",
                                preview_url=f"https://i.pximg.net/c/240x480/{native_id}.jpg",
                                observed_at=NOW,
                            ),
                        ).id
                    )
        occurrence_ids.extend(
            int(row[0])
            for row in database.connection.execute(
                "SELECT media_occurrence_id FROM media_occurrences ORDER BY media_occurrence_id"
            )
        )
        plan_id = first.library_expansion_plan_id
    return path, plan_id, sorted(set(occurrence_ids))


def test_expansion_scoped_selection_resolves_committed_occurrences_across_executions(
    tmp_path: Path,
) -> None:
    path, plan_id, occurrence_ids = _committed_expansion(tmp_path, with_media=True)

    scoped = plan_expansion_acquisition(path, plan_id, max_items=10)
    explicit = plan_acquisition(
        path,
        [AcquisitionSelection(occurrence_id, "primary") for occurrence_id in occurrence_ids],
        max_items=10,
    )

    assert scoped.committed_post_count == 2
    assert scoped.details_required_post_count == 0
    assert scoped.unavailable_occurrence_count == 0
    assert scoped.excluded_by_limit == 0
    assert scoped.preview.counts == {
        "requested": 2,
        "eligible": 2,
        "already_satisfied": 0,
        "excluded": 0,
        "duplicates": 0,
    }
    assert [item.media_occurrence_id for item in scoped.preview.items] == occurrence_ids
    assert scoped.preview.selection_digest == explicit.selection_digest


def test_expansion_scoped_selection_applies_limit_and_reports_exclusions(
    tmp_path: Path,
) -> None:
    path, plan_id, occurrence_ids = _committed_expansion(tmp_path, with_media=True)

    preview = plan_expansion_acquisition(path, plan_id, max_items=1)

    assert preview.excluded_by_limit == 1
    assert preview.preview.counts["requested"] == 1
    assert preview.preview.items[0].media_occurrence_id == occurrence_ids[0]


def test_expansion_scoped_selection_reports_details_required_posts(tmp_path: Path) -> None:
    path, plan_id, _ = _committed_expansion(tmp_path, with_media=False)

    preview = plan_expansion_acquisition(path, plan_id, max_items=10)

    assert preview.committed_post_count == 2
    assert preview.details_required_post_count == 2
    assert preview.preview.items == ()
    assert preview.excluded_by_limit == 0


def test_expansion_scoped_selection_rejects_unknown_plan(tmp_path: Path) -> None:
    path, _, _ = _committed_expansion(tmp_path, with_media=False)
    with pytest.raises(ValueError, match="library expansion plan not found"):
        plan_expansion_acquisition(path, 999, max_items=10)
    with pytest.raises(ValueError, match="max items must be positive"):
        plan_expansion_acquisition(path, 1, max_items=0)


def test_download_plan_cli_resolves_expansion_scope_without_network_or_writes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, plan_id, occurrence_ids = _committed_expansion(tmp_path, with_media=True)
    before_bytes = path.read_bytes()
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network attempted")),
    )

    main(
        [
            "assets",
            "download-plan",
            str(path),
            "--library-plan",
            str(plan_id),
            "--max-items",
            "1",
            "--json",
        ]
    )
    scoped = json.loads(capsys.readouterr().out)
    main(
        [
            "assets",
            "download-plan",
            str(path),
            "--select",
            f"{occurrence_ids[0]}:primary",
            "--json",
        ]
    )
    explicit = json.loads(capsys.readouterr().out)

    assert scoped["status"] == "planned"
    assert scoped["library_plan_id"] == plan_id
    assert scoped["committed_posts"] == 2
    assert scoped["excluded_by_limit"] == 1
    assert scoped["counts"] == explicit["counts"]
    assert scoped["selection_digest"] == explicit["selection_digest"]
    assert path.read_bytes() == before_bytes


def test_expansion_scoped_selection_filters_unavailable_occurrences(tmp_path: Path) -> None:
    path, plan_id, occurrence_ids = _committed_expansion(tmp_path, with_media=True)
    with CatalogDatabase(path) as database:
        database.connection.execute(
            "UPDATE media_occurrences SET availability = 'unavailable'"
            " WHERE media_occurrence_id = ?",
            (occurrence_ids[1],),
        )
        database.connection.commit()

    preview = plan_expansion_acquisition(path, plan_id, max_items=10)

    assert preview.unavailable_occurrence_count == 1
    assert [item.media_occurrence_id for item in preview.preview.items] == [occurrence_ids[0]]


def test_expansion_scoped_selection_passes_variant_through(tmp_path: Path) -> None:
    path, plan_id, _ = _committed_expansion(tmp_path, with_media=True)

    preview_variant = plan_expansion_acquisition(path, plan_id, variant="preview", max_items=10)
    preview_primary = plan_expansion_acquisition(path, plan_id, max_items=10)

    assert [item.variant_key for item in preview_variant.preview.items] == ["preview", "preview"]
    assert preview_variant.preview.selection_digest != preview_primary.preview.selection_digest
    with pytest.raises(ValueError, match="variant must not be empty"):
        plan_expansion_acquisition(path, plan_id, variant="  ", max_items=10)


def test_download_plan_cli_rejects_scope_flags_with_explicit_selection(
    tmp_path: Path,
) -> None:
    path, plan_id, occurrence_ids = _committed_expansion(tmp_path, with_media=True)
    _ = plan_id

    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "assets",
                "download-plan",
                str(path),
                "--select",
                f"{occurrence_ids[0]}:primary",
                "--variant",
                "original",
                "--json",
            ]
        )
    error = json.loads(str(exit_info.value.code))
    assert "require --library-plan" in error["error"]
