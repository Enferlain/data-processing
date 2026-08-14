"""Task 6.1: versioned e621 attribution enumeration capability and resolution.

These tests cover the read-only planning slice only: registering the versioned
e621 attribution capability, resolving only stable retained ``tag:<ID>`` artist
targets, failing closed for aliases/numeric ids/missing/non-artist/mismatched
targets, the private exact canonical-tag renderer, plan invalidation when the
retained tag changes, and byte-compatible Danbooru/AIBooru regression.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters.e621 import E621, E621Adapter
from media_catalog.adapters.e621.config import (
    ADAPTER_VERSION,
    PROVIDER_KEY,
    SCHEMA_VERSION,
)
from media_catalog.database import CatalogDatabase
from media_catalog.library import ArtistLibraryExpansionService, plan_library_expansion
from media_catalog.records import AccountRecord, AttributionRecord, TagObservationRecord
from media_catalog.writer import CatalogWriter

NOW = "2026-08-13T00:00:00Z"

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
) -> None:
    writer.upsert_tag_record(
        TagObservationRecord(
            platform=PROVIDER_KEY,
            category=category,
            normalized_name=name,
            provider_spelling=name,
            observed_at=NOW,
            normalization_version="provider-tag-v1",
            provider_tag_id=provider_tag_id,
            native_category=native_category,
            native_category_code=native_category_code,
        )
    )


def _e621_adapter() -> E621Adapter:
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(500)))
    return E621Adapter(E621, client=client, clock=lambda: NOW)


def test_e621_attribution_capability_is_versioned_without_count_probe() -> None:
    from media_catalog.library.contracts import ExpansionTargetKind
    from media_catalog.library.planning import CAPABILITY_VERSION, expansion_capability

    capability = expansion_capability(PROVIDER_KEY, ExpansionTargetKind.ATTRIBUTION)
    assert capability is not None
    assert capability.key == "e621-attribution-posts"
    assert capability.version == CAPABILITY_VERSION
    assert capability.provider == PROVIDER_KEY
    assert capability.operation == "list_account_posts"
    assert capability.adapter_version == ADAPTER_VERSION
    assert capability.schema_version == SCHEMA_VERSION
    # Task 6.1 declares no count probe; retained-count estimation is task 6.2.
    assert capability.count_probe_key is None


def test_explicit_e621_artist_tag_target_is_executable_and_preserves_tag_identity(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer)
        plan = plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"attribution:{attribution_id}",
            selection_note="operator selected the reviewed provider artist tag",
        )

    assert plan.executable is True
    assert plan.estimate.state == "unknown"
    assert plan.selected is not None
    target = plan.selected.target
    assert target.kind.value == "attribution"
    assert target.reference == f"attribution:{attribution_id}"
    # The durable plan material preserves the exact provider tag identity and no
    # account identity.
    assert target.native_id == f"tag:{TAG_ID}"
    assert target.provider == PROVIDER_KEY
    assert target.capability.key == "e621-attribution-posts"
    assert target.capability.adapter_version == ADAPTER_VERSION
    assert target.capability.schema_version == SCHEMA_VERSION
    assert plan.selected.authority.mode.value == "explicit"
    assert plan.selected.authority.note == "operator selected the reviewed provider artist tag"


@pytest.mark.parametrize(
    "attribution_id_factory,tag_factory,match",
    [
        # Alias ids must never masquerade as an exact tag target.
        (lambda w: _e621_attribution(w, provider_attribution_id="alias:99"), None, "stable tag"),
        # Direct artist-record ids are plain numerics and are not tag targets.
        (lambda w: _e621_attribution(w, provider_attribution_id="404"), None, "stable tag"),
        # tag:<ID> with no retained artist tag row fails closed.
        (lambda w: _e621_attribution(w), None, "retained artist tag"),
        # A retained tag whose provider id does not match fails closed.
        (
            lambda w: _e621_attribution(w),
            lambda w: _e621_tag(w, provider_tag_id="99999"),
            "retained artist tag",
        ),
        # A non-artist tag (both neutral and native category) is rejected.
        (
            lambda w: _e621_attribution(w),
            lambda w: _e621_tag(
                w, category="general", native_category="general", native_category_code=0
            ),
            "current artist tag",
        ),
        # The native artist category label is independently required.
        (
            lambda w: _e621_attribution(w),
            lambda w: _e621_tag(w, native_category="general", native_category_code=0),
            "current artist tag",
        ),
        # An unavailable attribution is not enumerable.
        (
            lambda w: _e621_attribution(w, availability="deleted"),
            lambda w: _e621_tag(w),
            "available",
        ),
    ],
)
def test_invalid_e621_attribution_targets_fail_closed(
    tmp_path: Path,
    attribution_id_factory: Callable[[CatalogWriter], int],
    tag_factory: Callable[[CatalogWriter], None] | None,
    match: str,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = attribution_id_factory(writer)
            if tag_factory is not None:
                tag_factory(writer)
        with pytest.raises(ValueError, match=match):
            plan_library_expansion(
                database,
                f"account:{seed_id}",
                target=f"attribution:{attribution_id}",
                selection_note="attempted invalid e621 attribution selection",
            )


def test_e621_attribution_plan_is_offline_read_only_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        writer = CatalogWriter(database)
        seed_id = _seed_account(writer)
        attribution_id = _e621_attribution(writer)
        _e621_tag(writer)
    before_bytes = catalog.read_bytes()
    before_entries = sorted(item.name for item in tmp_path.iterdir())

    def fail_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", fail_connect)
    first = plan_library_expansion(
        catalog,
        f"account:{seed_id}",
        target=f"attribution:{attribution_id}",
        selection_note="offline explicit selection",
    )
    second = plan_library_expansion(
        catalog,
        f"account:{seed_id}",
        target=f"attribution:{attribution_id}",
        selection_note="offline explicit selection",
    )

    assert first == second
    assert catalog.read_bytes() == before_bytes
    assert sorted(item.name for item in tmp_path.iterdir()) == before_entries
    public = json.dumps(first.as_dict(), sort_keys=True)
    # The exact canonical tag name is never exposed in public plan material.
    assert CANONICAL_NAME not in public
    assert f"tag:{TAG_ID}" in public
    assert 'network_requested": false' in public


def test_e621_renderer_returns_exact_canonical_tag_name_privately(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer)
        plan = plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"attribution:{attribution_id}",
            selection_note="render the canonical tag",
        )
        service = ArtistLibraryExpansionService(
            database,
            _e621_adapter(),
            minimum_interval_seconds=0,
            maximum_retries=0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        )
        rendered = service._render_target(plan)

    assert rendered == CANONICAL_NAME


def test_e621_renderer_fails_when_tag_is_no_longer_a_current_artist(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer)
        plan = plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"attribution:{attribution_id}",
            selection_note="render the canonical tag",
        )
        service = ArtistLibraryExpansionService(
            database,
            _e621_adapter(),
            minimum_interval_seconds=0,
            maximum_retries=0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        )
        with database.transaction():
            database.connection.execute(
                "UPDATE tags SET category = 'general', native_category = 'general' "
                "WHERE provider_tag_id = ?",
                (TAG_ID,),
            )
        with pytest.raises(ValueError, match="current artist tag"):
            service._render_target(plan)


def test_e621_plan_revision_invalidates_when_canonical_tag_name_changes(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)
            _e621_tag(writer)
        first = plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"attribution:{attribution_id}",
            selection_note="baseline selection",
        )
        # Rename only the canonical tag name; last_observed_at is untouched so the
        # diff isolates name binding in the revision.
        with database.transaction():
            database.connection.execute(
                "UPDATE tags SET name = ? WHERE provider_tag_id = ?",
                ("fluffy_renamed", TAG_ID),
            )
        second = plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"attribution:{attribution_id}",
            selection_note="baseline selection",
        )
        # A non-artist category change rejects the target outright on re-plan.
        with database.transaction():
            database.connection.execute(
                "UPDATE tags SET category = 'general', native_category = 'general' "
                "WHERE provider_tag_id = ?",
                (TAG_ID,),
            )

    assert first.selected is not None and second.selected is not None
    assert first.selected.target.revision != second.selected.target.revision
    assert first.execution_revision != second.execution_revision
    assert first.digest != second.digest

    with (
        CatalogDatabase(tmp_path / "catalog.sqlite3") as database,
        pytest.raises(ValueError, match="current artist tag"),
    ):
        plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"attribution:{attribution_id}",
            selection_note="baseline selection",
        )


def test_e621_attribution_does_not_require_a_primary_attribution_name(tmp_path: Path) -> None:
    """e621 resolves the canonical name from the retained tag row, not the
    attribution primary-name path used by Danbooru/AIBooru."""

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _seed_account(writer)
            attribution_id = _e621_attribution(writer)  # no primary_name supplied
            _e621_tag(writer)
        plan = plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"attribution:{attribution_id}",
            selection_note="resolved via retained tag",
        )

    assert plan.executable is True


def test_danbooru_attribution_regression_uses_primary_name_byte_compatible(
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
            selection_note="danbooru regression",
        )
        service = ArtistLibraryExpansionService(
            database,
            _e621_adapter(),  # adapter is unused by _render_target for attribution
            minimum_interval_seconds=0,
            maximum_retries=0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        )
        rendered = service._render_target(plan)

    assert plan.selected is not None
    assert plan.selected.target.provider == "danbooru"
    assert plan.selected.target.capability.key == "danbooru-attribution-posts"
    assert plan.selected.target.native_id == "44"
    # Danbooru/AIBooru still render the latest primary name byte-for-byte.
    assert rendered == "artist_a"
