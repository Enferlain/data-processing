"""Reprocessing contract tests (OpenSpec add-reprocessing-contract).

Retained raw observations replay offline through the current normalizer:
planning is read-only, replay never mutates the retained payload, facts land
as observations under the current-projection policy, replaying the same raw
under the same versions is idempotent, and malformed retained payloads fail
retentively.
"""

from __future__ import annotations

import json
import socket
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import AdapterOperation, load_fixture_suite
from media_catalog.adapters.danbooru import DANBOORU, DanbooruAdapter, DanbooruCredentials
from media_catalog.adapters.danbooru.config import ADAPTER_VERSION
from media_catalog.database import CatalogDatabase
from media_catalog.remote_sync import (
    MetadataSyncService,
    SyncLimits,
    execute_reprocess,
    plan_reprocess,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
NOW = "2026-10-07T00:00:00Z"
OLD_VERSION = "danbooru-native-v1"
CREDENTIALS = DanbooruCredentials("test-login", "0" * 32)


def _fixture_payload() -> bytes:
    suite = load_fixture_suite(FIXTURES / "danbooru.json")
    case = next(case for case in suite.cases if case.name == "post_with_attribution")
    return case.response.payload


def _old_adapter(handler, *, clock=None) -> DanbooruAdapter:
    class _OldDanbooruAdapter(DanbooruAdapter):
        adapter_version = OLD_VERSION

    return _OldDanbooruAdapter(
        DANBOORU,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock or (lambda: NOW),
    )


def _replay_adapter() -> DanbooruAdapter:
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("reprocessing must not contact the provider")

    return DanbooruAdapter(DANBOORU, client=httpx.Client(transport=httpx.MockTransport(refuse)))


def _sync_retained_raw(database: CatalogDatabase, *, payload: bytes | None = None) -> int:
    body = payload if payload is not None else _fixture_payload()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    MetadataSyncService(
        database,
        _old_adapter(handler),
        minimum_interval_seconds=0,
        maximum_retries=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
        clock=lambda: NOW,
    ).synchronize(AdapterOperation.FETCH_POST, "3001", limits=SyncLimits(1, 1, 50, 10))
    row = database.connection.execute(
        "SELECT raw_observation_id FROM raw_observations ORDER BY raw_observation_id DESC"
    ).fetchone()
    return int(row[0])


def test_plan_reports_stale_raws_without_writing(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        raw_id = _sync_retained_raw(database)
        runs_before = database.connection.execute("SELECT COUNT(*) FROM remote_runs").fetchone()[0]
        plan = plan_reprocess(database, adapter=_replay_adapter())
        assert plan["provider"] == "danbooru"
        assert plan["adapter_version"] == ADAPTER_VERSION
        assert plan["count"] == 1
        candidate = plan["results"][0]
        assert candidate["raw_observation_id"] == raw_id
        assert candidate["operation"] == "fetch_post"
        assert candidate["target"] == "3001"
        assert candidate["raw_adapter_version"] == OLD_VERSION
        assert candidate["already_reprocessed"] is False
        assert (
            database.connection.execute("SELECT COUNT(*) FROM remote_runs").fetchone()[0]
            == runs_before
        )


def test_replay_materializes_facts_offline_and_never_touches_raw(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        raw_id = _sync_retained_raw(database)
        payload_before = database.connection.execute(
            "SELECT sha256 FROM raw_payloads rp JOIN raw_observations ro "
            "ON ro.raw_payload_id = rp.raw_payload_id WHERE ro.raw_observation_id = ?",
            (raw_id,),
        ).fetchone()[0]
        facts_before = database.connection.execute(
            "SELECT COUNT(*) FROM post_metadata_observations"
        ).fetchone()[0]

        def fail_connect(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("network access attempted")

        socket_default = socket.socket.connect
        socket.socket.connect = fail_connect
        try:
            result = execute_reprocess(
                database, _replay_adapter(), raw_observation_ids=[raw_id], clock=lambda: NOW
            )
        finally:
            socket.socket.connect = socket_default

        assert result["counts"] == {"complete": 1}
        item = result["results"][0]
        assert item["status"] == "complete"
        assert item["record_count"] > 0
        run = database.connection.execute(
            """SELECT origin_kind, origin_reference, request_count, status, adapter_version
                 FROM remote_runs WHERE remote_run_id = ?""",
            (item["remote_run_id"],),
        ).fetchone()
        assert run["origin_kind"] == "reprocess"
        # The reference is the deterministic replay digest (raw id +
        # adapter/schema versions); stability is proven by idempotency.
        assert len(run["origin_reference"]) == 64
        assert all(character in "0123456789abcdef" for character in run["origin_reference"])
        assert run["request_count"] == 0
        assert run["adapter_version"] == ADAPTER_VERSION
        # The retained payload is byte-identical and identical facts do not
        # duplicate (observation digest dedup).
        payload_after = database.connection.execute(
            "SELECT sha256 FROM raw_payloads rp JOIN raw_observations ro "
            "ON ro.raw_payload_id = rp.raw_payload_id WHERE ro.raw_observation_id = ?",
            (raw_id,),
        ).fetchone()[0]
        assert payload_after == payload_before
        facts_after = database.connection.execute(
            "SELECT COUNT(*) FROM post_metadata_observations"
        ).fetchone()[0]
        assert facts_after == facts_before == 1


def test_replay_is_idempotent_per_versions(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        raw_id = _sync_retained_raw(database)
        service_result = execute_reprocess(
            database, _replay_adapter(), raw_observation_ids=[raw_id], clock=lambda: NOW
        )
        assert service_result["counts"] == {"complete": 1}
        runs_after_first = database.connection.execute(
            "SELECT COUNT(*) FROM remote_runs"
        ).fetchone()[0]

        again = execute_reprocess(
            database, _replay_adapter(), raw_observation_ids=[raw_id], clock=lambda: NOW
        )
        assert again["counts"] == {"skipped": 1}
        assert again["results"][0]["outcome"] == "already_reprocessed"
        assert (
            database.connection.execute("SELECT COUNT(*) FROM remote_runs").fetchone()[0]
            == runs_after_first
        )
        plan = plan_reprocess(database, adapter=_replay_adapter())
        assert plan["results"][0]["already_reprocessed"] is True


def test_malformed_retained_payload_fails_retentively(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        raw_id = _sync_retained_raw(database, payload=b"{private malformed")
        result = execute_reprocess(
            database, _replay_adapter(), raw_observation_ids=[raw_id], clock=lambda: NOW
        )
        assert result["counts"] == {"failed": 1}
        item = result["results"][0]
        assert item["outcome"] == "malformed_response"
        assert item["diagnostic"]
        run = database.connection.execute(
            "SELECT status, termination_outcome FROM remote_runs WHERE remote_run_id = ?",
            (item["remote_run_id"],),
        ).fetchone()
        assert tuple(run) == ("failed", "malformed_response")
        # The malformed payload remains inspectable for a later parser version.
        retained = database.connection.execute(
            "SELECT payload FROM raw_payloads rp JOIN raw_observations ro "
            "ON ro.raw_payload_id = rp.raw_payload_id WHERE ro.raw_observation_id = ?",
            (raw_id,),
        ).fetchone()[0]
        assert bytes(retained) == b"{private malformed"
        # A retry after the failure runs again (no complete run to skip).
        retry = execute_reprocess(
            database, _replay_adapter(), raw_observation_ids=[raw_id], clock=lambda: NOW
        )
        assert retry["counts"] == {"failed": 1}


def test_reprocess_cli_is_offline(tmp_path: Path, capsys, monkeypatch) -> None:
    from media_catalog.cli import main

    monkeypatch.chdir(tmp_path)
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database:
        raw_id = _sync_retained_raw(database)

    def fail_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted")

    socket_default = socket.socket.connect
    socket.socket.connect = fail_connect
    try:
        main(["reprocess", "plan", str(catalog), "--provider", "danbooru", "--json"])
        planned = json.loads(capsys.readouterr().out)
        assert planned["count"] == 1
        assert planned["results"][0]["raw_observation_id"] == raw_id
        main(
            [
                "reprocess",
                "run",
                str(catalog),
                "--provider",
                "danbooru",
                "--raw-id",
                str(raw_id),
                "--json",
            ]
        )
        executed = json.loads(capsys.readouterr().out)
        assert executed["counts"] == {"complete": 1}
    finally:
        socket.socket.connect = socket_default


def test_fixture_manifests_pin_live_adapter_versions() -> None:
    from media_catalog.adapters.e621 import ADAPTER_VERSION as E621_VERSION
    from media_catalog.adapters.gelbooru import ADAPTER_VERSION as GELBOORU_VERSION
    from media_catalog.adapters.pixiv import PIXIV_ADAPTER_VERSION

    expected = {
        "danbooru.json": ADAPTER_VERSION,
        "aibooru.json": ADAPTER_VERSION,
        "gelbooru.json": GELBOORU_VERSION,
        "gelbooru_html.json": GELBOORU_VERSION,
        "e621.json": E621_VERSION,
        "pixiv.json": PIXIV_ADAPTER_VERSION,
    }
    for name, version in expected.items():
        manifest = load_fixture_suite(FIXTURES / name).manifest
        assert manifest.adapter_version == version, name


def test_reprocess_rejects_unknown_or_foreign_raws(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with pytest.raises(ValueError, match="not found"):
            execute_reprocess(
                database, _replay_adapter(), raw_observation_ids=[999], clock=lambda: NOW
            )
        with pytest.raises(ValueError, match="at least one"):
            execute_reprocess(
                database, _replay_adapter(), raw_observation_ids=[], clock=lambda: NOW
            )


def test_replay_preserves_source_observation_time(tmp_path: Path) -> None:
    """Review regression (gh#8): replayed facts keep the source's chronology.

    A January raw reprocessed under a newer normalizer in October must not
    outrank a genuinely newer February observation: facts land at the
    retained raw's original observation time, and only the reprocess run
    carries the replay wall-clock time.
    """

    january = "2026-01-01T00:00:00Z"
    february = "2026-02-01T00:00:00Z"
    october = "2026-10-08T12:00:00Z"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=_fixture_payload(), headers={"content-type": "application/json"}
        )

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:

        def _sync_at(observed_at: str) -> int:
            MetadataSyncService(
                database,
                _old_adapter(handler, clock=lambda: observed_at),
                minimum_interval_seconds=0,
                maximum_retries=0,
                monotonic=lambda: 0.0,
                sleep=lambda _seconds: None,
                clock=lambda: observed_at,
            ).synchronize(AdapterOperation.FETCH_POST, "3001", limits=SyncLimits(1, 1, 50, 10))
            row = database.connection.execute(
                "SELECT raw_observation_id FROM raw_observations ORDER BY raw_observation_id DESC"
            ).fetchone()
            return int(row[0])

        january_raw = _sync_at(january)
        _sync_at(february)
        # The February observation owns the current projection.
        last_seen = database.connection.execute("SELECT last_seen_at FROM posts").fetchone()[0]
        assert last_seen == february

        result = execute_reprocess(
            database, _replay_adapter(), raw_observation_ids=[january_raw], clock=lambda: october
        )
        assert result["counts"] == {"complete": 1}
        run_id = result["results"][0]["remote_run_id"]

        # Facts keep the January source time, so the February observation
        # still wins the current projection despite the October replay.
        last_seen_after = database.connection.execute("SELECT last_seen_at FROM posts").fetchone()[
            0
        ]
        assert last_seen_after == february
        replayed_metadata = database.connection.execute(
            "SELECT observed_at FROM post_metadata_observations ORDER BY observed_at"
        ).fetchall()
        assert [row[0] for row in replayed_metadata] == [january, february]

        # The replay's own wall-clock time is run provenance only.
        run = database.connection.execute(
            "SELECT started_at, finished_at FROM remote_runs WHERE remote_run_id = ?",
            (run_id,),
        ).fetchone()
        assert (run["started_at"], run["finished_at"]) == (october, october)


def test_plan_reports_schema_version_drift(tmp_path: Path) -> None:
    """Review regression (gh#8): schema-only drift is stale too.

    The normalization identity is (payload, adapter version, schema
    version), so planning must not depend solely on the version-discipline
    rule that every normalization change bumps the adapter version.
    """

    drifted = replace(DANBOORU, schema_version="danbooru-json-v0")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=_fixture_payload(), headers={"content-type": "application/json"}
        )

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        MetadataSyncService(
            database,
            DanbooruAdapter(
                drifted,
                client=httpx.Client(transport=httpx.MockTransport(handler)),
                clock=lambda: NOW,
            ),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        ).synchronize(AdapterOperation.FETCH_POST, "3001", limits=SyncLimits(1, 1, 50, 10))
        plan = plan_reprocess(database, adapter=_replay_adapter())
        # Same adapter version, drifted schema version: still a candidate.
        assert plan["count"] == 1
        candidate = plan["results"][0]
        assert candidate["raw_adapter_version"] == ADAPTER_VERSION
        assert candidate["raw_schema_version"] == "danbooru-json-v0"
        assert candidate["already_reprocessed"] is False
