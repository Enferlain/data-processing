"""Materialize-a-seed tests (add-materialize-seed).

The operator seed entry point: bundles persist as operator_seed import
evidence, stubs land with availability unknown and typed references, the
operation is idempotent, decides nothing, and the stub is a valid lookup
seed exactly like a synced post.
"""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest
from PIL import Image

from media_catalog.adapters import LookupStrategy
from media_catalog.adapters.danbooru import DANBOORU
from media_catalog.candidate_lookup import (
    LookupLimits,
    plan_candidate_lookup,
)
from media_catalog.database import CatalogDatabase
from media_catalog.seeding import SeedMaterializationService

NOW = "2026-10-06T00:00:00Z"
PIXIV_URL = "https://www.pixiv.net/artworks/150422897"
X_URL = "https://x.com/yyqw7151/status/1950567258528547071"


def test_seed_materializes_stub_with_references_and_provenance(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        result = SeedMaterializationService(database).materialize(
            [PIXIV_URL, X_URL],
            note="spotted while browsing",
            declared_md5="0123456789ABCDEF0123456789ABCDEF",
            observed_at=NOW,
        )

        assert result["status"] == "materialized"
        assert result["platform"] == "pixiv"
        assert result["native_post_id"] == "150422897"
        assert result["url_count"] == 2
        assert result["reference_count"] == 4

        connection = database.connection
        stub = connection.execute(
            """SELECT p.availability, p.canonical_url, p.raw_observation_id,
                      pl.platform_key
                 FROM posts p JOIN platforms pl USING (platform_id)
                WHERE p.post_id = ?""",
            (result["post_id"],),
        ).fetchone()
        assert stub["platform_key"] == "pixiv"
        assert stub["availability"] == "unknown"
        assert stub["canonical_url"] == PIXIV_URL

        # The bundle is retained as raw import evidence under operator_seed.
        raw = connection.execute(
            """SELECT ro.raw_observation_id, ro.import_run_id, ir.source_kind, ir.status
                 FROM raw_observations ro JOIN import_runs ir USING (import_run_id)
                WHERE ro.raw_observation_id = ?""",
            (stub["raw_observation_id"],),
        ).fetchone()
        assert raw["source_kind"] == "operator_seed"
        assert raw["status"] == "complete"

        # Every URL attached as a source_url link reference...
        source_urls = {
            row[0]
            for row in connection.execute(
                """SELECT el.canonical_url
                     FROM post_external_references per
                     JOIN external_links el ON el.external_link_id = per.external_link_id
                    WHERE per.post_id = ? AND per.reference_kind = 'source_url'""",
                (result["post_id"],),
            )
        }
        assert source_urls == {PIXIV_URL, X_URL}
        # ...and as a typed provider_id reference planning can seed from.
        typed = {
            tuple(row)
            for row in connection.execute(
                """SELECT tp.platform_key, pr.native_identifier
                     FROM post_external_references per
                     JOIN platform_references pr
                            ON pr.platform_reference_id = per.platform_reference_id
                     JOIN platforms tp ON tp.platform_id = pr.platform_id
                    WHERE per.post_id = ? AND per.reference_kind = 'provider_id'""",
                (result["post_id"],),
            )
        }
        assert typed == {("pixiv", "150422897"), ("x", "1950567258528547071")}

        # Nothing was decided for the stub.
        assert connection.execute("SELECT COUNT(*) FROM post_match_candidates").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM post_relations").fetchone()[0] == 0


def test_seed_is_idempotent_for_the_same_bundle(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        service = SeedMaterializationService(database)
        first = service.materialize([PIXIV_URL], note="same", observed_at=NOW)
        second = service.materialize([PIXIV_URL], note="same", observed_at=NOW)
        assert second["status"] == "existing"
        assert second["post_id"] == first["post_id"]
        assert second["import_run_id"] == first["import_run_id"]
        assert database.connection.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0] == 1
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 1
        )


def test_seed_bundle_adding_a_url_creates_new_evidence_not_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        service = SeedMaterializationService(database)
        first = service.materialize([PIXIV_URL], observed_at=NOW)
        extended = service.materialize([PIXIV_URL, X_URL], observed_at=NOW)
        assert extended["status"] == "materialized"
        assert extended["post_id"] == first["post_id"]
        assert extended["import_run_id"] != first["import_run_id"]
        assert database.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1


@pytest.mark.parametrize(
    "urls, match",
    (
        ([], "at least one URL"),
        (["https://example.test/nothing"], "known platform post"),
        (["https://x.com/SomeHandle"], "stable post identity"),
        (
            [PIXIV_URL, "https://www.pixiv.net/artworks/111111111"],
            "conflicts with another URL",
        ),
    ),
)
def test_seed_rejects_invalid_bundles_before_writing(
    tmp_path: Path, urls: list[str], match: str
) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        with pytest.raises(ValueError, match=match):
            SeedMaterializationService(database).materialize(urls, observed_at=NOW)
        assert database.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
        assert database.connection.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0] == 0


def test_seed_rejects_malformed_note_and_md5(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        service = SeedMaterializationService(database)
        with pytest.raises(ValueError, match="note"):
            service.materialize([PIXIV_URL], note="   ", observed_at=NOW)
        with pytest.raises(ValueError, match="32-character hex"):
            service.materialize([PIXIV_URL], declared_md5="zz", observed_at=NOW)
        assert database.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0


def test_materialized_stub_seeds_external_post_id_lookup_planning(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        result = SeedMaterializationService(database).materialize(
            [X_URL, PIXIV_URL], observed_at=NOW
        )

    def fail_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted")

    socket_default = socket.socket.connect
    socket.socket.connect = fail_connect
    try:
        plan = plan_candidate_lookup(
            path,
            f"post:{result['post_id']}",
            DANBOORU,
            (LookupStrategy.EXTERNAL_POST_ID, LookupStrategy.VERIFIED_MD5),
            limits=LookupLimits(1, 1, 10, 30),
        )
    finally:
        socket.socket.connect = socket_default

    assert plan.provider == "danbooru"
    assert len(plan.items) == 1
    assert plan.items[0].material.values == ("150422897",)
    assert plan.items[0].material.platform == "pixiv"
    assert plan.exclusions == ({"strategy": "verified_md5", "reason": "missing_seed_material"},)


def test_seed_cli_creates_stub_offline(tmp_path: Path, capsys, monkeypatch) -> None:
    from media_catalog.cli import main

    monkeypatch.chdir(tmp_path)
    main(
        [
            "seed",
            "create",
            "seed-catalog.sqlite3",
            "--url",
            PIXIV_URL,
            "--note",
            "private note",
            "--json",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "materialized"
    assert output["platform"] == "pixiv"
    assert output["native_post_id"] == "150422897"
    # The note and URLs stay out of the public output.
    rendered = json.dumps(output)
    assert "private note" not in rendered
    assert "pixiv.net" not in rendered
    assert str(tmp_path) not in rendered


def _seed_image(root: Path, name: str = "found_artwork.png") -> Path:
    path = root / name
    Image.new("RGB", (64, 48), (200, 30, 30)).save(path)
    return path


def test_seed_with_file_adopts_verified_asset_and_seeds_hash_lookups(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    source = tmp_path / "downloads"
    source.mkdir()
    media_root = tmp_path / "media-root"
    media_root.mkdir()
    image = _seed_image(source)
    real_md5 = hashlib.md5(image.read_bytes()).hexdigest()

    with CatalogDatabase(catalog) as database:
        result = SeedMaterializationService(database).materialize(
            [PIXIV_URL],
            declared_md5=real_md5,
            observed_at=NOW,
            file=image,
            media_root=media_root,
        )
        assert result["status"] == "materialized"
        adoption = result["adoption"]
        assert adoption["status"] == "adopted"
        assert adoption["width"] == 64
        assert adoption["height"] == 48
        assert adoption["phash_recorded"] is True
        assert adoption["verified_md5"] == real_md5
        assert adoption["verified_sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()

        connection = database.connection
        occurrence = connection.execute(
            "SELECT declared_md5 FROM media_occurrences WHERE post_id = ?",
            (result["post_id"],),
        ).fetchone()
        assert occurrence["declared_md5"] == real_md5

    def fail_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted")

    socket_default = socket.socket.connect
    socket.socket.connect = fail_connect
    try:
        for strategy in (LookupStrategy.DECLARED_MD5, LookupStrategy.VERIFIED_MD5):
            plan = plan_candidate_lookup(
                catalog,
                f"post:{result['post_id']}",
                DANBOORU,
                (strategy,),
                limits=LookupLimits(1, 1, 10, 30),
            )
            assert len(plan.items) == 1, strategy
            assert plan.items[0].material.values == (real_md5,)
    finally:
        socket.socket.connect = socket_default


def test_seed_with_file_is_idempotent_across_runs(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    source = tmp_path / "downloads"
    source.mkdir()
    media_root = tmp_path / "media-root"
    media_root.mkdir()
    image = _seed_image(source)

    with CatalogDatabase(catalog) as database:
        service = SeedMaterializationService(database)
        first = service.materialize([PIXIV_URL], observed_at=NOW, file=image, media_root=media_root)
        second = service.materialize(
            [PIXIV_URL], observed_at=NOW, file=image, media_root=media_root
        )
        assert second["status"] == "existing"
        assert second["post_id"] == first["post_id"]
        assert second["adoption"]["status"] == "already-adopted"
        connection = database.connection
        assert connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0] == 1


def test_seed_rejects_declared_md5_mismatch_before_writes(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    source = tmp_path / "downloads"
    source.mkdir()
    media_root = tmp_path / "media-root"
    media_root.mkdir()
    image = _seed_image(source)

    with CatalogDatabase(catalog) as database:
        with pytest.raises(ValueError, match="does not match the supplied file"):
            SeedMaterializationService(database).materialize(
                [PIXIV_URL],
                declared_md5="0123456789abcdef0123456789abcdef",
                observed_at=NOW,
                file=image,
                media_root=media_root,
            )
        connection = database.connection
        assert connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0


@pytest.mark.parametrize(
    "kwargs, match",
    (
        ({"file": "missing.png", "media_root": "media"}, "existing regular file"),
        ({"media_root": "media"}, "only used with a local seed file"),
        ({"file": "placeholder"}, "required when seeding with a local file"),
    ),
)
def test_seed_rejects_malformed_file_inputs(
    tmp_path: Path, kwargs: dict[str, str], match: str
) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    if kwargs.get("file") == "placeholder":
        kwargs["file"] = _seed_image(tmp_path)
    if kwargs.get("media_root") == "media":
        kwargs["media_root"] = media_root
    with (
        CatalogDatabase(tmp_path / "catalog.sqlite3") as database,
        pytest.raises(ValueError, match=match),
    ):
        SeedMaterializationService(database).materialize([PIXIV_URL], observed_at=NOW, **kwargs)


def test_seed_cli_with_file_adopts(tmp_path: Path, capsys, monkeypatch) -> None:
    from media_catalog.cli import main

    monkeypatch.chdir(tmp_path)
    (tmp_path / "downloads").mkdir()
    media_root = tmp_path / "media-root"
    media_root.mkdir()
    image = _seed_image(tmp_path / "downloads")

    main(
        [
            "seed",
            "create",
            "seed-catalog.sqlite3",
            "--url",
            PIXIV_URL,
            "--file",
            str(image),
            "--media-root",
            str(media_root),
            "--json",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert output["adoption"]["status"] == "adopted"
    assert output["adoption"]["phash_recorded"] is True
    assert str(tmp_path) not in json.dumps(output)
