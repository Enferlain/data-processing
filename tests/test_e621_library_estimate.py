"""Task 6.2: offline retained-count estimation for e621 artist-library expansion.

The estimate reports the exact retained ``post_count`` of a stable
``tag:<ID>`` artist target only when a current retained tag observation
supplies an unambiguous count.  Alias targets, missing counts, and tags that an
active/approved alias redirects away from stay unknown without any probe or
listing request.  Count, category, and alias facts are bound into the target
revision so changing them invalidates a stale plan before execution.  Existing
Danbooru/AIBooru/Pixiv estimate behavior is unchanged.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters.e621 import E621, E621Adapter
from media_catalog.adapters.e621.config import ADAPTER_VERSION, PROVIDER_KEY
from media_catalog.database import CatalogDatabase
from media_catalog.library import ArtistLibraryExpansionService, plan_library_expansion
from media_catalog.library.planning import CAPABILITY_VERSION
from media_catalog.records import (
    AccountRecord,
    AttributionRecord,
    TagAliasObservationRecord,
    TagObservationRecord,
)
from media_catalog.writer import CatalogWriter

NOW = "2026-08-13T00:00:00Z"
OBSERVED_AT = "2026-08-12T12:00:00Z"

TAG_ID = "12345"
CANONICAL_NAME = "fluffy_foxy"


def _seed_account(writer: CatalogWriter) -> int:
    return writer.upsert_account(AccountRecord("x", "9001", NOW)).id


def _e621_attribution(
    writer: CatalogWriter,
    *,
    provider_attribution_id: str = f"tag:{TAG_ID}",
    availability: str = "available",
) -> int:
    return writer.upsert_attribution(
        AttributionRecord(
            PROVIDER_KEY,
            provider_attribution_id,
            ADAPTER_VERSION,
            NOW,
            availability=availability,
            instance_host="e621.net",
        )
    ).id


def _e621_tag(
    writer: CatalogWriter,
    *,
    provider_tag_id: str = TAG_ID,
    name: str = CANONICAL_NAME,
    category: str = "artist",
    native_category: str = "artist",
    native_category_code: int = 1,
    post_count: int | None = None,
    observed_at: str = OBSERVED_AT,
) -> None:
    writer.upsert_tag_record(
        TagObservationRecord(
            platform=PROVIDER_KEY,
            category=category,
            normalized_name=name,
            provider_spelling=name,
            observed_at=observed_at,
            normalization_version="provider-tag-v1",
            provider_tag_id=provider_tag_id,
            native_category=native_category,
            native_category_code=native_category_code,
            post_count=post_count,
        )
    )


def _e621_alias(
    writer: CatalogWriter,
    *,
    provider_alias_id: str,
    antecedent_name: str,
    consequent_name: str,
    status: str = "active",
    observed_at: str = OBSERVED_AT,
) -> None:
    writer.upsert_tag_alias(
        TagAliasObservationRecord(
            platform=PROVIDER_KEY,
            provider_alias_id=provider_alias_id,
            antecedent_name=antecedent_name,
            consequent_name=consequent_name,
            status=status,
            observed_at=observed_at,
        )
    )


def _plan(database: CatalogDatabase | Path, seed_id: int, attribution_id: int):
    return plan_library_expansion(
        database,
        f"account:{seed_id}",
        target=f"attribution:{attribution_id}",
        selection_note="operator selected the reviewed provider artist tag",
    )


def test_exact_retained_count_is_reported_offline(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer, post_count=427)
        plan = _plan(database, seed_id, attribution_id)
        public = plan.as_dict()

    assert plan.executable is True
    assert plan.selected is not None
    estimate = plan.estimate
    assert estimate.state == "count"
    assert estimate.count == 427
    assert estimate.observed_at == OBSERVED_AT
    assert estimate.source == "provider_estimate"
    # The exact canonical tag name stays private even with a reported count.
    serialized = json.dumps(public, sort_keys=True)
    assert CANONICAL_NAME not in serialized
    assert f"tag:{TAG_ID}" in serialized
    assert plan.selected.target.capability.version == CAPABILITY_VERSION
    assert public["network_requested"] is False


def test_zero_retained_count_is_a_valid_provider_estimate(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer, post_count=0)
        plan = _plan(database, seed_id, attribution_id)

    assert plan.estimate.state == "count"
    assert plan.estimate.count == 0
    assert plan.estimate.source == "provider_estimate"


def test_missing_count_is_unknown_without_a_probe(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer)  # artist tag observed with no retained post_count
        plan = _plan(database, seed_id, attribution_id)

    assert plan.executable is True
    assert plan.estimate.state == "unknown"
    assert plan.estimate.count is None


@pytest.mark.parametrize("status", ["active", "approved"])
def test_tag_redirected_by_active_alias_has_unknown_stale_count(
    tmp_path: Path, status: str
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer, post_count=427)
            # The canonical name redirects away, so its retained count is stale.
            _e621_alias(
                writer,
                provider_alias_id="8001",
                antecedent_name=CANONICAL_NAME,
                consequent_name="fluffy_renamed",
                status=status,
            )
        plan = _plan(database, seed_id, attribution_id)

    assert plan.executable is True
    assert plan.estimate.state == "unknown"


@pytest.mark.parametrize("status", ["pending", "deleted"])
def test_inactive_alias_does_not_make_the_count_unknown(tmp_path: Path, status: str) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer, post_count=427)
            _e621_alias(
                writer,
                provider_alias_id="8002",
                antecedent_name=CANONICAL_NAME,
                consequent_name="fluffy_renamed",
                status=status,
            )
        plan = _plan(database, seed_id, attribution_id)

    assert plan.estimate.state == "count"
    assert plan.estimate.count == 427


@pytest.mark.parametrize("status", ["pending", "deleted"])
def test_latest_alias_status_overrides_historical_active_redirect(
    tmp_path: Path, status: str
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer, post_count=427)
            _e621_alias(
                writer,
                provider_alias_id="8004",
                antecedent_name=CANONICAL_NAME,
                consequent_name="fluffy_renamed",
                status="active",
                observed_at="2026-08-12T12:00:00Z",
            )
            _e621_alias(
                writer,
                provider_alias_id="8004",
                antecedent_name=CANONICAL_NAME,
                consequent_name="fluffy_renamed",
                status=status,
                observed_at="2026-08-13T12:00:00Z",
            )
        plan = _plan(database, seed_id, attribution_id)

    assert plan.estimate.state == "count"
    assert plan.estimate.count == 427


def test_latest_immutable_tag_observation_supplies_the_count(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer, post_count=427, observed_at="2026-08-12T12:00:00Z")
            _e621_tag(writer, post_count=511, observed_at="2026-08-13T12:00:00Z")
        plan = _plan(database, seed_id, attribution_id)

    assert plan.estimate.state == "count"
    assert plan.estimate.count == 511
    assert plan.estimate.observed_at == "2026-08-13T12:00:00Z"


def test_consequent_alias_keeps_count_but_is_bound_into_revision(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer, post_count=427)
        before = _plan(database, seed_id, attribution_id)
        with database.transaction():
            # An old name redirecting INTO the canonical tag does not move the
            # count, so the estimate stays exact; the alias picture still binds.
            _e621_alias(
                writer,
                provider_alias_id="8003",
                antecedent_name="fluffy_old",
                consequent_name=CANONICAL_NAME,
            )
        after = _plan(database, seed_id, attribution_id)

    assert before.estimate.state == "count" and after.estimate.state == "count"
    assert before.estimate.count == after.estimate.count == 427
    assert before.selected is not None and after.selected is not None
    assert before.selected.target.revision != after.selected.target.revision
    assert before.digest != after.digest
    assert before.execution_revision != after.execution_revision


def test_alias_target_fails_closed_without_a_count_estimate(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer, provider_attribution_id="alias:99")
        # An alias:<ID> target never reaches a count estimate; it fails closed.
        with pytest.raises(ValueError, match="stable tag"):
            _plan(database, seed_id, attribution_id)


def test_nonartist_tag_fails_closed_without_a_count_estimate(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(
                writer,
                post_count=427,
                category="general",
                native_category="general",
                native_category_code=0,
            )
        # A non-artist tag fails closed rather than yielding a count.
        with pytest.raises(ValueError, match="current artist tag"):
            _plan(database, seed_id, attribution_id)


def test_mismatched_retained_tag_fails_closed_without_a_count_estimate(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)  # resolves tag:12345
            # A retained artist tag exists but under a different provider id, so
            # nothing matches the attribution identity; no count is produced.
            _e621_tag(writer, provider_tag_id="99999", post_count=427)
        with pytest.raises(ValueError, match="retained artist tag"):
            _plan(database, seed_id, attribution_id)


def test_count_change_invalidates_revision_and_digest(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer, post_count=427)
        before = _plan(database, seed_id, attribution_id)
        # A mutable projection edit does not become a current estimate without
        # a matching immutable observation.  It still changes target material,
        # so a prior plan cannot be reused silently.
        with database.transaction():
            database.connection.execute(
                "UPDATE tags SET post_count = ? WHERE provider_tag_id = ?",
                (511, TAG_ID),
            )
        after = _plan(database, seed_id, attribution_id)

    assert before.estimate.count == 427 and after.estimate.state == "unknown"
    assert before.selected is not None and after.selected is not None
    assert before.selected.target.revision != after.selected.target.revision
    assert before.digest != after.digest
    assert before.execution_revision != after.execution_revision


def test_category_change_rejects_the_target_on_replan(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer, post_count=427)
        before = _plan(database, seed_id, attribution_id)
        with database.transaction():
            database.connection.execute(
                "UPDATE tags SET category = 'general', native_category = 'general' "
                "WHERE provider_tag_id = ?",
                (TAG_ID,),
            )

    assert before.estimate.state == "count"
    with (
        CatalogDatabase(tmp_path / "catalog.sqlite3") as database,
        pytest.raises(ValueError, match="current artist tag"),
    ):
        _plan(database, seed_id, attribution_id)


def test_estimate_is_deterministic_and_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        writer = CatalogWriter(database)
        seed_id = _seed_account(writer)
        attribution_id = _e621_attribution(writer)
        _e621_tag(writer, post_count=427)
    before_bytes = catalog.read_bytes()

    def fail_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", fail_connect)
    first = _plan(catalog, seed_id, attribution_id)
    second = _plan(catalog, seed_id, attribution_id)

    assert first == second
    assert first.estimate.state == "count"
    assert catalog.read_bytes() == before_bytes


def test_danbooru_attribution_regression_still_uses_probe_estimate(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = writer.upsert_attribution(
                AttributionRecord(
                    "danbooru",
                    "44",
                    "danbooru-native-v1",
                    NOW,
                    instance_host="danbooru.donmai.us",
                    primary_name="artist_a",
                )
            ).id
        plan = plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"attribution:{attribution_id}",
            selection_note="danbooru estimate regression",
        )

    assert plan.selected is not None
    assert plan.selected.target.provider == "danbooru"
    # No retained probe exists, so Danbooru stays unknown and is never routed to
    # the e621 provider_estimate path.
    assert plan.estimate.state == "unknown"
    assert plan.estimate.source is None
    assert plan.selected.target.capability.key == "danbooru-attribution-posts"


def test_renderer_still_returns_canonical_name_with_a_count(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer, post_count=427)
        plan = _plan(database, seed_id, attribution_id)
        service = ArtistLibraryExpansionService(
            database,
            E621Adapter(
                E621,
                client=httpx.Client(
                    transport=httpx.MockTransport(lambda _request: httpx.Response(500))
                ),
                clock=lambda: NOW,
            ),
            minimum_interval_seconds=0,
            maximum_retries=0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        )
        rendered = service._render_target(plan)

    assert rendered == CANONICAL_NAME
