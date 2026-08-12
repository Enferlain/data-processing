from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path

import pytest

from media_catalog.cli import build_parser, main
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    CandidateLookupRunRecord,
    ManagedRootRecord,
    MediaOccurrenceRecord,
    OccurrenceSourceRecord,
    PostRecord,
    RemoteRunRecord,
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
        ["media", "list", str(catalog), "--author", "pixiv:1001", "--linked", "no"],
        ["media", "show", str(catalog), "1", "--json"],
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
        ["assets", "download-plan", str(catalog), "--select", "1:original"],
        [
            "assets",
            "download",
            str(catalog),
            "--media-root",
            str(tmp_path / "media"),
            "--select",
            "1:original",
        ],
        ["assets", "download-runs", str(catalog), "--json"],
        ["assets", "download-run-show", str(catalog), "1"],
        [
            "assets",
            "download-retry",
            str(catalog),
            "1",
            "--media-root",
            str(tmp_path / "media"),
        ],
        ["metadata", "pixiv-profile", str(catalog), "1001", "--max-requests", "1"],
        ["metadata", "pixiv-artwork", str(catalog), "2001"],
        ["metadata", "pixiv-account-artworks", str(catalog), "1001"],
        ["metadata", "danbooru-post", str(catalog), "3001"],
        ["metadata", "danbooru-artist", str(catalog), "4001"],
        ["metadata", "danbooru-list", str(catalog), "artist_a"],
        ["metadata", "aibooru-post", str(catalog), "3001"],
        ["metadata", "runs", str(catalog), "--json"],
        ["metadata", "run-show", str(catalog), "1"],
        [
            "lookup",
            "plan",
            str(catalog),
            "post:1",
            "--provider",
            "danbooru",
            "--strategy",
            "source_post_url",
        ],
        ["lookup", "runs", str(catalog), "--json"],
        ["lookup", "show", str(catalog), "1"],
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


def test_remote_run_inspection_is_offline_and_structured(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network attempted")),
    )
    main(["metadata", "runs", str(catalog), "--json"])
    output = json.loads(capsys.readouterr().out)
    assert output == {"catalog": "catalog.sqlite3", "count": 0, "results": []}


def test_lookup_plan_and_queries_are_offline_and_redacted(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = tmp_path / "private" / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        post_id = CatalogWriter(database).upsert_post(
            PostRecord(
                "x",
                "12345",
                "2026-08-11T00:00:00Z",
                canonical_url="https://x.com/private_handle/status/12345",
            )
        ).id
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network attempted")),
    )
    main(
        [
            "lookup",
            "plan",
            str(catalog),
            f"post:{post_id}",
            "--provider",
            "danbooru",
            "--strategy",
            "source_post_url",
            "--json",
        ]
    )
    planned = json.loads(capsys.readouterr().out)
    assert planned["status"] == "planned"
    assert planned["count"] == 1
    assert "private_handle" not in json.dumps(planned)
    main(["lookup", "runs", str(catalog), "--json"])
    assert json.loads(capsys.readouterr().out)["results"] == []


def test_lookup_run_listing_succeeds_when_history_contains_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        writer = CatalogWriter(database)
        post_id = writer.upsert_post(
            PostRecord("x", "failure-seed", "2026-08-11T00:00:00Z")
        ).id
        run_id = writer.begin_candidate_lookup(
            CandidateLookupRunRecord(
                "danbooru",
                "",
                "source_post_url",
                "lookup-v1",
                "danbooru-native-v1",
                "danbooru-json-v1",
                "revision",
                "a" * 64,
                "source_post_url",
                "b" * 64,
                "{}",
                1,
                1,
                1,
                30,
                "2026-08-11T00:00:00Z",
                seed_post_id=post_id,
            )
        )
        writer.finish_candidate_lookup(
            run_id,
            status="failed",
            outcome="malformed_response",
            request_count=1,
            page_count=0,
            result_count=0,
            finished_at="2026-08-11T00:00:01Z",
        )
    main(["lookup", "runs", str(catalog), "--json"])
    output = json.loads(capsys.readouterr().out)
    assert output["results"][0]["status"] == "failed"
    main(["lookup", "show", str(catalog), str(run_id), "--json"])
    shown = json.loads(capsys.readouterr().out)
    assert shown["run"]["status"] == "failed"


def test_remote_run_show_of_failed_history_exits_successfully(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database:
        writer = CatalogWriter(database)
        with database.transaction():
            run_id = writer.begin_remote_run(
                RemoteRunRecord(
                    "pixiv",
                    "fetch_post",
                    "10",
                    "fixture-adapter-v1",
                    "fixture-schema-v1",
                    1,
                    1,
                    1,
                    10,
                    "2026-08-10T00:00:00Z",
                )
            )
            writer.finish_remote_run(
                run_id,
                status="failed",
                outcome="malformed_response",
                request_count=1,
                page_count=0,
                record_count=0,
                finished_at="2026-08-10T00:00:01Z",
            )
    main(["metadata", "run-show", str(catalog), str(run_id), "--json"])
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "failed"
    assert output["termination_outcome"] == "malformed_response"


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


def test_download_plan_and_run_queries_are_redacted_and_network_free(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = tmp_path / "private" / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        platform_id = int(
            database.connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'pixiv'"
            ).fetchone()[0]
        )
        post_id = int(
            database.connection.execute(
                """INSERT INTO posts (
                       platform_id, native_post_id, first_seen_at, last_seen_at
                   ) VALUES (?, 'download-cli', '2026-08-10T00:00:00Z',
                             '2026-08-10T00:00:00Z')""",
                (platform_id,),
            ).lastrowid
        )
        database.connection.execute(
            """INSERT INTO media_occurrences (
                   post_id, source_key, media_index, media_type, remote_url,
                   availability, observed_at
               ) VALUES (?, 'download:p0', 0, 'image/png', ?, 'available',
                         '2026-08-10T00:00:00Z')""",
            (post_id, "https://i.pximg.net/file.png?signature=private-value"),
        )

    main(
        [
            "assets",
            "download-plan",
            str(catalog),
            "--select",
            "1:primary",
            "--json",
        ]
    )
    planned = json.loads(capsys.readouterr().out)
    rendered = json.dumps(planned)
    assert planned["status"] == "planned"
    assert planned["counts"]["eligible"] == 1
    assert "private-value" not in rendered
    assert "pximg.net" not in rendered
    assert str(tmp_path) not in rendered

    main(["assets", "download-runs", str(catalog), "--json"])
    runs = json.loads(capsys.readouterr().out)
    assert runs["results"] == []

    with CatalogDatabase(catalog) as database, database.transaction():
        managed_root_id = int(
            database.connection.execute(
                """INSERT INTO managed_roots (
                       root_kind, root_identity, display_label, private_path, created_at
                   ) VALUES ('managed', 'cli:failed', 'managed', '/private/media',
                             '2026-08-10T00:00:00Z')"""
            ).lastrowid
        )
        plan_id = int(
            database.connection.execute(
                """INSERT INTO media_acquisition_plans (
                       plan_version, selection_digest, requested_count, eligible_count,
                       satisfied_count, excluded_count, created_at
                   ) VALUES ('plan-v1', ?, 1, 1, 0, 0, '2026-08-10T00:00:00Z')""",
                ("a" * 64,),
            ).lastrowid
        )
        database.connection.execute(
            """INSERT INTO media_acquisition_runs (
                   acquisition_plan_id, managed_root_id, status, termination_outcome,
                   max_items, max_item_bytes, max_total_bytes, max_attempts_per_item,
                   max_seconds, max_redirects, max_quarantine_bytes, concurrency,
                   planned_count, failed_count, started_at, finished_at
               ) VALUES (?, ?, 'failed', 'failed', 1, 1000, 1000, 1, 30, 1, 1000,
                         1, 1, 1, '2026-08-10T00:00:00Z',
                         '2026-08-10T00:00:01Z')""",
            (plan_id, managed_root_id),
        )

    main(["assets", "download-run-show", str(catalog), "1", "--json"])
    shown = json.loads(capsys.readouterr().out)
    assert shown["status"] == "failed"


def test_media_browser_is_offline_redacted_and_feeds_download_planning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = tmp_path / "private" / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        platform_id = int(
            database.connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'pixiv'"
            ).fetchone()[0]
        )
        post_id = int(
            database.connection.execute(
                """INSERT INTO posts (
                       platform_id, native_post_id, availability, first_seen_at, last_seen_at
                   ) VALUES (?, 'browser-post', 'available',
                             '2026-08-11T00:00:00Z', '2026-08-11T00:00:00Z')""",
                (platform_id,),
            ).lastrowid
        )
        database.connection.execute(
            """INSERT INTO media_occurrences (
                   media_occurrence_id, post_id, source_key, media_index, media_type,
                   remote_url, variants_json, availability, observed_at
               ) VALUES (42, ?, 'browser:p0', 0, 'image/png', ?, ?, 'available',
                         '2026-08-11T00:00:00Z')""",
            (
                post_id,
                "https://i.pximg.net/private.png?token=PRIVATE_MEDIA_TOKEN",
                json.dumps(
                    {
                        "variants": [
                            {
                                "role": "original",
                                "url": (
                                    "https://i.pximg.net/private.png?token=PRIVATE_MEDIA_TOKEN"
                                ),
                            }
                        ]
                    }
                ),
            ),
        )
    before_bytes = catalog.read_bytes()
    before_names = sorted(path.name for path in catalog.parent.iterdir())
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network attempted")),
    )

    main(["media", "list", str(catalog), "--platform", "pixiv", "--json"])
    listed = json.loads(capsys.readouterr().out)
    selection = next(
        variant["selection"]
        for variant in listed["results"][0]["variants"]
        if variant["key"] == "original"
    )
    assert selection == "42:original"

    main(["media", "show", str(catalog), "42", "--json"])
    shown = json.loads(capsys.readouterr().out)
    assert shown["occurrence"]["media_occurrence_id"] == 42

    main(
        [
            "assets",
            "download-plan",
            str(catalog),
            "--select",
            selection,
            "--json",
        ]
    )
    planned = json.loads(capsys.readouterr().out)
    assert planned["items"][0]["eligibility"] == "eligible"

    rendered = json.dumps((listed, shown, planned))
    assert "PRIVATE_MEDIA_TOKEN" not in rendered
    assert "i.pximg.net" not in rendered
    assert str(tmp_path) not in rendered
    assert catalog.read_bytes() == before_bytes
    assert sorted(path.name for path in catalog.parent.iterdir()) == before_names

    with pytest.raises(SystemExit, match="media occurrence not found") as raised:
        main(["media", "show", str(catalog), "999"])
    assert str(tmp_path) not in str(raised.value)
