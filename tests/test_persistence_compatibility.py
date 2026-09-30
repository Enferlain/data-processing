from __future__ import annotations

import dataclasses
import hashlib
import inspect
import typing
from pathlib import Path

import pytest

import media_catalog.records as records
from media_catalog.database import CatalogDatabase
from media_catalog.records import AccountRecord, ManagedRootRecord
from media_catalog.writer import CatalogWriter

RECORD_SIGNATURE_DIGEST = "38a4a629d5ae850f2c8cc21d957a3e647f69e9d7a5191caa5e979320e50ae2c4"
RECORD_PUBLIC_NAMES_DIGEST = "e6c2ba22873f447ea3a1ec1876f7ed8659a245e836c7abaf014182ebf9b47a71"
WRITER_SIGNATURE_DIGEST = "d7db6318a1c54685e78c4393d6e6cdfb28d4cda4943fa1875e3464bb6b9a0aa1"
RECORD_FIELD_SURFACE_DIGEST = "df3c5dd72b32b7d419f3fece5dd4ff1372b8617531beb8f8476c27c7909288e0"


def _digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _record_signatures() -> list[str]:
    signatures: list[str] = []
    for name, value in sorted(vars(records).items()):
        if inspect.isclass(value) and dataclasses.is_dataclass(value):
            signatures.append(f"{name}{inspect.signature(value)}")
    return signatures


def _writer_signatures() -> list[str]:
    return [
        f"{name}{inspect.signature(value)}"
        for name, value in inspect.getmembers(CatalogWriter, inspect.isfunction)
        if not name.startswith("_")
    ]


def test_records_public_constructor_surface_is_stable() -> None:
    signatures = _record_signatures()

    assert len(signatures) == 45
    assert _digest(signatures) == RECORD_SIGNATURE_DIGEST, "\n".join(signatures)


def test_records_public_name_surface_is_stable() -> None:
    names = sorted(records.__all__)

    assert len(names) == 156
    assert all(not name.startswith("_") for name in names)
    assert all(hasattr(records, name) for name in names)
    assert {"REMOTE_OPERATIONS", "REMOTE_OUTCOMES", "REMOTE_RUN_STATUSES"} <= set(names)
    assert _digest(names) == RECORD_PUBLIC_NAMES_DIGEST, "\n".join(names)


def test_record_serialization_and_validator_reflection_paths_are_explicit() -> None:
    record_modules = {
        value.__module__
        for value in vars(records).values()
        if inspect.isclass(value) and dataclasses.is_dataclass(value)
    }

    assert record_modules == {
        "media_catalog.records.acquisition",
        "media_catalog.records.catalog",
        "media_catalog.records.discovery",
        "media_catalog.records.library",
        "media_catalog.records.lookup",
        "media_catalog.records.metadata",
        "media_catalog.records.remote",
        "media_catalog.records.storage",
    }
    assert records.validate_platform.__module__ == "media_catalog.records.common"


def test_record_families_preserve_fields_defaults_and_frozen_behavior() -> None:
    field_lines: list[str] = []

    for name, value in sorted(vars(records).items()):
        if not (inspect.isclass(value) and dataclasses.is_dataclass(value)):
            continue
        assert value.__dataclass_params__.frozen, name
        assert set(value.__slots__) == {f.name for f in dataclasses.fields(value)}, name
        parts: list[str] = []
        for field in dataclasses.fields(value):
            if field.default is not dataclasses.MISSING:
                default = repr(field.default)
            elif field.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
                default = f"factory:{field.default_factory!r}"
            else:
                default = "required"
            parts.append(f"{field.name}={default}")
        field_lines.append(f"{name}({', '.join(parts)})")

    assert len(field_lines) == 45
    assert _digest(field_lines) == RECORD_FIELD_SURFACE_DIGEST, "\n".join(field_lines)


def test_record_annotations_resolve_across_families() -> None:
    for name, value in sorted(vars(records).items()):
        if inspect.isclass(value) and dataclasses.is_dataclass(value):
            hints = typing.get_type_hints(value)
            assert set(hints) == {f.name for f in dataclasses.fields(value)}, name


def test_record_family_validation_smokes() -> None:
    now = "2026-08-16T00:00:00Z"

    valid_families = [
        records.AccountRecord(platform="pixiv", native_id="123", observed_at=now),
        records.CandidateRecord(
            candidate_kind="post",
            relation_kind="repost_of",
            review_state="pending",
            score=1,
            scoring_version="scan-v1",
        ),
        records.RawRecord(
            payload=b"payload",
            media_type="application/json",
            object_kind="post",
            native_id=None,
            observed_at=now,
        ),
        records.RemoteRequestRecord(
            1,
            1,
            "pixiv:fetch_post:99:1",
            "fetch_post",
            "99",
            "success",
            now,
        ),
        records.PostPoolObservationRecord(pool_native_id="1", observed_at=now),
        records.ManagedRootRecord(
            root_kind="source",
            root_identity="dev:ino",
            display_label="source",
        ),
        records.AcquisitionLimits(
            max_items=1,
            max_item_bytes=1,
            max_total_bytes=1,
            max_attempts_per_item=1,
            max_seconds=1,
            max_redirects=1,
            max_quarantine_bytes=0,
        ),
        records.CandidateLookupCheckpointRecord(
            1,
            "continuation",
            "x-v1",
            "{}",
            0,
            0,
            now,
        ),
        records.LibraryExpansionPostRecord(1, 2, now),
    ]

    assert len({type(record).__module__ for record in valid_families}) == 8

    invalid_families = [
        lambda: records.AccountRecord(platform="Pixiv", native_id="123", observed_at=now),
        lambda: records.CandidateRecord(
            candidate_kind="post",
            relation_kind="repost_of",
            review_state="nope",
            score=1,
            scoring_version="scan-v1",
        ),
        lambda: records.RawRecord(
            payload=b"payload",
            media_type="application/json",
            object_kind="post",
            native_id=None,
            observed_at=now,
            transport_key="dapi",
        ),
        lambda: records.RemoteRequestRecord(
            1,
            1,
            "pixiv:fetch_post:99:1",
            "fetch_post",
            "99",
            "exploded",
            now,
        ),
        lambda: records.PostPoolObservationRecord(pool_native_id="", observed_at=now),
        lambda: records.ManagedRootRecord(
            root_kind="bogus",
            root_identity="dev:ino",
            display_label="source",
        ),
        lambda: records.AcquisitionLimits(
            max_items=0,
            max_item_bytes=1,
            max_total_bytes=1,
            max_attempts_per_item=1,
            max_seconds=1,
            max_redirects=1,
            max_quarantine_bytes=0,
        ),
        lambda: records.CandidateLookupCheckpointRecord(
            1, "continuation", "x-v1", "{}", -1, 0, now
        ),
        lambda: records.LibraryExpansionPostRecord(1, 0, now),
    ]

    for construct in invalid_families:
        with pytest.raises(ValueError):
            construct()


def test_catalog_writer_public_method_surface_is_stable() -> None:
    signatures = _writer_signatures()

    assert len(signatures) == 53
    assert _digest(signatures) == WRITER_SIGNATURE_DIGEST, "\n".join(signatures)
    assert CatalogWriter.upsert_managed_root is CatalogWriter.register_managed_root


def test_writer_domains_share_the_caller_transaction(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)

        with pytest.raises(RuntimeError, match="force rollback"), database.transaction():
            writer.upsert_account(
                AccountRecord(
                    platform="pixiv",
                    native_id="123",
                    observed_at="2026-08-16T00:00:00Z",
                )
            )
            writer.register_managed_root(
                ManagedRootRecord(
                    root_kind="source",
                    root_identity="dev:ino",
                    display_label="source",
                )
            )
            raise RuntimeError("force rollback")

        assert database.connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
        assert database.connection.execute("SELECT COUNT(*) FROM managed_roots").fetchone()[0] == 0
