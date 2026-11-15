"""Operator labels (bead data-processing-j7l, change add-operator-labels):
free-form local facts on subjects — lifecycle, append-only assertions with
latest-wins state, identical-content search expansion, and never touching
provider tag tables."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.operator_labels import (
    apply_label,
    create_label,
    current_labels,
    list_labels,
    retire_label,
    revoke_label,
    search_label,
)

MD5 = "0123456789abcdef0123456789abcdef"
OTHER_MD5 = "f" * 32


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database, database.transaction():
        platform_id = int(
            database.connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'gelbooru'"
            ).fetchone()[0]
        )
        for native, md5 in (("ol-1", MD5), ("ol-2", OTHER_MD5), ("ol-3", MD5)):
            post = database.connection.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform_id, native),
            )
            database.connection.execute(
                """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                                      media_type, declared_md5, observed_at)
                   VALUES (?, 'ol:p', 0, 'image/png', ?, '2026-01-01T00:00:00Z')""",
                (int(post.lastrowid), md5),
            )
        for name, sha in (("s1", "a" * 64), ("s2", "a" * 64), ("s3", "b" * 64)):
            session = database.connection.execute(
                "INSERT INTO discovery_sessions (input_kind, started_at)"
                " VALUES ('local_file', '2026-11-15T00:00:00Z')"
            )
            database.connection.execute(
                """INSERT INTO discovery_file_seeds
                       (discovery_session_id, verified_md5, verified_sha256, byte_size,
                        source_path, observed_at)
                   VALUES (?, ?, ?, 1, ?, '2026-11-15T00:00:00Z')""",
                (int(session.lastrowid), MD5 if name != "s3" else OTHER_MD5, sha, f"{name}.bin"),
            )
    return path


def _seed_ids(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        str(row[1]): int(row[0])
        for row in connection.execute(
            "SELECT discovery_file_seed_id, source_path FROM discovery_file_seeds"
        )
    }


def _post_ids(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        str(row[1]): int(row[0])
        for row in connection.execute("SELECT post_id, native_post_id FROM posts")
    }


def test_label_lifecycle_is_case_insensitive_and_retire_keeps_history(
    catalog: Path,
) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        created = create_label(connection, "ai-generated")
        again = create_label(connection, "AI-Generated")
        assert created["status"] == "created" and again["status"] == "existing"
        retired = retire_label(connection, "ai-generated")
        assert retired["retired_at"] is not None
        with pytest.raises(ValueError, match="retired"):
            create_label(connection, "ai-generated")
        assert [label["name"] for label in list_labels(connection)] == ["ai-generated"]


def test_apply_revoke_reapply_is_append_only_latest_wins(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        seed = _seed_ids(connection)["s1.bin"]
        create_label(connection, "needs-review")
        apply_label(connection, "needs-review", "file_seed", seed, by="imi")
        assert "needs-review" in current_labels(connection, "file_seed", seed)["labels"]
        revoke_label(connection, "needs-review", "file_seed", seed, by="imi")
        assert current_labels(connection, "file_seed", seed)["labels"] == {}
        apply_label(connection, "needs-review", "file_seed", seed, by="imi")
        assert "needs-review" in current_labels(connection, "file_seed", seed)["labels"]
        rows = connection.execute(
            "SELECT state FROM operator_label_assertions ORDER BY operator_label_assertion_id"
        ).fetchall()
        assert [row[0] for row in rows] == ["applied", "revoked", "applied"]


def test_apply_validates_label_and_subject(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        with pytest.raises(ValueError, match="not found"):
            apply_label(connection, "missing", "post", 1)
        create_label(connection, "ai-generated")
        with pytest.raises(ValueError, match="not found"):
            apply_label(connection, "ai-generated", "post", 999_999)
        retire_label(connection, "ai-generated")
        with pytest.raises(ValueError, match="retired"):
            apply_label(connection, "ai-generated", "post", 1)


def test_search_expands_to_identical_content_only(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        seeds = _seed_ids(connection)
        posts = _post_ids(connection)
        create_label(connection, "ai-generated")
        apply_label(connection, "ai-generated", "file_seed", seeds["s1.bin"])

        result = search_label(connection, "ai-generated")
        assert result["subjects"] == [
            {"subject": f"file_seed:{seeds['s1.bin']}", "basis": "direct"}
        ]
        identical = {entry["subject"] for entry in result["identical_content_subjects"]}
        # same hash pair seed + posts declaring the same md5
        assert identical == {
            f"file_seed:{seeds['s2.bin']}",
            f"post:{posts['ol-1']}",
            f"post:{posts['ol-3']}",
        }
        # different bytes: never inherited, variant or not
        assert f"post:{posts['ol-2']}" not in identical
        assert f"file_seed:{seeds['s3.bin']}" not in identical

        show = current_labels(connection, "post", posts["ol-1"])
        assert show["labels"] == {}
        inherited = {entry["subject"]: entry["labels"] for entry in show["identical_content"]}
        assert inherited[f"file_seed:{seeds['s1.bin']}"] == ["ai-generated"]


def test_provider_tag_tables_untouched(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        create_label(connection, "kemono-batch")
        apply_label(connection, "kemono-batch", "post", 1)
        assert (
            connection.execute("SELECT count(*) FROM tags WHERE name = 'kemono-batch'").fetchone()[
                0
            ]
            == 0
        )


def test_cli_round_trip(catalog: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from media_catalog.cli import main

    seed = _seed_ids(sqlite3.connect(catalog))["s1.bin"]
    main(["tag", "create", str(catalog), "batch-2026-11", "--json"])
    capsys.readouterr()
    main(["tag", "apply", str(catalog), "batch-2026-11", "--file-seed", str(seed), "--json"])
    capsys.readouterr()
    main(["tag", "show", str(catalog), "--file-seed", str(seed), "--json"])
    shown = json.loads(capsys.readouterr().out)
    assert list(shown["labels"]) == ["batch-2026-11"]
    main(["tag", "search", str(catalog), "batch-2026-11", "--json"])
    found = json.loads(capsys.readouterr().out)
    assert found["subjects_total"] == 1


def test_list_counts_current_state_not_history(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        seed = _seed_ids(connection)["s1.bin"]
        create_label(connection, "needs-review")
        apply_label(connection, "needs-review", "file_seed", seed)
        revoke_label(connection, "needs-review", "file_seed", seed)
        (entry,) = list_labels(connection)
        assert entry["assertions"] == 2
        assert entry["applied_subjects"] == 0


def test_post_to_post_identical_expansion_without_any_seed_label(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        posts = _post_ids(connection)
        seeds = _seed_ids(connection)
        create_label(connection, "series")
        apply_label(connection, "series", "post", posts["ol-1"])
        result = search_label(connection, "series")
        identical = {entry["subject"] for entry in result["identical_content_subjects"]}
        # ol-3 shares the declared md5; so do the s1/s2 seeds; ol-2 does not
        assert identical == {
            f"post:{posts['ol-3']}",
            f"file_seed:{seeds['s1.bin']}",
            f"file_seed:{seeds['s2.bin']}",
        }
        inherited = current_labels(connection, "post", posts["ol-3"])
        assert inherited["identical_content"][0]["labels"] == ["series"]


def test_same_timestamp_tiebreak_is_numeric_latest_id_wins(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        seed = _seed_ids(connection)["s1.bin"]
        create_label(connection, "raced")
        label_id = int(
            connection.execute(
                "SELECT operator_label_id FROM operator_labels WHERE name = 'raced'"
            ).fetchone()[0]
        )
        same = "2026-11-15T00:00:00.000000Z"
        for state in ("applied", "revoked"):  # ascending ids, identical timestamps
            connection.execute(
                """INSERT INTO operator_label_assertions
                       (operator_label_id, subject_kind, subject_id, state, asserted_by,
                        note, observed_at)
                   VALUES (?, 'file_seed', ?, ?, 'imi', NULL, ?)""",
                (label_id, seed, state, same),
            )
        connection.commit()
        assert current_labels(connection, "file_seed", seed)["labels"] == {}
        # 10 assertions before a would-be "id 9 > id 10" text-comparison trap
        for index in range(12):
            connection.execute(
                """INSERT INTO operator_label_assertions
                       (operator_label_id, subject_kind, subject_id, state, asserted_by,
                        note, observed_at)
                   VALUES (?, 'file_seed', ?, ?, 'imi', ?, ?)""",
                (label_id, seed, "applied", f"n{index}", same),
            )
        connection.commit()
        shown = current_labels(connection, "file_seed", seed)["labels"]
        assert list(shown) == ["raced"]


def test_validation_errors(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        seed = _seed_ids(connection)["s1.bin"]
        create_label(connection, "checked")
        with pytest.raises(ValueError, match="asserted_by"):
            apply_label(connection, "checked", "file_seed", seed, by="   ")
        with pytest.raises(ValueError, match="not found"):
            current_labels(connection, "post", 999_999)
