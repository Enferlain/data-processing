"""Task 6.4 regression matrix for library expansion without CLI coverage."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import load_fixture_suite
from media_catalog.adapters.e621 import E621, E621Adapter
from media_catalog.adapters.e621.config import ADAPTER_VERSION, PROVIDER_KEY
from media_catalog.database import CatalogDatabase
from media_catalog.library import (
    ArtistLibraryExpansionService,
    ExpansionLimits,
    LibraryExpansionQueryService,
    plan_library_expansion,
)
from media_catalog.records import (
    AccountRecord,
    AttributionRecord,
    MediaOccurrenceRecord,
    PostExternalReferenceRecord,
    PostRecord,
    RawRecord,
    TagAliasObservationRecord,
    TagObservationRecord,
)
from media_catalog.writer import CatalogWriter

NOW = "2026-08-13T00:00:00Z"
OBSERVED_AT = "2026-08-12T12:00:00Z"
FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
SUITE = load_fixture_suite(FIXTURES / "e621.json")

TAG_ID = "12345"
CANONICAL_NAME = "artist_a"


def _body(name: str) -> object:
    case = next(case for case in SUITE.cases if case.name == name)
    return json.loads(case.response.payload)


def _e621_tag(
    writer: CatalogWriter,
    *,
    provider_tag_id: str = TAG_ID,
    name: str = CANONICAL_NAME,
    post_count: int | None = None,
    observed_at: str = OBSERVED_AT,
) -> None:
    writer.upsert_tag_record(
        TagObservationRecord(
            PROVIDER_KEY,
            "artist",
            name,
            name,
            observed_at,
            "provider-tag-v1",
            provider_tag_id=provider_tag_id,
            native_category="artist",
            native_category_code=1,
            post_count=post_count,
        )
    )


def _e621_attribution(
    writer: CatalogWriter,
    provider_id: str = f"tag:{TAG_ID}",
    *,
    instance_host: str = "",
) -> int:
    return writer.upsert_attribution(
        AttributionRecord(
            PROVIDER_KEY,
            provider_id,
            ADAPTER_VERSION,
            NOW,
            instance_host=instance_host,
        )
    ).id


def _seed_e621_plan(
    database: CatalogDatabase,
    *,
    post_count: int | None = None,
    limits: ExpansionLimits | None = None,
) -> tuple[int, int, object]:
    writer = CatalogWriter(database)
    with database.transaction():
        seed_id = writer.upsert_account(AccountRecord("x", "9001", NOW)).id
        attribution_id = _e621_attribution(writer)
        _e621_tag(writer, post_count=post_count)
    plan = plan_library_expansion(
        database,
        f"account:{seed_id}",
        target=f"attribution:{attribution_id}",
        selection_note="operator selected the reviewed e621 artist tag",
        limits=limits,
    )
    return seed_id, attribution_id, plan


def _adapter(handler: Callable[[httpx.Request], httpx.Response]) -> E621Adapter:
    return E621Adapter(
        E621,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )


def test_e621_attribution_ambiguity_requires_explicit_selection_and_never_confirms_identity(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = writer.upsert_post(PostRecord("e621", "5001", NOW)).id
            first_attribution = _e621_attribution(writer, "tag:12345")
            second_attribution = _e621_attribution(writer, "tag:67890")
            _e621_tag(writer, provider_tag_id="12345", name="artist_a")
            _e621_tag(writer, provider_tag_id="67890", name="artist_b")
            raw_id = writer.store_raw(RawRecord(b"{}", "application/json", "post", "5001", NOW))
            for provider_id in ("tag:12345", "tag:67890"):
                writer.add_post_external_reference(
                    seed_id,
                    PostExternalReferenceRecord(
                        "provider_id",
                        NOW,
                        target_platform="e621",
                        target_object_kind="artist",
                        target_identifier_kind="stable_id",
                        target_native_id=provider_id,
                    ),
                    raw_observation_id=raw_id,
                )

        ambiguous = plan_library_expansion(database, f"post:{seed_id}")
        selected = plan_library_expansion(
            database,
            f"post:{seed_id}",
            target=f"attribution:{second_attribution}",
            selection_note="operator selected the reviewed artist tag",
        )

    assert ambiguous.executable is False
    assert ambiguous.ambiguity == "ambiguous_selection_required"
    assert {choice.target.catalog_id for choice in ambiguous.choices} == {
        first_attribution,
        second_attribution,
    }
    assert selected.selected is not None
    assert selected.selected.target.catalog_id == second_attribution
    assert selected.selected.authority.mode.value == "explicit"
    assert selected.selected.authority.reference is None
    assert selected.selected.authority.note == "operator selected the reviewed artist tag"
    assert all(choice.authority.mode.value != "confirmed" for choice in ambiguous.choices)


@pytest.mark.parametrize(
    ("mutation", "error_match"),
    [
        ("tag", "current artist tag"),
        ("alias", "stale library expansion plan"),
        ("capability", "adapter version does not match"),
    ],
)
def test_e621_stale_material_is_rejected_before_network_or_run(
    tmp_path: Path, mutation: str, error_match: str
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[])

    with CatalogDatabase(tmp_path / f"catalog-{mutation}.sqlite3") as database:
        writer = CatalogWriter(database)
        _seed_id, _attribution_id, plan = _seed_e621_plan(database)
        with database.transaction():
            if mutation == "tag":
                database.connection.execute(
                    "UPDATE tags SET category = 'general', native_category = 'general' "
                    "WHERE provider_tag_id = ?",
                    (TAG_ID,),
                )
            elif mutation == "alias":
                writer.upsert_tag_alias(
                    TagAliasObservationRecord(
                        PROVIDER_KEY,
                        "8001",
                        CANONICAL_NAME,
                        "artist_renamed",
                        "active",
                        NOW,
                    )
                )

        adapter_type: type[E621Adapter] = E621Adapter
        if mutation == "capability":
            adapter_type = type(
                "FutureE621Adapter",
                (E621Adapter,),
                {"adapter_version": "e621-native-v2"},
            )
        adapter = adapter_type(
            E621,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            clock=lambda: NOW,
        )
        try:
            service = ArtistLibraryExpansionService(
                database,
                adapter,
                minimum_interval_seconds=0,
                maximum_retries=0,
                sleep=lambda _seconds: None,
                clock=lambda: NOW,
            )
            with pytest.raises(ValueError, match=error_match):
                service.run(plan)
        finally:
            adapter._client.close()

        assert calls == 0
        assert database.connection.execute("SELECT COUNT(*) FROM remote_runs").fetchone()[0] == 0
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM library_expansion_executions"
            ).fetchone()[0]
            == 0
        )


def test_e621_provider_estimate_exposes_exact_count_provenance(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        _seed_id, _attribution_id, plan = _seed_e621_plan(database, post_count=427)

    assert plan.estimate.as_dict() == {
        "state": "count",
        "count": 427,
        "observed_at": OBSERVED_AT,
        "source": "provider_estimate",
    }
    assert plan.as_dict()["network_requested"] is False


def test_e621_queries_scope_posts_and_media_to_target_and_redact_provider_urls(
    tmp_path: Path,
) -> None:
    first_page = _body("listing_first")
    assert isinstance(first_page, list)
    first_page[0]["relationships"] = {"parent_id": 4999, "has_children": False}
    requested_pages: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_pages.append(request.url.params.get("page"))
        if request.url.params.get("page") is None:
            return httpx.Response(200, json=first_page)
        return httpx.Response(200, json=[])

    limits = ExpansionLimits(requests=2, pages=2, records=20, seconds=60)
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        _seed_id, _attribution_id, plan = _seed_e621_plan(database, limits=limits)
        adapter = _adapter(handler)
        try:
            result = ArtistLibraryExpansionService(
                database,
                adapter,
                minimum_interval_seconds=0,
                maximum_retries=0,
                sleep=lambda _seconds: None,
                clock=lambda: NOW,
            ).run(plan)
        finally:
            adapter._client.close()

        writer = CatalogWriter(database)
        with database.transaction():
            parent_id = database.connection.execute(
                "SELECT post_id FROM posts WHERE native_post_id = '4999'"
            ).fetchone()[0]
            writer.upsert_media(
                parent_id,
                MediaOccurrenceRecord(
                    "4999:p0",
                    0,
                    "image",
                    remote_url="https://static1.e621.net/relation-only.jpg",
                    observed_at=NOW,
                ),
            )
            unrelated_id = writer.upsert_post(PostRecord("e621", "9999", NOW)).id
            writer.upsert_media(
                unrelated_id,
                MediaOccurrenceRecord(
                    "9999:p0",
                    0,
                    "image",
                    remote_url="https://static1.e621.net/unrelated.jpg",
                    observed_at=NOW,
                ),
            )

        query = LibraryExpansionQueryService(database)
        posts = query.posts(result.library_expansion_plan_id)
        media = query.media(result.library_expansion_plan_id)
        public = json.dumps(
            {"result": result.as_dict(), "posts": posts, "media": media}, sort_keys=True
        )

    assert result.sync.status == "complete"
    assert requested_pages == [None, "b5101"]
    assert {item["native_post_id"] for item in posts["results"]} == {"5101", "5102"}
    assert all(item["native_post_id"] not in {"4999", "9999"} for item in posts["results"])
    assert {item["post"]["native_post_id"] for item in media["results"]} == {"5101", "5102"}
    assert all(item["post"]["native_post_id"] not in {"4999", "9999"} for item in media["results"])
    assert CANONICAL_NAME not in public
    assert "static1.e621.net" not in public
    assert "remote_url" not in public


@pytest.mark.parametrize(
    ("platform", "target_kind", "native_id", "primary_name", "capability"),
    [
        ("pixiv", "account", "1001", None, "pixiv-account-artworks"),
        ("danbooru", "attribution", "44", "artist_a", "danbooru-attribution-posts"),
        ("aibooru", "attribution", "55", "artist_b", "aibooru-attribution-posts"),
    ],
)
def test_existing_provider_expansion_plan_matrix_remains_stable(
    tmp_path: Path,
    platform: str,
    target_kind: str,
    native_id: str,
    primary_name: str | None,
    capability: str,
) -> None:
    with CatalogDatabase(tmp_path / f"{platform}.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = writer.upsert_account(AccountRecord("x", "9001", NOW)).id
            if target_kind == "account":
                target_id = writer.upsert_account(AccountRecord(platform, native_id, NOW)).id
            else:
                target_id = writer.upsert_attribution(
                    AttributionRecord(
                        platform,
                        native_id,
                        "danbooru-native-v1",
                        NOW,
                        instance_host=(
                            "aibooru.online" if platform == "aibooru" else "danbooru.donmai.us"
                        ),
                        primary_name=primary_name,
                    )
                ).id
        plan = plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"{target_kind}:{target_id}",
            selection_note=f"operator selected the {platform} target",
        )

    assert plan.selected is not None
    assert plan.selected.target.provider == platform
    assert plan.selected.target.capability.key == capability
    assert plan.selected.authority.mode.value == "explicit"
    assert plan.selected.authority.reference is None
