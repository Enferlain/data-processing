"""Bare-file discovery roots and generational follow-up (b8n).

A local file with no known source seeds a session from its intrinsic
verified identity; a provider hit fans out into one bounded follow-up
generation.  These tests pin the honest planning, the no-synthetic-identity
rule, the generation dedupe/depth/budget behavior, and session re-report
stability — all offline, with provider steps stubbed at the executor seam.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.discovery.orchestration import DiscoveryOrchestrator

_JPEG_MAGIC = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path):
        pass
    return path


@pytest.fixture()
def image_file(tmp_path: Path) -> Path:
    path = tmp_path / "picked.jpg"
    path.write_bytes(_JPEG_MAGIC * 64)
    return path


def test_bare_file_seed_plans_honestly_offline(catalog: Path, image_file: Path) -> None:
    with CatalogDatabase(catalog) as database:
        result = DiscoveryOrchestrator(database).start(file=image_file)
    assert result["input_kind"] == "local_file"
    assert result["seed_post_id"] is None
    assert result["seed_account_id"] is None
    assert result["seed_file_id"] is not None
    assert result["status"] == "planned"  # provider steps pending without --live
    # The seed's intrinsic identity is reported without the operator path.
    seed = result["file_seed"]
    assert seed["verified_md5"] and len(seed["verified_md5"]) == 32
    assert "source_path" not in seed
    methods = {(step["source"], step["method"]): step for step in result["steps"]}
    assert methods[("catalog", "local_md5")]["status"] == "complete"
    for method in ("local_source_url", "local_platform_identity"):
        step = methods[("catalog", method)]
        assert step["status"] == "excluded"
        assert "material" in step["detail"]
    # The verified hash is planned exactly where providers declare it.
    for provider in ("danbooru", "aibooru", "e621", "gelbooru"):
        assert methods[(provider, "verified_md5")]["status"] == "planned"
        assert methods[(provider, "source_post_url")]["status"] == "excluded"


def test_file_seed_creates_no_post_and_no_platform(catalog: Path, image_file: Path) -> None:
    with CatalogDatabase(catalog) as database:
        DiscoveryOrchestrator(database).start(file=image_file)
        posts = database.connection.execute("SELECT count(*) FROM posts").fetchone()[0]
        file_seeds = database.connection.execute(
            "SELECT count(*) FROM discovery_file_seeds"
        ).fetchone()[0]
    assert posts == 0
    assert file_seeds == 1


def test_missing_file_fails_before_any_write(catalog: Path) -> None:
    with (
        CatalogDatabase(catalog) as database,
        pytest.raises(ValueError, match="regular file"),
    ):
        DiscoveryOrchestrator(database).start(file=catalog / "absent.jpg")
    with CatalogDatabase(catalog) as database:
        sessions = database.connection.execute(
            "SELECT count(*) FROM discovery_sessions"
        ).fetchone()[0]
        seeds = database.connection.execute("SELECT count(*) FROM discovery_file_seeds").fetchone()[
            0
        ]
    assert (sessions, seeds) == (0, 0)


def test_file_seed_re_report_is_stable(catalog: Path, image_file: Path) -> None:
    with CatalogDatabase(catalog) as database:
        orchestrator = DiscoveryOrchestrator(database)
        first = orchestrator.start(file=image_file)
        session_id = first["session_id"]
        again = orchestrator.report(session_id)
    assert again["session_id"] == session_id
    assert again["steps"] == first["steps"]
    assert again["status"] == first["status"]


def test_followup_fetches_hits_once_and_caps_depth(catalog: Path, image_file: Path) -> None:
    """One hit plans one fetch; nothing plans beyond the follow-up wave."""
    with CatalogDatabase(catalog) as database:
        orchestrator = DiscoveryOrchestrator(database)

        # Plan offline first to get the session and step rows.
        result = orchestrator.start(file=image_file)
        session_id = result["session_id"]
        connection = database.connection

        # Pretend the e621 verified_md5 step hit a post candidate: record a
        # completed lookup run with a post_match result.
        step = connection.execute(
            """SELECT discovery_step_id FROM discovery_steps
                WHERE discovery_session_id = ? AND source = 'e621'
                  AND method = 'verified_md5'""",
            (session_id,),
        ).fetchone()
        connection.execute(
            """UPDATE discovery_steps SET status = 'complete', outcome = 'success',
                      result_count = 1 WHERE discovery_step_id = ?""",
            (step["discovery_step_id"],),
        )
        platform = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'e621'"
        ).fetchone()
        run_cursor = connection.execute(
            """INSERT INTO candidate_lookup_runs
                   (platform_id, instance_host, strategy, strategy_version,
                    adapter_version, schema_version, seed_file_id, seed_revision,
                    plan_digest, query_kind, material_digest, private_query_json,
                    status, request_limit, page_limit, result_limit,
                    time_limit_seconds, started_at, finished_at, result_count)
               VALUES (?, '', 'verified_md5', 'v1', 'v1', 'v1',
                       (SELECT discovery_file_seed_id FROM discovery_file_seeds
                         WHERE discovery_session_id = ?),
                       'r1', ?, 'md5', ?, '{}',
                       'complete', 1, 1, 10, 10, '2026-11-04T00:00:00Z',
                       '2026-11-04T00:00:01Z', 1)""",
            (
                platform["platform_id"],
                session_id,
                "a" * 64,
                "b" * 64,
            ),
        )
        run_id = run_cursor.lastrowid
        assert run_id is not None
        run_id = int(run_id)
        connection.execute(
            """UPDATE discovery_steps SET candidate_lookup_run_id = ?
                WHERE discovery_step_id = ?""",
            (run_id, step["discovery_step_id"]),
        )
        connection.execute(
            """INSERT INTO posts (post_id, platform_id, native_post_id,
                                      first_seen_at, last_seen_at)
               VALUES (3224, ?, '3224', '2026-11-04T00:00:00Z',
                       '2026-11-04T00:00:00Z')""",
            (platform["platform_id"],),
        )
        payload_cursor = connection.execute(
            """INSERT INTO raw_payloads (sha256, media_type, payload, byte_size)
               VALUES (?, 'application/json', '{}', 2)""",
            ("d" * 64,),
        )
        payload_id = payload_cursor.lastrowid
        assert payload_id is not None
        raw_cursor = connection.execute(
            """INSERT INTO raw_observations
                   (raw_payload_id, platform_id, object_kind, native_id,
                    media_type, source_schema, status, observed_at,
                    remote_run_id, adapter_version, schema_version,
                    transport_key, transport_version)
               VALUES (?, ?, 'post', '3224', 'application/json', 'v1', 'observed',
                       '2026-11-04T00:00:01Z', NULL, 'v1', 'v1', 'test', 'v1')""",
            (int(payload_id), platform["platform_id"]),
        )
        raw_id = raw_cursor.lastrowid
        assert raw_id is not None
        connection.execute(
            """INSERT INTO candidate_lookup_results
                   (candidate_lookup_run_id, result_kind, result_digest,
                    page_number, result_order, normalized_post_id,
                    raw_observation_id, observed_at)
               VALUES (?, 'post_match', ?, 1, 1, '3224', ?, '2026-11-04T00:00:01Z')""",
            (run_id, "c" * 64, int(raw_id)),
        )
        connection.commit()

        session = connection.execute(
            "SELECT * FROM discovery_sessions WHERE discovery_session_id = ?",
            (session_id,),
        ).fetchone()
        wave_a = orchestrator._plan_followup(session)
        identities = {(row["source"], row["method"], row["target"]) for row in wave_a}
        assert identities == {("e621", "fetch_post", "3224")}

        # Re-planning the same wave collapses: one reference, one step.
        assert orchestrator._plan_followup(session) == []

        # A wave-B plan from a fetched post never creates generation-2 rows:
        # depth is structurally capped because _plan_followup only reads
        # generation-0 steps.
        wave_b = orchestrator._plan_followup_from_posts(session, [999999])
        assert all(row["generation"] == 1 for row in wave_b)
