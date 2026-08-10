from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path

import pytest

from media_catalog.cli import build_parser, main
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    ManagedRootRecord,
    MediaOccurrenceRecord,
    OccurrenceSourceRecord,
    PostRecord,
)
from media_catalog.writer import CatalogWriter
from x_likes.database import SCHEMA


def test_parser_accepts_all_planned_commands(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    source = tmp_path / "source.json"
    parser = build_parser()
    cases = (
        ["init", str(catalog)],
        ["schema", str(catalog), "--json"],
        ["doctor", str(catalog)],
        ["stats", str(catalog), "--json"],
        ["search", str(catalog), "artist", "--event", "bookmarked"],
        ["ingest", "x-likes-db", str(source), "--catalog", str(catalog)],
        ["ingest", "xarchive", str(source), "--catalog", str(catalog), "--json"],
        ["discover-links", str(catalog), "--json"],
        ["links", str(catalog), "--platform", "pixiv", "--subject-id", "1"],
        ["matches", str(catalog), "--kind", "post", "--state", "pending"],
        ["match-show", str(catalog), "post:1", "--json"],
        ["match-review", str(catalog), "post:1", "--decision", "reject"],
        [
            "assets",
            "plan",
            str(catalog),
            "--source-root",
            str(tmp_path),
            "--media-root",
            str(tmp_path / "media"),
        ],
        ["assets", "list", str(catalog), "--json"],
        ["assets", "show", str(catalog), "1"],
        ["assets", "verify", str(catalog), "--media-root", str(tmp_path / "media")],
    )
    for argv in cases:
        assert parser.parse_args(argv).command == argv[0]


def test_init_json_uses_only_catalog_basename(tmp_path: Path, capsys: object) -> None:
    path = tmp_path / "private" / "catalog.sqlite3"
    main(["init", str(path), "--json"])
    output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert output["catalog"] == "catalog.sqlite3"
    assert output["status"] == "initialized"
    assert str(tmp_path) not in json.dumps(output)


def test_missing_private_source_path_is_redacted(tmp_path: Path) -> None:
    source = tmp_path / "private" / "missing.json"
    catalog = tmp_path / "catalog.sqlite3"
    with pytest.raises(SystemExit) as raised:
        main(["ingest", "xarchive", str(source), "--catalog", str(catalog)])
    assert source.name in str(raised.value)
    assert str(tmp_path) not in str(raised.value)


def _asset_catalog(catalog: Path, source_root: Path, relative_path: str) -> None:
    with CatalogDatabase(catalog) as database:
        writer = CatalogWriter(database)
        with database.transaction():
            source_id = writer.register_managed_root(
                ManagedRootRecord(
                    "source", "fixture-source", "source", str(source_root.resolve())
                )
            )
            post_id = writer.upsert_post(PostRecord("x", "1", "2026-08-09T00:00:00Z")).id
            occurrence_id = writer.upsert_media(
                post_id,
                MediaOccurrenceRecord(
                    "media:0", 0, "image", observed_at="2026-08-09T00:00:00Z"
                ),
            ).id
            writer.add_occurrence_source(
                OccurrenceSourceRecord(
                    occurrence_id,
                    "legacy_local",
                    relative_path,
                    "2026-08-09T00:00:00Z",
                    source_id,
                )
            )


def test_asset_cli_plan_adopt_query_and_verify_are_offline_and_redacted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    private = tmp_path / "private"
    source_root = private / "source"
    media_root = private / "managed"
    source_root.mkdir(parents=True)
    media_root.mkdir()
    (source_root / "sample.bin").write_bytes(b"same bytes")
    catalog = private / "catalog.sqlite3"
    _asset_catalog(catalog, source_root, "sample.bin")
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network attempted")),
    )

    main(
        [
            "assets",
            "plan",
            str(catalog),
            "--source-root",
            str(source_root),
            "--media-root",
            str(media_root),
            "--json",
        ]
    )
    plan = json.loads(capsys.readouterr().out)
    assert plan["status"] == "planned"
    assert plan["planned_count"] == 1
    assert not (media_root / "sha256").exists()

    main(
        [
            "assets",
            "adopt",
            str(catalog),
            "--source-root",
            str(source_root),
            "--media-root",
            str(media_root),
            "--json",
        ]
    )
    adopted = json.loads(capsys.readouterr().out)
    assert adopted["status"] == "complete"
    assert adopted["outcomes"] == {"adopted_exact_only": 1}

    main(["assets", "list", str(catalog), "--json"])
    listed = json.loads(capsys.readouterr().out)
    assert listed["count"] == 1
    asset_id = listed["results"][0]["asset_id"]
    main(["assets", "show", str(catalog), str(asset_id), "--json"])
    shown = json.loads(capsys.readouterr().out)
    assert shown["asset"]["asset_id"] == asset_id
    assert {item["fingerprint_kind"] for item in shown["fingerprints"]} == {"md5", "sha256"}

    main(
        [
            "assets",
            "verify",
            str(catalog),
            "--media-root",
            str(media_root),
            "--json",
        ]
    )
    verified = json.loads(capsys.readouterr().out)
    assert verified["status"] == "ok"
    assert verified["counts"]["valid"] == 1
    combined = json.dumps((plan, adopted, listed, verified))
    assert str(tmp_path) not in combined


def test_asset_cli_partial_run_has_stable_exit_code(tmp_path: Path, capsys: object) -> None:
    source_root = tmp_path / "private-source"
    media_root = tmp_path / "private-media"
    source_root.mkdir()
    media_root.mkdir()
    catalog = tmp_path / "catalog.sqlite3"
    _asset_catalog(catalog, source_root, "missing.bin")
    with pytest.raises(SystemExit) as raised:
        main(
            [
                "assets",
                "adopt",
                str(catalog),
                "--source-root",
                str(source_root),
                "--media-root",
                str(media_root),
                "--json",
            ]
        )
    assert raised.value.code == 2
    output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert output["status"] == "partial"
    assert output["outcomes"] == {"missing": 1}


def test_corrupt_database_has_bounded_cli_error(tmp_path: Path) -> None:
    catalog = tmp_path / "corrupt.sqlite3"
    catalog.write_bytes(b"not sqlite")
    with pytest.raises(SystemExit, match="error:") as raised:
        main(["schema", str(catalog)])
    assert "Traceback" not in str(raised.value)


def test_both_ingest_commands_run_with_human_and_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    bookmarks = tmp_path / "bookmarks.json"
    bookmarks.write_text(
        json.dumps(
            {
                "export_metadata": {"exported_at": "2026-08-05T00:00:00Z"},
                "bookmarks": [],
            }
        ),
        encoding="utf-8",
    )
    main(["ingest", "xarchive", str(bookmarks), "--catalog", str(catalog), "--json"])
    structured = json.loads(capsys.readouterr().out)
    assert structured["source_kind"] == "xarchive"
    assert structured["status"] == "complete"

    likes = tmp_path / "likes.sqlite3"
    with sqlite3.connect(likes) as connection:
        connection.executescript(SCHEMA)
    main(["ingest", "x-likes-db", str(likes), "--catalog", str(catalog)])
    human = capsys.readouterr().out
    assert "source_kind: x-likes-db" in human
    assert str(tmp_path) not in human


def test_discovery_cli_has_stable_json_and_bounded_candidate_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = tmp_path / "private" / "catalog.sqlite3"
    main(["init", str(catalog), "--json"])
    capsys.readouterr()
    main(["discover-links", str(catalog), "--json"])
    discovered = json.loads(capsys.readouterr().out)
    assert discovered["status"] == "complete"
    assert discovered["versions"]["recognizer"] == "platform-recognizers-v1"
    main(["links", str(catalog), "--state", "unresolved", "--json"])
    assert json.loads(capsys.readouterr().out)["results"] == []
    main(["matches", str(catalog), "--state", "pending", "--json"])
    assert json.loads(capsys.readouterr().out)["results"] == []
    with pytest.raises(SystemExit, match="candidate not found") as raised:
        main(["match-show", str(catalog), "post:999"])
    assert str(tmp_path) not in str(raised.value)
