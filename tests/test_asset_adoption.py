from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from media_catalog.asset_adoption import (
    adopt_assets,
    find_exact_duplicates,
    list_failed_adoption_items,
    plan_adoption,
)
from media_catalog.asset_storage import AssetStorage, SourceChangedError, UnsafePathError
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    ManagedRootRecord,
    MediaOccurrenceRecord,
    OccurrenceSourceRecord,
    PostRecord,
)
from media_catalog.writer import CatalogWriter

NOW = "2026-08-09T00:00:00Z"


def _png(*, color: tuple[int, int, int] = (20, 30, 40)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (4, 3), color=color).save(output, format="PNG")
    return output.getvalue()


def _catalog_with_sources(path: Path, source: Path, *, count: int = 1) -> list[int]:
    source_identity = hashlib.sha256(str(source.resolve()).encode()).hexdigest()
    with CatalogDatabase(path) as database:
        writer = CatalogWriter(database)
        with database.transaction():
            source_id = writer.register_managed_root(
                ManagedRootRecord("source", source_identity, "source", str(source.resolve()), NOW)
            )
            occurrence_ids: list[int] = []
            for index in range(count):
                post_id = writer.upsert_post(PostRecord("x", str(index + 1), NOW)).id
                occurrence_id = writer.upsert_media(
                    post_id,
                    MediaOccurrenceRecord(
                        f"media:{index}",
                        index,
                        "image",
                        observed_at=NOW,
                        local_path=f"image-{index}.png",
                    ),
                ).id
                writer.add_occurrence_source(
                    OccurrenceSourceRecord(
                        occurrence_id,
                        "legacy_local",
                        f"image-{index}.png",
                        NOW,
                        managed_root_id=source_id,
                        source_identity=source_identity,
                    )
                )
                occurrence_ids.append(occurrence_id)
        return occurrence_ids


def test_plan_is_read_only_and_reports_missing_candidates(tmp_path: Path) -> None:
    source = tmp_path / "source"
    managed = tmp_path / "managed"
    source.mkdir()
    managed.mkdir()
    (source / "image-0.png").write_bytes(_png())
    catalog = tmp_path / "catalog.sqlite3"
    _catalog_with_sources(catalog, source, count=2)
    before = catalog.read_bytes()

    plan = plan_adoption(catalog, source, managed)

    assert plan.planned_count == 1
    assert plan.skipped_count == 1
    assert {item.classification for item in plan.items} == {"eligible", "missing"}
    assert catalog.read_bytes() == before
    assert not (managed / "staging").exists()


def test_plan_json_redacts_absolute_unsafe_source_paths(tmp_path: Path) -> None:
    source = tmp_path / "source"
    managed = tmp_path / "managed"
    source.mkdir()
    managed.mkdir()
    catalog = tmp_path / "catalog.sqlite3"
    _catalog_with_sources(catalog, source)
    with CatalogDatabase(catalog) as database:
        database.connection.execute(
            "UPDATE occurrence_sources SET relative_path = ?",
            (str(tmp_path / "private" / "secret.jpg"),),
        )
        database.connection.commit()
    plan = plan_adoption(catalog, source, managed)
    result = plan.as_dict()
    assert result["items"][0]["classification"] == "unsafe_path"
    assert result["items"][0]["relative_path"] == "<redacted>"
    assert "secret.jpg" not in str(result)


def test_service_does_not_resolve_away_a_symlinked_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    source_link = tmp_path / "source-link"
    source_link.symlink_to(source, target_is_directory=True)
    managed = tmp_path / "managed"
    managed.mkdir()
    catalog = tmp_path / "catalog.sqlite3"
    _catalog_with_sources(catalog, source)

    with pytest.raises(UnsafePathError):
        plan_adoption(catalog, source_link, managed)
    assert not (managed / "sha256").exists()


def test_execution_refuses_roots_replaced_after_planning(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "image-0.png").write_bytes(_png())
    managed = tmp_path / "managed"
    managed.mkdir()
    catalog = tmp_path / "catalog.sqlite3"
    _catalog_with_sources(catalog, source)
    plan = plan_adoption(catalog, source, managed)

    source.rename(tmp_path / "original-source")
    source.mkdir()
    (source / "image-0.png").write_bytes(_png(color=(200, 1, 1)))
    with CatalogDatabase(catalog) as database, pytest.raises(SourceChangedError):
        adopt_assets(database, source, managed, plan=plan)
    assert not (managed / "sha256").exists()
    with CatalogDatabase.open_read_only(catalog) as database:
        assert database.connection.execute("SELECT COUNT(*) FROM adoption_runs").fetchone()[0] == 0


def test_adoption_is_idempotent_and_persists_provenance(tmp_path: Path) -> None:
    source = tmp_path / "source"
    managed = tmp_path / "managed"
    source.mkdir()
    managed.mkdir()
    payload = _png()
    (source / "image-0.png").write_bytes(payload)
    catalog = tmp_path / "catalog.sqlite3"
    occurrence_ids = _catalog_with_sources(catalog, source)

    with CatalogDatabase(catalog) as database:
        first = adopt_assets(database, source, managed)
        second = adopt_assets(database, source, managed)
        assert first.status == "complete"
        assert second.status == "complete"
        assert first.outcomes == {"adopted": 1}
        assert second.outcomes == {"existing": 1}
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
        assert (
            database.connection.execute("SELECT COUNT(*) FROM asset_locations").fetchone()[0] == 1
        )
        assert database.connection.execute("SELECT COUNT(*) FROM adoption_items").fetchone()[0] == 2
        assert database.connection.execute(
            "SELECT COUNT(*) FROM asset_fingerprints WHERE fingerprint_kind = 'sha256'"
        ).fetchone()[0] == 1
        assert database.connection.execute(
            "SELECT media_occurrence_id FROM occurrence_assets"
        ).fetchone()[0] == occurrence_ids[0]


def test_partial_failure_continues_and_exact_duplicates_are_queryable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    managed = tmp_path / "managed"
    source.mkdir()
    managed.mkdir()
    payload = _png()
    (source / "image-0.png").write_bytes(payload)
    (source / "image-1.png").write_bytes(payload)
    catalog = tmp_path / "catalog.sqlite3"
    _catalog_with_sources(catalog, source, count=2)
    with CatalogDatabase(catalog) as database:
        # Deliberately disagree with the calculated bytes on one occurrence.
        database.connection.execute(
            "UPDATE media_occurrences SET declared_sha256 = ? WHERE media_occurrence_id = 2",
            ("0" * 64,),
        )
        database.connection.commit()
        summary = adopt_assets(database, source, managed)
        assert summary.status == "partial"
        assert summary.completed_count == 1
        assert summary.failed_count == 1
        assert summary.outcomes["hash_mismatch"] == 1
        failures = list_failed_adoption_items(database, run_id=summary.run_id)
        assert len(failures) == 1
        assert failures[0]["sha256"] == hashlib.sha256(payload).hexdigest()
        assert failures[0]["md5"] == hashlib.md5(payload, usedforsecurity=False).hexdigest()
        assert failures[0]["byte_size"] == len(payload)
        database.connection.execute(
            "UPDATE media_occurrences SET declared_sha256 = ? WHERE media_occurrence_id = 2",
            (hashlib.sha256(payload).hexdigest(),),
        )
        database.connection.commit()
        assert adopt_assets(database, source, managed).status == "complete"
        assert len(find_exact_duplicates(database)) == 1
        target = database.connection.execute(
            "SELECT relative_path FROM asset_locations"
        ).fetchone()[0]
        assert (managed / target).read_bytes() == payload


def test_interruption_preserves_committed_items_and_a_rerun_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    managed = tmp_path / "managed"
    source.mkdir()
    managed.mkdir()
    (source / "image-0.png").write_bytes(_png(color=(1, 2, 3)))
    (source / "image-1.png").write_bytes(_png(color=(4, 5, 6)))
    catalog = tmp_path / "catalog.sqlite3"
    _catalog_with_sources(catalog, source, count=2)
    original_adopt = AssetStorage.adopt
    calls = 0

    def interrupt_second(self: AssetStorage, relative_path: str, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return original_adopt(self, relative_path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(AssetStorage, "adopt", interrupt_second)
    with CatalogDatabase(catalog) as database:
        with pytest.raises(KeyboardInterrupt):
            adopt_assets(database, source, managed)
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
        assert database.connection.execute("SELECT COUNT(*) FROM adoption_items").fetchone()[0] == 1
        assert (
            database.connection.execute("SELECT status FROM adoption_runs").fetchone()[0]
            == "running"
        )

    monkeypatch.setattr(AssetStorage, "adopt", original_adopt)
    with CatalogDatabase(catalog) as database:
        resumed = adopt_assets(database, source, managed)
        assert resumed.status == "complete"
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 2


def test_rerun_reports_corrupt_existing_cas_without_overwriting_it(tmp_path: Path) -> None:
    source = tmp_path / "source"
    managed = tmp_path / "managed"
    source.mkdir()
    managed.mkdir()
    payload = _png()
    (source / "image-0.png").write_bytes(payload)
    catalog = tmp_path / "catalog.sqlite3"
    _catalog_with_sources(catalog, source)
    with CatalogDatabase(catalog) as database:
        adopt_assets(database, source, managed)
        relative = database.connection.execute(
            "SELECT relative_path FROM asset_locations"
        ).fetchone()[0]
        target = managed / relative
        target.write_bytes(b"corrupt")
        summary = adopt_assets(database, source, managed)
        assert summary.status == "partial"
        assert summary.outcomes["storage_integrity_failed"] == 1
        assert summary.items[0]["sha256"] == hashlib.sha256(payload).hexdigest()
        assert summary.items[0]["md5"] == hashlib.md5(payload, usedforsecurity=False).hexdigest()
        assert summary.items[0]["byte_size"] == len(payload)
        assert target.read_bytes() == b"corrupt"
