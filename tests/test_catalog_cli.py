from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path

import pytest

import media_catalog.cli as cli_module
from media_catalog.adapters import AdapterOperation
from media_catalog.candidate_lookup import LookupExecutionResult, LookupLimits
from media_catalog.cli import build_parser, main
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    AccountRecord,
    AttributionRecord,
    CandidateLookupRunRecord,
    ManagedRootRecord,
    MediaOccurrenceRecord,
    OccurrenceSourceRecord,
    PostRecord,
    RemoteRunRecord,
    TagObservationRecord,
)
from media_catalog.remote_sync import SyncResult
from media_catalog.writer import CatalogWriter
from x_likes.database import SCHEMA

NOW = "2026-08-12T20:00:00Z"


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
        ["metadata", "e621-post", str(catalog), "5001"],
        ["metadata", "e621-artist", str(catalog), "7001"],
        ["metadata", "e621-tag", str(catalog), "artist_tag"],
        ["metadata", "e621-alias", str(catalog), "old_artist_tag"],
        ["metadata", "e621-list", str(catalog), "artist_tag"],
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
        ["library", "plan", str(catalog), "account:1", "--json"],
        ["library", "probe", str(catalog), "account:1", "--json"],
        ["library", "run", str(catalog), "account:1"],
        ["library", "resume", str(catalog), "1"],
        ["library", "runs", str(catalog), "--json"],
        ["library", "show", str(catalog), "1"],
    )
    for argv in cases:
        assert parser.parse_args(argv).command == argv[0]


@pytest.mark.parametrize(
    ("command", "target", "operation"),
    [
        ("e621-post", "5001", AdapterOperation.FETCH_POST),
        ("e621-artist", "7001", AdapterOperation.FETCH_ATTRIBUTION),
        ("e621-tag", "artist_tag", AdapterOperation.FETCH_TAG),
        ("e621-alias", "old_artist_tag", AdapterOperation.FETCH_TAG_ALIAS),
        ("e621-list", "artist_tag", AdapterOperation.LIST_ACCOUNT_POSTS),
    ],
)
def test_e621_metadata_cli_routes_operations_with_provider_limits_and_resume(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    target: str,
    operation: AdapterOperation,
) -> None:
    catalog = tmp_path / "private" / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass

    adapter_calls: list[tuple[object, object, object]] = []
    service_calls: list[tuple[object, str, object, int | None]] = []
    service_intervals: list[float] = []

    class FakeAdapter:
        adapter_version = "e621-native-v1"
        schema_version = "e621-json-v1"
        instance_key = "e621"

        def __init__(self, instance: object, *, client: object, credentials: object) -> None:
            adapter_calls.append((instance, client, credentials))

    class FakeService:
        def __init__(
            self,
            _database: CatalogDatabase,
            _adapter: FakeAdapter,
            *,
            minimum_interval_seconds: float,
        ) -> None:
            assert _adapter is not None
            service_intervals.append(minimum_interval_seconds)
            self.minimum_interval_seconds = minimum_interval_seconds

        def synchronize(
            self,
            actual_operation: AdapterOperation,
            actual_target: str,
            *,
            limits: object,
            resume_from_run_id: int | None,
        ) -> SyncResult:
            service_calls.append((actual_operation, actual_target, limits, resume_from_run_id))
            return SyncResult(
                remote_run_id=41,
                platform="e621",
                operation=actual_operation.value,
                target=actual_target,
                status="complete",
                outcome="success",
                request_count=1,
                page_count=1,
                record_count=1,
                resumed_from_run_id=resume_from_run_id,
            )

    monkeypatch.setattr(cli_module, "E621Adapter", FakeAdapter)
    monkeypatch.setattr(cli_module, "MetadataSyncService", FakeService)
    monkeypatch.delenv("E621_USERNAME", raising=False)
    monkeypatch.delenv("E621_API_KEY", raising=False)

    main(
        [
            "metadata",
            command,
            str(catalog),
            target,
            "--max-requests",
            "7",
            "--max-pages",
            "8",
            "--max-records",
            "9",
            "--max-seconds",
            "11",
            "--resume-from",
            "13",
            "--json",
        ]
    )
    rendered = capsys.readouterr().out
    output = json.loads(rendered)
    assert output == {
        "catalog": "catalog.sqlite3",
        "operation": operation.value,
        "outcome": "success",
        "page_count": 1,
        "platform": "e621",
        "record_count": 1,
        "remote_run_id": 41,
        "request_count": 1,
        "resumed_from_run_id": 13,
        "status": "complete",
        "target": target,
        "budget_boundary": None,
        "retry_after": None,
        "diagnostic": None,
    }
    assert len(adapter_calls) == 1
    assert adapter_calls[0][0] is cli_module.E621
    assert adapter_calls[0][2] is None
    assert service_intervals == [cli_module.E621.minimum_interval_seconds]
    assert len(service_calls) == 1
    actual_operation, actual_target, limits, resumed_from = service_calls[0]
    assert actual_operation is operation
    assert actual_target == target
    assert (limits.requests, limits.pages, limits.records, limits.elapsed_seconds) == (7, 8, 9, 11)
    assert resumed_from == 13


@pytest.mark.parametrize("as_json", [False, True])
def test_e621_partial_credentials_fail_with_safe_guidance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    as_json: bool,
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass
    sentinel = "e621-secret-value"
    monkeypatch.setenv("E621_USERNAME", sentinel)
    monkeypatch.delenv("E621_API_KEY", raising=False)

    argv = ["metadata", "e621-post", str(catalog), "5001"]
    if as_json:
        argv.append("--json")
    with pytest.raises(SystemExit) as raised:
        main(argv)
    message = str(raised.value)
    assert sentinel not in message
    assert "E621_USERNAME" in message
    assert "E621_API_KEY" in message
    if as_json:
        payload = json.loads(message)
        assert sentinel not in json.dumps(payload)
        assert "error" in payload
    else:
        assert "configure both" in message
    assert capsys.readouterr().out == ""


def test_e621_metadata_cli_human_output_and_help_keep_credentials_external(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass

    class FakeAdapter:
        adapter_version = "e621-native-v1"
        schema_version = "e621-json-v1"
        instance_key = "e621"

        def __init__(self, _instance: object, *, client: object, credentials: object) -> None:
            assert client is not None
            assert credentials.username == "external-user"
            assert credentials.api_key == "sentinel-secret"

    class FakeService:
        def __init__(self, _database: CatalogDatabase, _adapter: FakeAdapter, **_kwargs) -> None:
            pass

        def synchronize(self, operation, target, *, limits, resume_from_run_id):
            return SyncResult(
                42,
                "e621",
                operation.value,
                target,
                "complete",
                "success",
                1,
                1,
                1,
            )

    monkeypatch.setattr(cli_module, "E621Adapter", FakeAdapter)
    monkeypatch.setattr(cli_module, "MetadataSyncService", FakeService)
    monkeypatch.setenv("E621_USERNAME", "external-user")
    monkeypatch.setenv("E621_API_KEY", "sentinel-secret")
    main(["metadata", "e621-post", str(catalog), "5001"])
    human = capsys.readouterr().out
    assert "catalog: catalog.sqlite3" in human
    assert "platform: e621" in human
    assert "operation: fetch_post" in human
    assert str(tmp_path) not in human
    assert "external-user" not in human
    assert "sentinel-secret" not in human

    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(["metadata", "e621-post", "--help"])
    assert raised.value.code == 0
    help_text = capsys.readouterr().out
    assert "E621_USERNAME" in help_text
    assert "E621_API_KEY" in help_text
    assert "never CLI flags" in help_text

    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(["metadata", "--help"])
    assert raised.value.code == 0
    assert "E621_USERNAME" in capsys.readouterr().out


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
                ManagedRootRecord("source", "fixture-source", "source", str(source_root.resolve()))
            )
            post_id = writer.upsert_post(PostRecord("x", "1", "2026-08-09T00:00:00Z")).id
            occurrence_id = writer.upsert_media(
                post_id,
                MediaOccurrenceRecord("media:0", 0, "image", observed_at="2026-08-09T00:00:00Z"),
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
        post_id = (
            CatalogWriter(database)
            .upsert_post(
                PostRecord(
                    "x",
                    "12345",
                    "2026-08-11T00:00:00Z",
                    canonical_url="https://x.com/private_handle/status/12345",
                )
            )
            .id
        )
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


def test_lookup_parser_accepts_e621_provider(tmp_path: Path) -> None:
    parser = build_parser()
    catalog = str(tmp_path / "catalog.sqlite3")
    plan = parser.parse_args(
        [
            "lookup",
            "plan",
            catalog,
            "post:1",
            "--provider",
            "e621",
            "--strategy",
            "source_post_url",
        ]
    )
    assert plan.provider == "e621"
    run = parser.parse_args(
        [
            "lookup",
            "run",
            catalog,
            "post:1",
            "--provider",
            "e621",
            "--strategy",
            "source_post_url",
        ]
    )
    assert run.provider == "e621"
    resume = parser.parse_args(["lookup", "resume", catalog, "7", "--provider", "e621"])
    assert resume.provider == "e621"


def test_e621_lookup_plan_uses_e621_identity_and_capability_exclusions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network attempted")),
    )
    catalog = tmp_path / "private" / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        post_id = (
            CatalogWriter(database)
            .upsert_post(
                PostRecord(
                    "x",
                    "12345",
                    NOW,
                    canonical_url="https://x.com/acme/status/12345",
                )
            )
            .id
        )

    main(
        [
            "lookup",
            "plan",
            str(catalog),
            f"post:{post_id}",
            "--provider",
            "e621",
            "--strategy",
            "artist_text",
            "--json",
        ]
    )
    excluded = json.loads(capsys.readouterr().out)
    assert excluded["provider"] == "e621"
    assert excluded["count"] == 0
    assert excluded["network_requested"] is False
    assert excluded["exclusions"] == [
        {"strategy": "artist_text", "reason": "unsupported_provider_capability"}
    ]

    main(
        [
            "lookup",
            "plan",
            str(catalog),
            f"post:{post_id}",
            "--provider",
            "e621",
            "--strategy",
            "source_post_url",
            "--json",
        ]
    )
    planned = json.loads(capsys.readouterr().out)
    assert planned["provider"] == "e621"
    assert planned["count"] == 1
    item = planned["items"][0]
    assert item["provider"] == "e621"
    assert item["instance"] == "e621"
    assert item["strategy"] == "source_post_url"
    assert item["adapter_version"] == "e621-native-v1"
    assert item["schema_version"] == "e621-json-v1"
    assert "acme" not in json.dumps(planned)


@pytest.mark.parametrize("lookup_command", ["run", "resume"])
def test_e621_lookup_run_and_resume_route_through_adapter_with_provider_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lookup_command: str,
) -> None:
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network attempted")),
    )
    catalog = tmp_path / "private" / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        post_id = (
            CatalogWriter(database)
            .upsert_post(PostRecord("x", "1", NOW, canonical_url="https://x.com/acme/status/1"))
            .id
        )

    adapter_calls: list[tuple[object, object, object]] = []
    service_intervals: list[float] = []
    plan_limits: list[LookupLimits] = []
    resume_calls: list[tuple[int, LookupLimits]] = []

    class FakeAdapter:
        def __init__(self, instance: object, *, client: object, credentials: object) -> None:
            adapter_calls.append((instance, client, credentials))

    class FakeService:
        def __init__(
            self,
            _database: CatalogDatabase,
            _adapter: FakeAdapter,
            *,
            minimum_interval_seconds: float,
        ) -> None:
            service_intervals.append(minimum_interval_seconds)

        def plan(self, seed, strategies, *, limits, search_term=None):
            plan_limits.append(limits)
            return "plan-token"

        def execute(self, _plan):
            return (
                LookupExecutionResult(
                    1,
                    "e621",
                    "source_post_url",
                    f"post:{post_id}",
                    "complete",
                    "success",
                    0,
                    0,
                    0,
                ),
            )

        def resume(self, run_id, *, limits):
            resume_calls.append((run_id, limits))
            return LookupExecutionResult(
                1,
                "e621",
                "source_post_url",
                f"post:{post_id}",
                "complete",
                "success",
                0,
                0,
                0,
            )

    monkeypatch.setattr(cli_module, "E621Adapter", FakeAdapter)
    monkeypatch.setattr(cli_module, "CandidateLookupService", FakeService)
    monkeypatch.delenv("E621_USERNAME", raising=False)
    monkeypatch.delenv("E621_API_KEY", raising=False)

    argv = ["lookup", lookup_command, str(catalog)]
    if lookup_command == "run":
        argv += [f"post:{post_id}", "--provider", "e621", "--strategy", "source_post_url"]
    else:
        argv += ["9", "--provider", "e621"]
    argv += ["--max-results", "5", "--json"]
    main(argv)

    assert len(adapter_calls) == 1
    assert adapter_calls[0][0] is cli_module.E621
    assert adapter_calls[0][1] is not None
    assert adapter_calls[0][2] is None
    assert service_intervals == [cli_module.E621.minimum_interval_seconds]
    forwarded = LookupLimits(3, 3, 5, 60)
    if lookup_command == "run":
        assert plan_limits == [forwarded]
        assert resume_calls == []
    else:
        assert resume_calls == [(9, forwarded)]
        assert plan_limits == []


@pytest.mark.parametrize("as_json", [False, True])
def test_e621_lookup_partial_credentials_fail_with_safe_guidance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    as_json: bool,
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass
    sentinel = "e621-secret-value"
    monkeypatch.setenv("E621_USERNAME", sentinel)
    monkeypatch.delenv("E621_API_KEY", raising=False)

    argv = [
        "lookup",
        "run",
        str(catalog),
        "post:1",
        "--provider",
        "e621",
        "--strategy",
        "source_post_url",
    ]
    if as_json:
        argv.append("--json")
    with pytest.raises(SystemExit) as raised:
        main(argv)
    message = str(raised.value)
    assert sentinel not in message
    assert "E621_USERNAME" in message
    assert "E621_API_KEY" in message
    assert "configure both" in message
    if as_json:
        payload = json.loads(message)
        assert sentinel not in json.dumps(payload)
        assert "error" in payload
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "provider, instance",
    [("danbooru", cli_module.DANBOORU), ("aibooru", cli_module.AIBOORU)],
)
def test_danbooru_family_lookup_routing_is_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    instance: object,
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass
    adapter_calls: list[tuple[object, object, object]] = []
    service_intervals: list[float] = []

    class FakeAdapter:
        def __init__(self, inst: object, *, client: object, credentials: object) -> None:
            adapter_calls.append((inst, client, credentials))

    class FakeService:
        def __init__(
            self,
            _database: CatalogDatabase,
            _adapter: FakeAdapter,
            *,
            minimum_interval_seconds: float,
        ) -> None:
            service_intervals.append(minimum_interval_seconds)

        def plan(self, seed, strategies, *, limits, search_term=None):
            return "plan-token"

        def execute(self, _plan):
            return ()

    monkeypatch.setattr(cli_module, "DanbooruAdapter", FakeAdapter)
    monkeypatch.setattr(cli_module, "CandidateLookupService", FakeService)
    monkeypatch.delenv(instance.login_env, raising=False)
    monkeypatch.delenv(instance.api_key_env, raising=False)
    main(
        [
            "lookup",
            "run",
            str(catalog),
            "post:1",
            "--provider",
            provider,
            "--strategy",
            "source_post_url",
            "--json",
        ]
    )
    assert len(adapter_calls) == 1
    assert adapter_calls[0][0] is instance
    assert service_intervals == [instance.minimum_interval_seconds]


def test_lookup_run_listing_succeeds_when_history_contains_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        writer = CatalogWriter(database)
        post_id = writer.upsert_post(PostRecord("x", "failure-seed", "2026-08-11T00:00:00Z")).id
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


def test_library_plan_cli_is_read_only_and_unsupported_probe_makes_no_request(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = tmp_path / "private" / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        writer = CatalogWriter(database)
        pixiv_id = writer.upsert_account(AccountRecord("pixiv", "1001", NOW)).id
        x_id = writer.upsert_account(AccountRecord("x", "9001", NOW)).id
        attribution_id = writer.upsert_attribution(
            AttributionRecord(
                "danbooru",
                "44",
                "danbooru-adapter-v1",
                NOW,
                primary_name="artist_a",
            )
        ).id
    before_bytes = catalog.read_bytes()
    before_names = sorted(path.name for path in catalog.parent.iterdir())
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network attempted")),
    )

    main(["library", "plan", str(catalog), f"account:{pixiv_id}", "--json"])
    planned = json.loads(capsys.readouterr().out)
    assert planned["status"] == "planned"
    assert planned["executable"] is True
    assert planned["network_requested"] is False
    assert catalog.read_bytes() == before_bytes
    assert sorted(path.name for path in catalog.parent.iterdir()) == before_names

    main(
        [
            "library",
            "probe",
            str(catalog),
            f"account:{x_id}",
            "--target",
            f"attribution:{attribution_id}",
            "--selection-note",
            "selected provider attribution",
            "--json",
        ]
    )
    probed = json.loads(capsys.readouterr().out)
    assert probed["outcome"] == "unsupported"
    assert probed["request_count"] == 0


def _seed_e621_library_target(catalog: Path) -> tuple[int, int]:
    with CatalogDatabase(catalog) as database, database.transaction():
        writer = CatalogWriter(database)
        seed_id = writer.upsert_account(AccountRecord("x", "9001", NOW)).id
        attribution_id = writer.upsert_attribution(
            AttributionRecord(
                "e621",
                "tag:12345",
                "e621-native-v1",
                NOW,
                instance_host="e621.net",
            )
        ).id
        writer.upsert_tag_record(
            TagObservationRecord(
                "e621",
                "artist",
                "canonical_artist_tag",
                "canonical_artist_tag",
                NOW,
                "provider-tag-v1",
                provider_tag_id="12345",
                native_category="artist",
                native_category_code=1,
            )
        )
    return seed_id, attribution_id


def test_e621_library_parser_accepts_stable_attribution_target_and_resume(
    tmp_path: Path,
) -> None:
    catalog = str(tmp_path / "catalog.sqlite3")
    parser = build_parser()
    run = parser.parse_args(
        [
            "library",
            "run",
            catalog,
            "account:1",
            "--target",
            "attribution:2",
            "--max-requests",
            "4",
        ]
    )
    assert run.library_command == "run"
    assert run.target == "attribution:2"
    assert run.max_requests == 4
    resume = parser.parse_args(["library", "resume", catalog, "9", "--json"])
    assert resume.library_command == "resume"
    assert resume.execution_id == 9


@pytest.mark.parametrize("library_command", ["run", "resume"])
@pytest.mark.parametrize("as_json", [False, True])
def test_e621_library_cli_routes_with_provider_floor_and_private_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    library_command: str,
    as_json: bool,
) -> None:
    catalog = tmp_path / "private" / "catalog.sqlite3"
    seed_id, attribution_id = _seed_e621_library_target(catalog)
    target_reference = f"attribution:{attribution_id}"
    selected_plan = cli_module.plan_library_expansion(
        catalog,
        f"account:{seed_id}",
        target=target_reference,
        selection_note="operator selected the e621 artist tag",
    )
    if library_command == "resume":
        monkeypatch.setattr(
            cli_module,
            "replan_library_execution",
            lambda _database, _execution_id: selected_plan,
        )

    adapter_calls: list[tuple[object, object]] = []
    service_calls: list[tuple[str, object, int | None]] = []
    service_intervals: list[float] = []

    class FakeAdapter:
        instance_key = "e621"
        adapter_version = "e621-native-v1"
        schema_version = "e621-json-v1"

        def __init__(self, instance: object, *, client: object, credentials: object) -> None:
            adapter_calls.append((instance, credentials))
            assert client is not None

    class FakeResult:
        def as_dict(self) -> dict[str, object]:
            return {
                "library_expansion_plan_id": 21,
                "library_expansion_execution_id": 22,
                "target": target_reference,
                "status": "complete",
                "outcome": "success",
                "request_count": 1,
                "page_count": 1,
                "record_count": 1,
            }

    class FakeService:
        def __init__(
            self,
            _database: CatalogDatabase,
            _adapter: FakeAdapter,
            *,
            minimum_interval_seconds: float,
        ) -> None:
            service_intervals.append(minimum_interval_seconds)

        def run(self, plan: object) -> FakeResult:
            service_calls.append(("run", plan, None))
            return FakeResult()

        def resume(self, plan: object, execution_id: int) -> FakeResult:
            service_calls.append(("resume", plan, execution_id))
            return FakeResult()

    monkeypatch.setattr(cli_module, "E621Adapter", FakeAdapter)
    monkeypatch.setattr(cli_module, "ArtistLibraryExpansionService", FakeService)
    monkeypatch.setenv("E621_USERNAME", "external-user")
    monkeypatch.setenv("E621_API_KEY", "external-secret")

    argv = ["library", library_command, str(catalog)]
    if library_command == "run":
        argv += [
            f"account:{seed_id}",
            "--target",
            target_reference,
            "--selection-note",
            "operator selected the e621 artist tag",
            "--max-requests",
            "7",
            "--max-pages",
            "8",
            "--max-records",
            "9",
            "--max-seconds",
            "11",
        ]
    else:
        argv += ["77"]
    if as_json:
        argv += ["--json"]
    main(argv)

    rendered = capsys.readouterr().out
    if as_json:
        output = json.loads(rendered)
        assert output["catalog"] == "catalog.sqlite3"
        assert output["target"] == target_reference
        assert output["status"] == "complete"
    else:
        assert "catalog: catalog.sqlite3" in rendered
        assert f"target: {target_reference}" in rendered
        assert "status: complete" in rendered
    assert "canonical_artist_tag" not in rendered
    assert "external-user" not in rendered
    assert "external-secret" not in rendered
    assert adapter_calls[0][0] is cli_module.E621
    credentials = adapter_calls[0][1]
    assert credentials.username == "external-user"
    assert credentials.api_key == "external-secret"
    assert service_intervals == [cli_module.E621.minimum_interval_seconds]
    assert len(service_calls) == 1
    called, plan, execution_id = service_calls[0]
    assert called == library_command
    assert plan.selected is not None
    assert plan.selected.target.native_id == "tag:12345"
    if library_command == "run":
        assert (
            plan.limits.requests,
            plan.limits.pages,
            plan.limits.records,
            plan.limits.seconds,
        ) == (
            7,
            8,
            9,
            11,
        )
        assert execution_id is None
    else:
        assert execution_id == 77


@pytest.mark.parametrize("as_json", [False, True])
def test_e621_library_partial_credentials_fail_without_secret_leak(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    as_json: bool,
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    seed_id, attribution_id = _seed_e621_library_target(catalog)
    sentinel = "e621-library-secret"
    monkeypatch.setenv("E621_USERNAME", "external-user")
    monkeypatch.setenv("E621_API_KEY", sentinel)
    # Force credentials to be incomplete after parser/plan work, before any client request.
    monkeypatch.delenv("E621_USERNAME", raising=False)

    argv = [
        "library",
        "run",
        str(catalog),
        f"account:{seed_id}",
        "--target",
        f"attribution:{attribution_id}",
        "--selection-note",
        "operator selected the e621 artist tag",
    ]
    if as_json:
        argv.append("--json")
    with pytest.raises(SystemExit) as raised:
        main(argv)
    message = str(raised.value)
    assert sentinel not in message
    assert "E621_USERNAME" in message
    assert "E621_API_KEY" in message
    assert "configure both" in message
    if as_json:
        payload = json.loads(message)
        assert sentinel not in json.dumps(payload)
        assert "error" in payload
    assert capsys.readouterr().out == ""
