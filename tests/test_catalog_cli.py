from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from media_catalog.cli import build_parser, main
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
