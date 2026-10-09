"""Export projection contract tests (OpenSpec add-export-projections).

Projections are bounded, reproducible, and auditable: a complete manifest
recipe with deterministic digests, privacy-safe output, offline read-only
planning and execution, stable evidence-layer identifiers, and the assets
and posts kinds with their stated policies.
"""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.projections import plan_export, run_export
from media_catalog.projections.output import parse_jsonl, selection_digest, write_csv
from media_catalog.projections.spec import ProjectionSpec, enforce_allowlist, strip_url_query

FIRST = "2026-01-01T00:00:00Z"
SECOND = "2026-02-01T00:00:00Z"
GENERATED = "2026-10-09T00:00:00Z"


def _seed(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        connection.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name) "
            "VALUES ('danbooru', 'Danbooru')"
        )
        platform = int(
            connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
            ).fetchone()[0]
        )
        connection.execute(
            """INSERT INTO posts (platform_id, native_post_id, canonical_url, rating,
                                  availability, first_seen_at, last_seen_at)
               VALUES (?, '3001', 'https://danbooru.donmai.us/posts/3001?token=secret#frag',
                       'g', 'available', '2026-01-01T00:00:00Z', '2026-02-01T00:00:00Z')""",
            (platform,),
        )
        post = int(
            connection.execute(
                "SELECT post_id FROM posts WHERE native_post_id = '3001'"
            ).fetchone()[0]
        )
        connection.execute(
            """INSERT INTO accounts (platform_id, native_account_id, first_seen_at, last_seen_at)
               VALUES (?, 'artist-one', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
            (platform,),
        )
        account = int(
            connection.execute(
                "SELECT account_id FROM accounts WHERE native_account_id = 'artist-one'"
            ).fetchone()[0]
        )
        connection.execute(
            "INSERT INTO post_participants (post_id, account_id, role, review_state) "
            "VALUES (?, ?, 'artist', 'observed')",
            (post, account),
        )
        connection.execute(
            """INSERT INTO media_occurrences (post_id, source_key, media_index, media_type,
                                              role, observed_at)
               VALUES (?, 'danbooru:3001:0', 0, 'image', 'original', '2026-01-01T00:00:00Z'),
                      (?, 'danbooru:3001:1', 1, 'image', 'variant', '2026-01-01T00:00:00Z')""",
            (post, post),
        )
        occurrence_ids = [
            int(row[0])
            for row in connection.execute(
                "SELECT media_occurrence_id FROM media_occurrences ORDER BY media_occurrence_id"
            )
        ]
        connection.execute(
            """INSERT INTO assets (verified_sha256, storage_kind, verification_method,
                                   storage_path, byte_size, verified_at, detected_mime_type,
                                   detected_width, detected_height)
               VALUES (lower(hex(randomblob(32))), 'managed', 'sha256_adoption',
                       '/private/media/root/aa/bb/secret-file.jpg', 12345,
                       '2026-01-02T00:00:00Z', 'image/jpeg', 800, 600)"""
        )
        asset = int(
            connection.execute(
                "SELECT asset_id FROM assets ORDER BY asset_id DESC LIMIT 1"
            ).fetchone()[0]
        )
        for occurrence in occurrence_ids:
            connection.execute(
                """INSERT INTO occurrence_assets (media_occurrence_id, asset_id, relationship,
                                                  verification_source)
                   VALUES (?, ?, 'exact_bytes', 'byte_verification')""",
                (occurrence, asset),
            )
        connection.execute(
            """INSERT INTO asset_legacy_assertions (asset_id, legacy_path, assertion_kind,
                                                    recorded_at)
               VALUES (?, '/private/legacy/path.jpg', 'ambiguous_asset_path',
                       '2026-01-02T00:00:00Z')""",
            (asset,),
        )
        database.connection.commit()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- Framework: spec digests, privacy guard, serializers ---------------------


def test_spec_digest_is_stable_and_policy_sensitive() -> None:
    base = {
        "kind": "assets",
        "projection_schema_version": "export-projections-v1",
        "policies": {
            "selection": "all verified assets",
            "ordering": "asset_id ascending",
            "dedup": "content_identity_by_sha256",
            "preferred_representation": "not_applicable_pending_phase_d",
            "field_source": "locally_verified_columns_only",
            "url_handling": "no_urls_emitted",
        },
        "tool_version": "0.1.0",
        "source_schema_version": "14",
    }
    assert ProjectionSpec(**base).digest() == ProjectionSpec(**base).digest()
    drifted = {**base, "policies": {**base["policies"], "ordering": "asset_id descending"}}
    assert ProjectionSpec(**base).digest() != ProjectionSpec(**drifted).digest()
    with pytest.raises(ValueError, match="missing policies"):
        ProjectionSpec(
            kind="assets",
            projection_schema_version="v1",
            policies={"selection": "all"},
            tool_version="0.1.0",
            source_schema_version="14",
        )


def test_privacy_guard_strips_urls_and_rejects_undeclared_fields() -> None:
    assert strip_url_query("https://h.example/a.jpg?sig=1&x=2#f") == "https://h.example/a.jpg"
    assert (
        strip_url_query("https://user:pass@h.example:8443/a.jpg?sig=1")
        == "https://h.example:8443/a.jpg"
    )
    assert strip_url_query(None) is None
    with pytest.raises(ValueError, match="outside its allowlist"):
        enforce_allowlist({"asset_id": 1, "storage_path": "/private"}, ("asset_id",))


def test_jsonl_and_csv_are_logically_equivalent(tmp_path: Path) -> None:
    rows = [{"b": 1, "a": "x", "n": {"k": [1, 2]}}, {"b": 2, "a": "y", "n": None}]
    from media_catalog.projections.output import write_jsonl

    count_jsonl, _ = write_jsonl(rows, tmp_path / "r.jsonl")
    count_csv, _ = write_csv(rows, tmp_path / "r.csv")
    assert count_jsonl == count_csv == 2
    import csv as csv_module

    with (tmp_path / "r.csv").open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv_module.DictReader(handle))
    assert parse_jsonl(tmp_path / "r.jsonl") == rows
    assert csv_rows[0]["n"] == '{"k":[1,2]}'
    assert csv_rows[1]["n"] == ""


# --- Projection kinds --------------------------------------------------------


def test_assets_projection_collapses_exact_duplicates(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    result = run_export(
        catalog,
        kind="assets",
        out_dir=tmp_path / "out",
        limit=10,
        clock=lambda: GENERATED,
    )
    rows = parse_jsonl(tmp_path / "out" / "assets-projection.jsonl")
    assert len(rows) == 1
    assert rows[0]["representation_count"] == 2
    assert rows[0]["legacy_assertion_count"] == 1
    assert rows[0]["detected_mime_type"] == "image/jpeg"
    assert result["counts"] == {"included": 1, "excluded": []}


def test_posts_projection_reports_participants_and_strips_urls(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    with CatalogDatabase(catalog) as database:
        database.connection.execute(
            "UPDATE post_participants SET review_state = 'verified' WHERE post_id = 1"
        )
        database.connection.commit()
    run_export(catalog, kind="posts", out_dir=tmp_path / "out", clock=lambda: GENERATED)
    rows = parse_jsonl(tmp_path / "out" / "posts-projection.jsonl")
    assert len(rows) == 1
    row = rows[0]
    assert row["platform"] == "danbooru"
    assert row["native_post_id"] == "3001"
    assert row["canonical_url"] == "https://danbooru.donmai.us/posts/3001"
    assert row["occurrence_count"] == 2
    assert row["participants"] == [
        {
            "platform": "danbooru",
            "account_native_id": "artist-one",
            "role": "artist",
            "review_state": "verified",
        }
    ]
    assert row["participant_count"] == 1


def test_selection_and_limit_policies_report_exclusions(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    with CatalogDatabase(catalog) as database:
        database.connection.execute(
            """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
               VALUES ((SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'),
                       '3002', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"""
        )
        database.connection.commit()
    plan = plan_export(catalog, kind="posts", limit=1)
    assert plan["preview"] is True
    assert plan["counts"] == {
        "included": 1,
        "excluded": [{"reason": "excluded_by_limit", "count": 1}],
    }
    with pytest.raises(ValueError, match="does not support a platform filter"):
        plan_export(catalog, kind="assets", platform="danbooru")
    filtered = plan_export(catalog, kind="posts", limit=10, platform="danbooru")
    assert filtered["counts"] == {"included": 2, "excluded": []}
    assert "(platform=danbooru)" in filtered["policies"]["selection"]


# --- Determinism and audit chain ---------------------------------------------


def test_rerun_reproduces_digests_and_evidence_change_moves_selection(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    first = run_export(catalog, kind="posts", out_dir=tmp_path / "one", clock=lambda: GENERATED)
    second = run_export(catalog, kind="posts", out_dir=tmp_path / "two", clock=lambda: FIRST)
    assert first["spec_digest"] == second["spec_digest"]
    assert first["selection_digest"] == second["selection_digest"]
    assert {f["content_digest"] for f in first["files"]} == {
        f["content_digest"] for f in second["files"]
    }
    assert first["generated_at"] != second["generated_at"]
    assert _file_sha(tmp_path / "one" / "posts-projection.jsonl") == _file_sha(
        tmp_path / "two" / "posts-projection.jsonl"
    )

    with CatalogDatabase(catalog) as database:
        database.connection.execute(
            """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
               VALUES ((SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'),
                       '3003', '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z')"""
        )
        database.connection.commit()
    third = run_export(catalog, kind="posts", out_dir=tmp_path / "three", clock=lambda: GENERATED)
    assert third["spec_digest"] == first["spec_digest"]
    assert third["selection_digest"] != first["selection_digest"]


def test_manifest_recipe_is_complete(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    result = run_export(catalog, kind="assets", out_dir=tmp_path / "out", clock=lambda: GENERATED)
    for key in (
        "kind",
        "projection_schema_version",
        "policies",
        "tool_version",
        "source_schema_version",
        "generated_at",
        "files",
        "counts",
        "identifiers",
        "spec_digest",
        "selection_digest",
    ):
        assert key in result, key
    assert set(result["policies"]) == {
        "selection",
        "ordering",
        "dedup",
        "preferred_representation",
        "field_source",
        "url_handling",
    }
    manifest = json.loads(
        (tmp_path / "out" / "assets-projection.manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["spec_digest"] == result["spec_digest"]
    assert manifest["counts"] == result["counts"]
    written = {entry["name"] for entry in manifest["files"]}
    assert written == {"assets-projection.jsonl", "assets-projection.csv"}


def test_plan_writes_nothing(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    before = _file_sha(catalog)
    plan = plan_export(catalog, kind="posts")
    assert plan["preview"] is True
    assert not any(tmp_path.iterdir()) or all(path == catalog for path in tmp_path.iterdir())
    assert _file_sha(catalog) == before


# --- Privacy and offline execution -------------------------------------------


def test_output_never_contains_private_material(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    for kind in ("assets", "posts"):
        run_export(catalog, kind=kind, out_dir=tmp_path / kind, clock=lambda: GENERATED)
    for path in sorted((tmp_path / "assets").iterdir()) + sorted((tmp_path / "posts").iterdir()):
        text = path.read_text(encoding="utf-8")
        assert "/private" not in text, path
        assert "secret" not in text, path
        assert "token=" not in text, path
        assert "user:pass" not in text, path
        assert "storage_path" not in text, path


def test_cli_export_is_offline_and_leaves_catalog_unchanged(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    from media_catalog.cli import main

    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    before = _file_sha(catalog)

    def fail_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted")

    socket_default = socket.socket.connect
    socket.socket.connect = fail_connect
    try:
        main(
            [
                "export",
                "run",
                str(catalog),
                "--kind",
                "posts",
                "--out-dir",
                str(tmp_path / "out"),
                "--format",
                "jsonl",
                "--json",
            ]
        )
        executed = json.loads(capsys.readouterr().out)
    finally:
        socket.socket.connect = socket_default
    assert executed["counts"]["included"] == 1
    assert "preview" not in executed  # run results are manifests, not previews
    assert (tmp_path / "out" / "posts-projection.jsonl").is_file()
    assert (tmp_path / "out" / "posts-projection.manifest.json").is_file()
    assert _file_sha(catalog) == before
    assert not catalog.with_suffix(".sqlite3-wal").exists()
    # The deterministic selection digest matches a direct service run.
    assert executed["selection_digest"] == selection_digest(["1:danbooru:3001"])
