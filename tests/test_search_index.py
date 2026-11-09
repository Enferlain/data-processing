"""Local search indexes (bead data-processing-an1, change
add-local-search-indexes).

Pins the slice contract: verified rebuildable projections, path-independent
target identity, snapshot-scoped freshness, offline index steps before
providers, hits as leads bridged to fetches, and the shared post-commit teach
boundary with failure containment.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.discovery.orchestration import DiscoveryOrchestrator
from media_catalog.search_index.importers.e621_export import (
    BUILDER_VERSION,
    import_e621_export,
    sha256_file,
)
from media_catalog.search_index.projection import (
    LOOKUP_FORMAT,
    ProjectionBuilder,
    lookup,
    read_snapshot,
    registered_targets,
)

MD5_A = "0123456789abcdef0123456789abcdef"
MD5_B = "fedcba9876543210fedcba9876543210"


def _write_export(path: Path, rows: list[dict[str, str]]) -> str:
    """A small gzipped e621 posts-export fixture; returns its sha256."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "id",
            "md5",
            "source",
            "parent_id",
            "file_ext",
            "image_width",
            "image_height",
            "created_at",
            "updated_at",
            "is_deleted",
            "tag_string_artist",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    path.write_bytes(gzip.compress(buffer.getvalue().encode("utf-8")))
    return sha256_file(path)


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "private" / "catalog.sqlite3"
    with CatalogDatabase(path) as database, database.transaction():
        platform_id = int(
            database.connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'e621'"
            ).fetchone()[0]
        )
        post_cursor = database.connection.execute(
            """INSERT INTO posts (platform_id, native_post_id, first_seen_at,
                                      last_seen_at)
               VALUES (?, '909', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
            (platform_id,),
        )
        post_id = int(post_cursor.lastrowid)
        database.connection.execute(
            """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                              media_type, declared_md5, observed_at)
               VALUES (?, 'idx:p0', 0, 'image/png', ?, '2026-01-01T00:00:00Z')""",
            (post_id, MD5_A),
        )
    return path


@pytest.fixture()
def artifact(tmp_path: Path) -> Path:
    path = tmp_path / "posts.csv.gz"
    _write_export(
        path,
        [
            {
                "id": "4242",
                "md5": MD5_A,
                "source": '{"https://www.pixiv.net/artworks/123","https://x.com/a/1"}',
                "parent_id": "",
                "file_ext": "png",
                "image_width": "800",
                "image_height": "600",
                "created_at": "2026-02-01T00:00:00Z",
                "updated_at": "2026-02-02T00:00:00Z",
                "is_deleted": "f",
                "tag_string_artist": "some_artist",
            },
            {
                "id": "4243",
                "md5": MD5_B,
                "source": "",
                "parent_id": "4242",
                "file_ext": "jpg",
                "image_width": "400",
                "image_height": "300",
                "created_at": "2026-02-03T00:00:00Z",
                "updated_at": "2026-02-03T00:00:00Z",
                "is_deleted": "f",
                "tag_string_artist": "",
            },
        ],
    )
    return path


def _register(
    catalog: Path,
    provider: str,
    path: Path,
    name: str | None = None,
    *,
    missing: bool = False,
) -> None:
    """Register a projection; ``missing`` inserts the row without validation
    (the planner must handle a registration whose file vanished)."""
    with CatalogDatabase(catalog) as database:
        if missing:
            database.connection.execute(
                """INSERT INTO search_index_registrations
                       (target_name, provider, index_format, private_path,
                        snapshot_revision, registered_at)
                   VALUES (?, ?, 'lookup-v1', ?, 'deadbeef', '2026-11-08T00:00:00Z')""",
                (name or provider, provider, str(path)),
            )
            database.connection.commit()
            return
    from media_catalog.cli_commands.maintenance import _upsert_registration

    snapshot = read_snapshot(path)
    with CatalogDatabase(catalog) as database:
        _upsert_registration(
            database,
            name=name or provider,
            provider=snapshot.provider,
            path=path,
            revision=snapshot.revision,
        )


# ── Projection and importer ──────────────────────────────────────────────


def test_import_builds_verified_projection_and_keeps_artifact(
    catalog: Path, artifact: Path, tmp_path: Path
) -> None:
    destination = tmp_path / "indexes" / "e621" / "lookup.sqlite"
    result = import_e621_export(artifact, destination=destination, checksum=sha256_file(artifact))
    snapshot = read_snapshot(destination)
    assert snapshot.provider == "e621"
    assert snapshot.format == LOOKUP_FORMAT
    assert snapshot.record_count == 2
    assert snapshot.artifact_path == str(artifact)
    assert snapshot.source_digest == result.artifact_digest == sha256_file(artifact)
    assert artifact.is_file()  # retained untouched: the rebuild source
    # Rebuild from the artifact produces an equivalent projection.
    again = tmp_path / "lookup-2.sqlite"
    import_e621_export(artifact, destination=again)
    assert read_snapshot(again).record_count == 2


def test_import_refuses_checksum_mismatch(artifact: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="checksum mismatch"):
        import_e621_export(
            artifact,
            destination=tmp_path / "x.sqlite",
            checksum="0" * 64,
        )
    assert not (tmp_path / "x.sqlite").exists()


def test_lookup_serves_md5_url_and_artist(catalog: Path, artifact: Path, tmp_path: Path) -> None:
    destination = tmp_path / "lookup.sqlite"
    import_e621_export(artifact, destination=destination)
    target = registered_targets_stub(destination)
    md5_hits = lookup(target, method="verified_md5", values=[MD5_A])
    assert [hit["post_native_id"] for hit in md5_hits] == ["4242"]
    url_hits = lookup(
        target, method="source_post_url", values=["https://www.pixiv.net/artworks/123"]
    )
    assert [hit["post_native_id"] for hit in url_hits] == ["4242"]
    artist_hits = lookup(target, method="artist_exact_name", values=["some_artist"])
    assert [hit["post_native_id"] for hit in artist_hits] == ["4242"]
    with pytest.raises(ValueError, match="does not support"):
        lookup(target, method="fetch_post", values=["1"])


def registered_targets_stub(destination: Path):
    """Wrap one projection as an IndexTarget without a catalog registration."""
    from media_catalog.search_index.projection import IndexTarget

    return IndexTarget(
        name="e621",
        provider="e621",
        path=destination,
        snapshot=read_snapshot(destination),
        problem=None,
    )


# ── Planner and executor integration ─────────────────────────────────────


def test_discovery_runs_index_steps_offline_and_records_leads(
    catalog: Path, artifact: Path, tmp_path: Path
) -> None:
    projection = tmp_path / "lookup.sqlite"
    import_e621_export(artifact, destination=projection)
    _register(catalog, "e621", projection)
    with CatalogDatabase(catalog) as database:
        result = DiscoveryOrchestrator(database).start(post_id=_seed_post(catalog))
    steps = {(step["source_kind"], step["method"]): step for step in result["steps"]}
    index_md5 = steps[("index", "declared_md5")]
    assert index_md5["source"] == "e621"
    assert index_md5["status"] == "complete"
    assert index_md5["result_count"] == 1
    # Index steps run without --live; provider steps stay planned.
    provider_md5 = steps[("provider", "declared_md5")]
    assert provider_md5["status"] == "planned"
    # external_post_id is platform-namespaced: an e621 seed CAN serve it here.
    assert steps[("index", "external_post_id")]["status"] == "complete"
    with CatalogDatabase(catalog) as database:
        hits = database.connection.execute(
            "SELECT provider, post_native_id FROM discovery_index_hits"
        ).fetchall()
    assert [(row["provider"], row["post_native_id"]) for row in hits] == [("e621", "4242")]


def test_rerun_skips_fresh_index_steps_until_snapshot_changes(
    catalog: Path, artifact: Path, tmp_path: Path
) -> None:
    projection = tmp_path / "lookup.sqlite"
    import_e621_export(artifact, destination=projection)
    _register(catalog, "e621", projection)
    with CatalogDatabase(catalog) as database:
        first = DiscoveryOrchestrator(database).start(post_id=_seed_post(catalog))
    with CatalogDatabase(catalog) as database:
        second = DiscoveryOrchestrator(database).start(post_id=_seed_post(catalog))
    steps = {(step["source_kind"], step["method"]): step for step in second["steps"]}
    assert steps[("index", "declared_md5")]["status"] == "skipped"
    assert "fresh successful attempt" in steps[("index", "declared_md5")]["detail"]
    # A refreshed snapshot is a new strategy version: everything replans.
    refreshed = tmp_path / "refreshed.csv.gz"
    _write_export(
        refreshed,
        [
            {
                "id": "4242",
                "md5": MD5_A,
                "source": "",
                "parent_id": "",
                "file_ext": "png",
                "image_width": "",
                "image_height": "",
                "created_at": "",
                "updated_at": "2026-03-01T00:00:00Z",
                "is_deleted": "f",
                "tag_string_artist": "",
            }
        ],
    )
    import_e621_export(refreshed, destination=projection)
    _register(catalog, "e621", projection)
    with CatalogDatabase(catalog) as database:
        third = DiscoveryOrchestrator(database).start(post_id=_seed_post(catalog))
    steps = {(step["source_kind"], step["method"]): step for step in third["steps"]}
    assert steps[("index", "declared_md5")]["status"] == "complete"
    assert first["status"] in {"planned", "complete"}


def test_moving_the_projection_preserves_target_identity(
    catalog: Path, artifact: Path, tmp_path: Path
) -> None:
    projection = tmp_path / "lookup.sqlite"
    import_e621_export(artifact, destination=projection)
    _register(catalog, "e621", projection)
    with CatalogDatabase(catalog) as database:
        DiscoveryOrchestrator(database).start(post_id=_seed_post(catalog))
    moved = tmp_path / "moved" / "lookup.sqlite"
    moved.parent.mkdir(exist_ok=True)
    projection.rename(moved)
    _register(catalog, "e621", moved)
    with CatalogDatabase(catalog) as database:
        result = DiscoveryOrchestrator(database).start(post_id=_seed_post(catalog))
    steps = {(step["source_kind"], step["method"]): step for step in result["steps"]}
    # Same target name, same evidence: the prior successful attempt still
    # satisfies the key even though the file moved.
    assert steps[("index", "declared_md5")]["status"] == "skipped"


def test_missing_projection_excludes_target_with_reason(catalog: Path, tmp_path: Path) -> None:
    _register(catalog, "e621", tmp_path / "absent.sqlite", missing=True)
    with CatalogDatabase(catalog) as database:
        targets = registered_targets(database.connection)
    assert targets[0].problem is not None and "missing" in targets[0].problem
    with CatalogDatabase(catalog) as database:
        result = DiscoveryOrchestrator(database).start(post_id=_seed_post(catalog))
    steps = {(step["source_kind"], step["method"]): step for step in result["steps"]}
    assert steps[("index", "declared_md5")]["status"] == "excluded"
    assert "missing" in steps[("index", "declared_md5")]["detail"]


def test_index_hit_bridges_to_wave_a_fetch(
    catalog: Path, artifact: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = tmp_path / "lookup.sqlite"
    import_e621_export(artifact, destination=projection)
    _register(catalog, "e621", projection)
    fetches = _fake_fetch(monkeypatch)
    with CatalogDatabase(catalog) as database:
        result = DiscoveryOrchestrator(database).start(
            post_id=_seed_post(catalog), live=True, request_budget=20
        )
    assert fetches == ["4242"]  # the index lead became a normal fetch step
    fetch_step = next(
        step
        for step in result["steps"]
        if step["method"] == "fetch_post" and step["generation"] == 1
    )
    assert fetch_step["status"] == "complete"


def _fake_fetch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import media_catalog.remote_sync as remote_sync_module

    fetches: list[str] = []

    class FakeSync:
        def __init__(self, database, adapter, *, minimum_interval_seconds):
            pass

        def synchronize(self, operation, target, *, limits, resume_from_run_id=None):
            fetches.append(str(target))

            class Result:
                status = "complete"
                outcome = "success"
                remote_run_id = 1
                record_count = 0
                request_count = 1

            return Result()

    monkeypatch.setattr(remote_sync_module, "MetadataSyncService", FakeSync)
    return fetches


def _seed_post(catalog: Path) -> int:
    with CatalogDatabase(catalog) as database:
        row = database.connection.execute(
            "SELECT post_id FROM posts WHERE native_post_id = '909'"
        ).fetchone()
    assert row is not None
    return int(row["post_id"])


# ── Teach-on-result at the shared boundary ───────────────────────────────


def _gelbooru_projection(tmp_path: Path) -> Path:
    destination = tmp_path / "gelbooru.sqlite"
    builder = ProjectionBuilder(
        provider="gelbooru",
        destination=destination,
        artifact_path=tmp_path / "taught",
        artifact_digest="0" * 64,
        snapshot_revision="seedrev",
        builder_version=BUILDER_VERSION,
    )
    builder.commit()
    return destination


def _normalized_post_page(platform: str, native_id: str, md5: str, url: str):
    from media_catalog.adapters import NormalizedItem, NormalizedPage

    return NormalizedPage(
        (
            NormalizedItem(
                object_kind="post",
                native_id=native_id,
                data={
                    "platform": platform,
                    "canonical_url": url,
                    "observation_time": "2026-11-08T00:00:00Z",
                },
            ),
            NormalizedItem(
                object_kind="media_occurrence",
                native_id=native_id,
                data={
                    "platform": platform,
                    "post_id": native_id,
                    "source_key": f"{platform}:{native_id}:0",
                    "media_type": "image/png",
                    "declared_md5": md5,
                },
            ),
        )
    )


def test_committed_provider_posts_teach_registered_indexes(catalog: Path, tmp_path: Path) -> None:
    from media_catalog.remote_sync.persistence import NormalizedPageWriter
    from media_catalog.writer import CatalogWriter

    projection = _gelbooru_projection(tmp_path)
    _register(catalog, "gelbooru", projection)
    with CatalogDatabase(catalog) as database:
        writer = CatalogWriter(database)
        page_writer = NormalizedPageWriter(writer)
        with database.transaction():
            page_writer.write(
                _normalized_post_page(
                    "gelbooru",
                    "777",
                    MD5_A,
                    "https://gelbooru.com/index.php?page=post&s=view&id=777",
                ),
                observed_at="2026-11-08T00:00:00Z",
                raw_observation_id=_raw_observation(catalog),
                adapter_version="test-v1",
            )
        # The teach happened post-commit: the projection now answers offline.
        target = registered_targets_stub(projection)
        hits = lookup(target, method="verified_md5", values=[MD5_A])
    assert [hit["post_native_id"] for hit in hits] == ["777"]


def test_rolled_back_transactions_do_not_teach(catalog: Path, tmp_path: Path) -> None:
    from media_catalog.remote_sync.persistence import NormalizedPageWriter
    from media_catalog.writer import CatalogWriter

    projection = _gelbooru_projection(tmp_path)
    _register(catalog, "gelbooru", projection)
    with CatalogDatabase(catalog) as database:
        writer = CatalogWriter(database)
        page_writer = NormalizedPageWriter(writer)
        with pytest.raises(RuntimeError, match="boom"), database.transaction():
            page_writer.write(
                _normalized_post_page("gelbooru", "778", MD5_B, "https://gelbooru.com/x"),
                observed_at="2026-11-08T00:00:00Z",
                raw_observation_id=_raw_observation(catalog),
                adapter_version="test-v1",
            )
            raise RuntimeError("boom")
        target = registered_targets_stub(projection)
        hits = lookup(target, method="verified_md5", values=[MD5_B])
    assert hits == []


def test_unwritable_index_never_fails_the_catalog_write(catalog: Path, tmp_path: Path) -> None:
    from media_catalog.remote_sync.persistence import NormalizedPageWriter
    from media_catalog.writer import CatalogWriter

    # Registered path that does not exist: teach silently no-ops.
    _register(catalog, "gelbooru", tmp_path / "absent.sqlite", missing=True)
    with CatalogDatabase(catalog) as database:
        writer = CatalogWriter(database)
        page_writer = NormalizedPageWriter(writer)
        with database.transaction():
            result = page_writer.write(
                _normalized_post_page("gelbooru", "779", MD5_A, "https://gelbooru.com/y"),
                observed_at="2026-11-08T00:00:00Z",
                raw_observation_id=_raw_observation(catalog),
                adapter_version="test-v1",
            )
    assert result >= 1  # the catalog write succeeded


def _raw_observation(catalog: Path) -> int:
    """A real retained raw observation, as the page writer's provenance needs."""
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        row = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'gelbooru'"
        ).fetchone()
        assert row is not None
        payload = connection.execute(
            """INSERT INTO raw_payloads (sha256, media_type, payload, byte_size)
               VALUES (?, 'application/json', '{}', 2)""",
            (f"{_raw_observation_counter[0]:064x}",),
        )
        _raw_observation_counter[0] += 1
        observation = connection.execute(
            """INSERT INTO raw_observations
                   (raw_payload_id, platform_id, object_kind, native_id,
                    media_type, source_schema, status, observed_at,
                    remote_run_id, adapter_version, schema_version,
                    transport_key, transport_version)
               VALUES (?, ?, 'post', '1', 'application/json', 'v1', 'observed',
                       '2026-11-08T00:00:00Z', NULL, 'test-v1', 'test-v1',
                       'test', 'test-v1')""",
            (int(payload.lastrowid), int(row["platform_id"])),
        )
        connection.commit()
        return int(observation.lastrowid)


_raw_observation_counter = [1]


# ── CLI ──────────────────────────────────────────────────────────────────


def test_cli_register_list_import_and_dry_run(
    catalog: Path, artifact: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from media_catalog.cli import main

    main(
        [
            "index",
            "import",
            str(catalog),
            "--provider",
            "e621",
            "--artifact",
            str(artifact),
            "--checksum",
            sha256_file(artifact),
            "--json",
        ]
    )
    imported = json.loads(capsys.readouterr().out)
    assert imported["target"] == "e621"
    assert imported["record_count"] == 2
    default_dest = catalog.parent / "catalog-indexes" / "e621" / "lookup.sqlite"
    assert default_dest.is_file()

    main(["index", "list", str(catalog), "--json"])
    listed = json.loads(capsys.readouterr().out)
    assert listed["count"] == 1
    assert listed["indexes"][0]["target"] == "e621"
    assert listed["indexes"][0]["problem"] is None

    # Register validates: wrong provider name is refused loudly.
    with pytest.raises(SystemExit):
        main(
            [
                "index",
                "register",
                str(catalog),
                "--provider",
                "danbooru",
                "--path",
                str(default_dest),
                "--json",
            ]
        )

    # discover --dry-run shows the index as an ordinary target.
    main(["discover", str(catalog), "--post", str(_seed_post(catalog)), "--dry-run", "--json"])
    dry = json.loads(capsys.readouterr().out)
    index_rows = [step for step in dry["steps"] if step["source_kind"] == "index"]
    assert any(row["status"] == "planned" for row in index_rows)


def test_register_validates_missing_file(
    catalog: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from media_catalog.cli import main

    with pytest.raises(SystemExit) as raised:
        main(
            [
                "index",
                "register",
                str(catalog),
                "--provider",
                "e621",
                "--path",
                str(tmp_path / "nope.sqlite"),
                "--json",
            ]
        )
    assert "not a lookup-v1 projection" in str(raised.value) or raised.value.code
