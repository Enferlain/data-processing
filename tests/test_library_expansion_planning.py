from __future__ import annotations

import json
import socket
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.discovery import DiscoveryService
from media_catalog.library import ExpansionLimits, plan_library_expansion
from media_catalog.records import (
    AccountRecord,
    AttributionRecord,
    PostExternalReferenceRecord,
    PostRecord,
    RawRecord,
)
from media_catalog.writer import CatalogWriter

NOW = "2026-08-12T20:00:00Z"
LATER = "2026-08-12T21:00:00Z"


def _account(
    writer: CatalogWriter,
    platform: str,
    native_id: str,
    *,
    handle: str | None = None,
    display_name: str | None = None,
    profile_url: str | None = None,
) -> int:
    return writer.upsert_account(
        AccountRecord(
            platform,
            native_id,
            NOW,
            handle=handle,
            display_name=display_name,
            profile_url=profile_url,
        )
    ).id


def test_pixiv_account_plan_is_deterministic_redacted_and_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database, database.transaction():
        account_id = _account(
            CatalogWriter(database),
            "pixiv",
            "1001",
            handle="private-name",
            profile_url="https://www.pixiv.net/users/1001?token=secret",
        )
    before_bytes = path.read_bytes()
    before_entries = sorted(item.name for item in tmp_path.iterdir())

    def fail_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", fail_connect)
    first = plan_library_expansion(path, f"account:{account_id}")
    second = plan_library_expansion(path, f"account:{account_id}")

    assert first == second
    assert first.executable is True
    assert first.selected is not None
    assert first.selected.target.reference == f"account:{account_id}"
    assert first.selected.authority.mode.value == "explicit"
    assert first.estimate.state == "unknown"
    public = json.dumps(first.as_dict(), sort_keys=True)
    assert "private-name" not in public
    assert "token=secret" not in public
    assert 'network_requested": false' in public
    assert path.read_bytes() == before_bytes
    assert sorted(item.name for item in tmp_path.iterdir()) == before_entries


def test_capability_versions_are_part_of_plan_identity(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database, database.transaction():
        account_id = _account(CatalogWriter(database), "pixiv", "1001")
    plan = plan_library_expansion(tmp_path / "catalog.sqlite3", f"account:{account_id}")
    assert plan.selected is not None
    changed_capability = replace(plan.selected.target.capability, version="future-v2")
    changed_target = replace(plan.selected.target, capability=changed_capability)
    changed_choice = replace(plan.selected, target=changed_target)
    changed_plan = replace(
        plan,
        choices=(changed_choice,),
        selected=changed_choice,
    )

    assert changed_choice.digest != plan.selected.digest
    assert changed_plan.digest != plan.digest
    assert changed_plan.execution_revision != plan.execution_revision


def test_confirmed_identity_provenance_selects_supported_target(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            x_account = _account(writer, "x", "9001", handle="not-a-target")
            pixiv_account = _account(writer, "pixiv", "1001")
            cursor = database.connection.execute(
                """INSERT INTO account_match_candidates (
                           candidate_key, subject_account_id, target_account_id,
                           relation_kind, current_state, score, score_version,
                           score_components_json, evidence_generation, review_revision,
                           created_at, updated_at
                       ) VALUES (?, ?, ?, 'same_identity', 'pending', 100, 'test-v1',
                                 '{}', 0, 0, ?, ?)""",
                ("c" * 64, x_account, pixiv_account, NOW, NOW),
            )
            assert cursor.lastrowid is not None
            candidate_id = cursor.lastrowid
        review = DiscoveryService(database).review(f"account:{candidate_id}", "confirmed")

        plan = plan_library_expansion(database, f"account:{x_account}")

    assert plan.executable is True
    assert plan.selected is not None
    assert plan.selected.target.reference == f"account:{pixiv_account}"
    assert plan.selected.authority.mode.value == "confirmed"
    assert f"decision:{review['decision_id']}" in str(plan.selected.authority.reference)
    assert any(item["reason"] == "unsupported account expansion target" for item in plan.exclusions)


def test_post_resolution_uses_authors_but_never_uploaders(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            author_id = _account(writer, "pixiv", "1001")
            uploader_id = _account(writer, "pixiv", "1002")
            post_id = writer.upsert_post(PostRecord("danbooru", "55", NOW)).id
            writer.add_participant(post_id, author_id, "author")
            writer.add_participant(post_id, uploader_id, "uploader")

        plan = plan_library_expansion(database, f"post:{post_id}")

    assert plan.selected is not None
    assert plan.selected.target.reference == f"account:{author_id}"
    assert plan.selected.source_kind == "observed_authorship"
    assert any(item["reason"] == "unsupported_participant_role" for item in plan.exclusions)


def test_multiple_supported_authors_require_explicit_selection(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            first_id = _account(writer, "pixiv", "1001")
            second_id = _account(writer, "pixiv", "1002")
            post_id = writer.upsert_post(PostRecord("x", "55", NOW)).id
            writer.add_participant(post_id, second_id, "creator")
            writer.add_participant(post_id, first_id, "author")

        ambiguous = plan_library_expansion(database, f"post:{post_id}")
        selected = plan_library_expansion(
            database,
            f"post:{post_id}",
            target=f"account:{second_id}",
            selection_note="operator selected the credited creator",
        )

    assert ambiguous.executable is False
    assert ambiguous.ambiguity == "ambiguous_selection_required"
    assert [choice.target.catalog_id for choice in ambiguous.choices] == [first_id, second_id]
    assert selected.selected is not None
    assert selected.selected.target.catalog_id == second_id
    assert selected.selected.authority.note == "operator selected the credited creator"


def test_explicit_booru_attribution_remains_distinct_from_account(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _account(writer, "x", "9001", handle="artist-alias")
            attribution_id = writer.upsert_attribution(
                AttributionRecord(
                    "danbooru",
                    "44",
                    "danbooru-adapter-v1",
                    NOW,
                    instance_host="danbooru.donmai.us",
                    primary_name="artist-alias",
                )
            ).id

        with pytest.raises(ValueError, match="selection note"):
            plan_library_expansion(
                database, f"account:{seed_id}", target=f"attribution:{attribution_id}"
            )
        plan = plan_library_expansion(
            database,
            f"account:{seed_id}",
            target=f"attribution:{attribution_id}",
            selection_note="selected the reviewed provider artist record",
        )

    assert plan.selected is not None
    assert plan.selected.target.kind.value == "attribution"
    assert plan.selected.target.reference == f"attribution:{attribution_id}"
    assert plan.selected.target.capability.count_probe_key is None
    assert plan.selected.authority.mode.value == "explicit"
    changed_note = replace(
        plan.selected,
        authority=replace(plan.selected.authority, note="a different explicit selection reason"),
    )
    assert changed_note.digest != plan.selected.digest


def test_post_typed_artist_reference_resolves_existing_attribution(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            post_id = writer.upsert_post(PostRecord("x", "55", NOW)).id
            attribution_id = writer.upsert_attribution(
                AttributionRecord(
                    "danbooru",
                    "44",
                    "danbooru-adapter-v1",
                    NOW,
                    primary_name="artist_a",
                )
            ).id
            raw_id = writer.store_raw(RawRecord(b"{}", "application/json", "post", "55", NOW))
            writer.add_post_external_reference(
                post_id,
                PostExternalReferenceRecord(
                    "provider_id",
                    NOW,
                    target_platform="danbooru",
                    target_object_kind="artist",
                    target_identifier_kind="stable_id",
                    target_native_id="44",
                ),
                raw_observation_id=raw_id,
            )

        plan = plan_library_expansion(database, f"post:{post_id}")

    assert plan.selected is not None
    assert plan.selected.target.reference == f"attribution:{attribution_id}"
    assert plan.selected.source_kind == "observed_attribution"
    assert plan.selected.authority.mode.value == "explicit"


def test_plan_revision_changes_when_target_snapshot_changes(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            account_id = _account(writer, "pixiv", "1001", display_name="before")
        first = plan_library_expansion(database, f"account:{account_id}")
        with database.transaction():
            writer.upsert_account(AccountRecord("pixiv", "1001", LATER, display_name="after"))
        second = plan_library_expansion(database, f"account:{account_id}")

    assert first.seed_revision != second.seed_revision
    assert first.selected is not None and second.selected is not None
    assert first.selected.target.revision != second.selected.target.revision
    assert first.digest != second.digest


def test_attribution_without_primary_name_is_not_executable(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_id = _account(writer, "x", "9001")
            attribution_id = writer.upsert_attribution(
                AttributionRecord("danbooru", "44", "danbooru-native-v1", NOW)
            ).id

        with pytest.raises(ValueError, match="no current primary name"):
            plan_library_expansion(
                database,
                f"account:{seed_id}",
                target=f"attribution:{attribution_id}",
                selection_note="selected provider attribution",
            )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ExpansionLimits(requests=0),
        lambda: ExpansionLimits(pages=True),
        lambda: ExpansionLimits(records=10_001),
        lambda: ExpansionLimits(seconds=-1),
    ],
)
def test_limits_reject_invalid_values(factory: Callable[[], ExpansionLimits]) -> None:
    with pytest.raises(ValueError, match="library expansion"):
        factory()
