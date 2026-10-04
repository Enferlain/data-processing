"""Storage-level enforcement of the provenance-kernel audit surfaces (migration 0012)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase

NOW = "2026-10-04T00:00:00Z"


def _platform_id(connection: sqlite3.Connection, key: str) -> int:
    return int(
        connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = ?", (key,)
        ).fetchone()[0]
    )


def _seed(database: CatalogDatabase) -> dict[str, int]:
    """Build one minimal row on every enforcement-target surface."""
    connection = database.connection
    x = _platform_id(connection, "x")
    danbooru = _platform_id(connection, "danbooru")
    ids: dict[str, int] = {}
    account_cursor = connection.execute(
        "INSERT INTO accounts (platform_id, native_account_id, first_seen_at, last_seen_at)"
        " VALUES (?, '9001', ?, ?)",
        (x, NOW, NOW),
    )
    ids["account"] = int(account_cursor.lastrowid)
    target_account_cursor = connection.execute(
        "INSERT INTO accounts (platform_id, native_account_id, first_seen_at, last_seen_at)"
        " VALUES (?, '9002', ?, ?)",
        (x, NOW, NOW),
    )
    ids["target_account"] = int(target_account_cursor.lastrowid)
    post_cursor = connection.execute(
        "INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)"
        " VALUES (?, '55', ?, ?)",
        (x, NOW, NOW),
    )
    ids["post"] = int(post_cursor.lastrowid)
    target_post_cursor = connection.execute(
        "INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)"
        " VALUES (?, '56', ?, ?)",
        (x, NOW, NOW),
    )
    ids["target_post"] = int(target_post_cursor.lastrowid)
    payload_cursor = connection.execute(
        "INSERT INTO raw_payloads (sha256, media_type, payload, byte_size)"
        " VALUES (?, 'application/json', x'7b7d', 2)",
        ("a" * 64,),
    )
    ids["raw_payload"] = int(payload_cursor.lastrowid)
    observation_cursor = connection.execute(
        "INSERT INTO raw_observations (raw_payload_id, platform_id, object_kind, native_id,"
        " media_type, observed_at) VALUES (?, ?, 'post', '55', 'application/json', ?)",
        (ids["raw_payload"], x, NOW),
    )
    ids["raw_observation"] = int(observation_cursor.lastrowid)
    event_cursor = connection.execute(
        "INSERT INTO observations (subject_kind, subject_id, event_type, source_kind,"
        " source_event_key, observed_at) VALUES ('post', ?, 'liked', 'fixture', 'evt-1', ?)",
        (ids["post"], NOW),
    )
    ids["observation"] = int(event_cursor.lastrowid)
    revision_cursor = connection.execute(
        "INSERT INTO observation_revisions (observation_id, observed_at) VALUES (?, ?)",
        (ids["observation"], NOW),
    )
    ids["observation_revision"] = int(revision_cursor.lastrowid)
    tag_cursor = connection.execute(
        "INSERT INTO tags (platform_id, category, name, normalization_version)"
        " VALUES (?, 'artist', 'fixture_tag', 'fixture-v1')",
        (danbooru,),
    )
    ids["tag"] = int(tag_cursor.lastrowid)
    post_tag_cursor = connection.execute(
        "INSERT INTO post_tags (post_id, tag_id, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)",
        (ids["post"], ids["tag"], NOW, NOW),
    )
    ids["post_tag"] = int(post_tag_cursor.lastrowid)
    post_tag_observation_cursor = connection.execute(
        "INSERT INTO post_tag_observations (post_tag_id, observed_at, provider_spelling,"
        " observation_digest) VALUES (?, ?, 'fixture_tag', ?)",
        (ids["post_tag"], NOW, "b" * 64),
    )
    ids["post_tag_observation"] = int(post_tag_observation_cursor.lastrowid)
    root_cursor = connection.execute(
        "INSERT INTO managed_roots (root_kind, root_identity, display_label, created_at)"
        " VALUES ('managed', 'fixture-root', 'fixture root', ?)",
        (NOW,),
    )
    ids["managed_root"] = int(root_cursor.lastrowid)
    adoption_run_cursor = connection.execute(
        "INSERT INTO adoption_runs (managed_root_id, managed_root_identity, algorithm_version,"
        " status, started_at) VALUES (?, 'fixture-root', 'fixture-v1', 'complete', ?)",
        (ids["managed_root"], NOW),
    )
    ids["adoption_run"] = int(adoption_run_cursor.lastrowid)
    item_cursor = connection.execute(
        "INSERT INTO adoption_items (adoption_run_id, item_key, outcome, created_at, updated_at)"
        " VALUES (?, 'fixture-item', 'existing', ?, ?)",
        (ids["adoption_run"], NOW, NOW),
    )
    ids["adoption_item"] = int(item_cursor.lastrowid)
    attempt_cursor = connection.execute(
        "INSERT INTO adoption_attempts (adoption_item_id, attempt_number, outcome, started_at)"
        " VALUES (?, 1, 'existing', ?)",
        (ids["adoption_item"], NOW),
    )
    ids["adoption_attempt"] = int(attempt_cursor.lastrowid)
    account_candidate_cursor = connection.execute(
        "INSERT INTO account_match_candidates (candidate_key, subject_account_id,"
        " target_account_id, relation_kind, score_version, created_at, updated_at)"
        " VALUES (?, ?, ?, 'same_identity', 'fixture-v1', ?, ?)",
        ("c" * 64, ids["account"], ids["target_account"], NOW, NOW),
    )
    ids["account_candidate"] = int(account_candidate_cursor.lastrowid)
    post_candidate_cursor = connection.execute(
        "INSERT INTO post_match_candidates (candidate_key, subject_post_id, target_post_id,"
        " relation_kind, score_version, created_at, updated_at)"
        " VALUES (?, ?, ?, 'same_work', 'fixture-v1', ?, ?)",
        ("d" * 64, ids["post"], ids["target_post"], NOW, NOW),
    )
    ids["post_candidate"] = int(post_candidate_cursor.lastrowid)
    evidence_cursor = connection.execute(
        "INSERT INTO match_evidence (evidence_digest, stance, evidence_kind, direction, strength,"
        " detector, detector_version, observed_at, explanation)"
        " VALUES (?, 'supports', 'fixture', 'none', 'weak', 'fixture', 'fixture-v1', ?, 'fixture')",
        ("e" * 64, NOW),
    )
    ids["evidence"] = int(evidence_cursor.lastrowid)
    connection.execute(
        "INSERT INTO account_candidate_evidence (account_candidate_id, evidence_id) VALUES (?, ?)",
        (ids["account_candidate"], ids["evidence"]),
    )
    connection.execute(
        "INSERT INTO post_candidate_evidence (post_candidate_id, evidence_id) VALUES (?, ?)",
        (ids["post_candidate"], ids["evidence"]),
    )
    account_decision_cursor = connection.execute(
        "INSERT INTO account_candidate_decisions (account_candidate_id, prior_state, decision,"
        " evidence_generation, decided_at) VALUES (?, 'pending', 'confirmed', 0, ?)",
        (ids["account_candidate"], NOW),
    )
    ids["account_decision"] = int(account_decision_cursor.lastrowid)
    post_decision_cursor = connection.execute(
        "INSERT INTO post_candidate_decisions (post_candidate_id, prior_state, decision,"
        " evidence_generation, decided_at) VALUES (?, 'pending', 'rejected', 0, ?)",
        (ids["post_candidate"], NOW),
    )
    ids["post_decision"] = int(post_decision_cursor.lastrowid)
    run_cursor = connection.execute(
        "INSERT INTO remote_runs (platform_id, operation, target, adapter_version, schema_version,"
        " request_budget, page_budget, record_budget, time_budget_seconds, origin_kind,"
        " origin_reference, started_at)"
        " VALUES (?, 'fetch_post', 'fixture:55', 'fixture-v1', 'fixture-v1', 1, 1, 1, 60,"
        " 'library_expansion', ?, ?)",
        (danbooru, "4" * 64, NOW),
    )
    ids["remote_run"] = int(run_cursor.lastrowid)
    request_cursor = connection.execute(
        "INSERT INTO remote_requests (remote_run_id, attempt_number, request_identity, operation,"
        " target, outcome, request_started_at) VALUES (?, 1, 'fixture-request', 'fetch_post',"
        " 'fixture:55', 'success', ?)",
        (ids["remote_run"], NOW),
    )
    ids["remote_request"] = int(request_cursor.lastrowid)
    occurrence_cursor = connection.execute(
        "INSERT INTO media_occurrences (post_id, source_key, media_index, media_type,"
        " remote_url, observed_at) VALUES (?, '55:p0', 0, 'image', 'https://example.test/55', ?)",
        (ids["post"], NOW),
    )
    ids["media_occurrence"] = int(occurrence_cursor.lastrowid)
    acquisition_plan_cursor = connection.execute(
        "INSERT INTO media_acquisition_plans (plan_version, selection_digest, requested_count,"
        " eligible_count, satisfied_count, excluded_count, created_at)"
        " VALUES ('fixture-plan-v1', ?, 1, 1, 0, 0, ?)",
        ("1" * 64, NOW),
    )
    ids["acquisition_plan"] = int(acquisition_plan_cursor.lastrowid)
    acquisition_item_cursor = connection.execute(
        "INSERT INTO media_acquisition_plan_items (acquisition_plan_id, item_key,"
        " media_occurrence_id, variant_key, material_digest, request_policy_key,"
        " request_policy_version, eligibility, created_at)"
        " VALUES (?, 'fixture-select', ?, 'primary', ?, 'fixture-policy', 'fixture-v1',"
        " 'eligible', ?)",
        (ids["acquisition_plan"], ids["media_occurrence"], "2" * 64, NOW),
    )
    ids["acquisition_plan_item"] = int(acquisition_item_cursor.lastrowid)
    acquisition_run_cursor = connection.execute(
        "INSERT INTO media_acquisition_runs (acquisition_plan_id, managed_root_id, max_items,"
        " max_item_bytes, max_total_bytes, max_attempts_per_item, max_seconds, max_redirects,"
        " max_quarantine_bytes, concurrency, started_at) VALUES (?, ?, 1, 10, 10, 1, 10, 1, 0,"
        " 1, ?)",
        (ids["acquisition_plan"], ids["managed_root"], NOW),
    )
    ids["acquisition_run"] = int(acquisition_run_cursor.lastrowid)
    run_item_cursor = connection.execute(
        "INSERT INTO media_acquisition_run_items (acquisition_run_id, acquisition_plan_item_id,"
        " state, created_at, updated_at) VALUES (?, ?, 'pending', ?, ?)",
        (ids["acquisition_run"], ids["acquisition_plan_item"], NOW, NOW),
    )
    ids["acquisition_run_item"] = int(run_item_cursor.lastrowid)
    acquisition_attempt_cursor = connection.execute(
        "INSERT INTO media_acquisition_attempts (acquisition_run_item_id, attempt_number,"
        " state, outcome, request_identity, request_policy_key, request_policy_version,"
        " started_at, finished_at) VALUES (?, 1, 'complete', 'downloaded', ?,"
        " 'fixture-policy', 'fixture-v1', ?, ?)",
        (ids["acquisition_run_item"], "3" * 64, NOW, NOW),
    )
    ids["acquisition_attempt"] = int(acquisition_attempt_cursor.lastrowid)
    verification_cursor = connection.execute(
        "INSERT INTO media_acquisition_verifications (acquisition_run_item_id, claim_kind,"
        " declared_value, verified_value, comparison_result, created_at)"
        " VALUES (?, 'sha256', 'declared', 'verified', 'matched', ?)",
        (ids["acquisition_run_item"], NOW),
    )
    ids["verification"] = int(verification_cursor.lastrowid)
    expansion_plan_cursor = connection.execute(
        "INSERT INTO library_expansion_plans (platform_id, target_kind, target_account_id,"
        " seed_account_id, seed_revision, authority_mode, capability_key, capability_version,"
        " target_native_id, target_revision, adapter_version, schema_version, source_revision,"
        " request_limit, page_limit, record_limit, time_limit_seconds, estimate_state,"
        " exclusions_json, plan_digest, material_digest, created_at)"
        " VALUES (?, 'account', ?, ?, 'fixture-rev', 'explicit', 'fixture-capability',"
        " 'fixture-v1', '9001', 'fixture-rev', 'fixture-v1', 'fixture-v1', 'fixture-rev',"
        " 1, 1, 1, 60, 'unknown', '{}', ?, ?, ?)",
        (danbooru, ids["account"], ids["account"], "4" * 64, "5" * 64, NOW),
    )
    ids["expansion_plan"] = int(expansion_plan_cursor.lastrowid)
    probe_cursor = connection.execute(
        "INSERT INTO library_expansion_probes (library_expansion_plan_id, capability_key,"
        " capability_version, adapter_version, schema_version, request_limit,"
        " time_limit_seconds, outcome, requested_at, observed_at)"
        " VALUES (?, 'fixture-capability', 'fixture-v1', 'fixture-v1', 'fixture-v1', 1, 10,"
        " 'unsupported', ?, ?)",
        (ids["expansion_plan"], NOW, NOW),
    )
    ids["expansion_probe"] = int(probe_cursor.lastrowid)
    execution_cursor = connection.execute(
        "INSERT INTO library_expansion_executions (library_expansion_plan_id, remote_run_id,"
        " execution_kind, created_at) VALUES (?, ?, 'initial', ?)",
        (ids["expansion_plan"], ids["remote_run"], NOW),
    )
    ids["expansion_execution"] = int(execution_cursor.lastrowid)
    expansion_post_cursor = connection.execute(
        "INSERT INTO library_expansion_posts (library_expansion_execution_id, post_id,"
        " observed_at) VALUES (?, ?, ?)",
        (ids["expansion_execution"], ids["post"], NOW),
    )
    ids["expansion_post"] = int(expansion_post_cursor.lastrowid)
    lookup_run_cursor = connection.execute(
        "INSERT INTO candidate_lookup_runs (platform_id, strategy, strategy_version,"
        " adapter_version, schema_version, seed_account_id, seed_revision, plan_digest,"
        " query_kind, material_digest, private_query_json, request_limit, page_limit,"
        " result_limit, time_limit_seconds, started_at)"
        " VALUES (?, 'artist_exact_name', 'fixture-v1', 'fixture-v1', 'fixture-v1', ?,"
        " 'fixture-rev', ?, 'fixture', ?, '{}', 1, 1, 1, 60, ?)",
        (danbooru, ids["account"], "6" * 64, "7" * 64, NOW),
    )
    ids["lookup_run"] = int(lookup_run_cursor.lastrowid)
    lookup_request_cursor = connection.execute(
        "INSERT INTO candidate_lookup_requests (candidate_lookup_run_id, attempt_number,"
        " request_identity, state, outcome, started_at, finished_at)"
        " VALUES (?, 1, 'fixture-lookup-request', 'complete', 'success', ?, ?)",
        (ids["lookup_run"], NOW, NOW),
    )
    ids["lookup_request"] = int(lookup_request_cursor.lastrowid)
    return ids


@pytest.fixture()
def seeded(tmp_path: Path) -> tuple[CatalogDatabase, dict[str, int]]:
    database = CatalogDatabase(tmp_path / "catalog.sqlite3")
    with database.transaction():
        ids = _seed(database)
    yield database, ids
    database.close()


FULLY_IMMUTABLE = [
    ("raw_observations", "raw_observation_id", "source reports are append-only"),
    ("post_tag_observations", "post_tag_observation_id", "post tag observations are append-only"),
    (
        "observation_revisions",
        "observation_revision_id",
        "provenance event revisions are append-only",
    ),
    (
        "account_candidate_decisions",
        "account_decision_id",
        "account review decisions are append-only",
    ),
    ("post_candidate_decisions", "post_decision_id", "post review decisions are append-only"),
    (
        "media_acquisition_verifications",
        "acquisition_verification_id",
        "acquisition verifications are append-only",
    ),
    ("raw_payloads", "raw_payload_id", "source report payloads are append-only"),
]

UNDELETABLE = [
    *FULLY_IMMUTABLE,
    ("observations", "observation_id", "provenance events cannot be deleted"),
    ("adoption_attempts", "adoption_attempt_id", "adoption attempts cannot be deleted"),
    (
        "account_match_candidates",
        "account_candidate_id",
        "account match candidates cannot be deleted",
    ),
    ("post_match_candidates", "post_candidate_id", "post match candidates cannot be deleted"),
    ("match_evidence", "evidence_id", "match evidence cannot be deleted"),
    (
        "account_candidate_evidence",
        "account_candidate_id",
        "account candidate evidence links cannot be deleted",
    ),
    (
        "post_candidate_evidence",
        "post_candidate_id",
        "post candidate evidence links cannot be deleted",
    ),
    ("remote_requests", "remote_request_id", "remote requests cannot be deleted"),
    (
        "library_expansion_plans",
        "library_expansion_plan_id",
        "library expansion plans cannot be deleted",
    ),
    (
        "library_expansion_probes",
        "library_expansion_probe_id",
        "library expansion probes cannot be deleted",
    ),
    (
        "library_expansion_executions",
        "library_expansion_execution_id",
        "library expansion executions cannot be deleted",
    ),
    (
        "library_expansion_posts",
        "library_expansion_post_id",
        "library expansion post associations cannot be deleted",
    ),
    (
        "candidate_lookup_requests",
        "candidate_lookup_request_id",
        "candidate lookup requests cannot be deleted",
    ),
    (
        "media_acquisition_attempts",
        "acquisition_attempt_id",
        "media acquisition attempts cannot be deleted",
    ),
]


@pytest.mark.parametrize(("table", "key", "message"), FULLY_IMMUTABLE)
def test_fully_immutable_surfaces_reject_update(
    seeded: tuple[CatalogDatabase, dict[str, int]],
    table: str,
    key: str,
    message: str,
) -> None:
    database, ids = seeded
    with pytest.raises(sqlite3.IntegrityError, match=message):
        database.connection.execute(
            f"UPDATE {table} SET {key} = {key} WHERE {key} = ?",
            (ids[key_id(table)],),
        )


@pytest.mark.parametrize(("table", "key", "message"), UNDELETABLE)
def test_audit_surfaces_reject_delete(
    seeded: tuple[CatalogDatabase, dict[str, int]],
    table: str,
    key: str,
    message: str,
) -> None:
    database, ids = seeded
    with pytest.raises(sqlite3.IntegrityError, match=message):
        database.connection.execute(
            f"DELETE FROM {table} WHERE {key} = ?",
            (ids[key_id(table)],),
        )


def key_id(table: str) -> str:
    return {
        "raw_observations": "raw_observation",
        "post_tag_observations": "post_tag_observation",
        "observation_revisions": "observation_revision",
        "account_candidate_decisions": "account_decision",
        "post_candidate_decisions": "post_decision",
        "observations": "observation",
        "adoption_attempts": "adoption_attempt",
        "account_match_candidates": "account_candidate",
        "post_match_candidates": "post_candidate",
        "match_evidence": "evidence",
        "account_candidate_evidence": "account_candidate",
        "post_candidate_evidence": "post_candidate",
        "remote_requests": "remote_request",
        "media_acquisition_verifications": "verification",
        "raw_payloads": "raw_payload",
        "library_expansion_plans": "expansion_plan",
        "library_expansion_probes": "expansion_probe",
        "library_expansion_executions": "expansion_execution",
        "library_expansion_posts": "expansion_post",
        "candidate_lookup_requests": "lookup_request",
        "media_acquisition_attempts": "acquisition_attempt",
    }[table]


def test_remote_request_allows_only_the_source_report_attach(
    seeded: tuple[CatalogDatabase, dict[str, int]],
) -> None:
    database, ids = seeded
    connection = database.connection
    connection.execute(
        "UPDATE remote_requests SET raw_observation_id = ? WHERE remote_request_id = ?",
        (ids["raw_observation"], ids["remote_request"]),
    )
    connection.execute(
        "UPDATE remote_requests SET raw_observation_id = ? WHERE remote_request_id = ?",
        (ids["raw_observation"], ids["remote_request"]),
    )
    with pytest.raises(sqlite3.IntegrityError, match="remote request fields are immutable"):
        connection.execute(
            "UPDATE remote_requests SET outcome = 'unavailable' WHERE remote_request_id = ?",
            (ids["remote_request"],),
        )
    with pytest.raises(sqlite3.IntegrityError, match="remote request fields are immutable"):
        connection.execute(
            "UPDATE remote_requests SET raw_observation_id = NULL WHERE remote_request_id = ?",
            (ids["remote_request"],),
        )


def test_remote_request_rejects_swapping_the_source_report(
    seeded: tuple[CatalogDatabase, dict[str, int]],
) -> None:
    database, ids = seeded
    connection = database.connection
    other_payload = int(
        connection.execute(
            "INSERT INTO raw_payloads (sha256, media_type, payload, byte_size)"
            " VALUES (?, 'application/json', x'7b7d', 2)",
            ("9" * 64,),
        ).lastrowid
    )
    other_observation = int(
        connection.execute(
            "INSERT INTO raw_observations (raw_payload_id, platform_id, object_kind, native_id,"
            " media_type, observed_at) VALUES (?, ?, 'post', '56', 'application/json', ?)",
            (other_payload, _platform_id(connection, "x"), NOW),
        ).lastrowid
    )
    connection.execute(
        "UPDATE remote_requests SET raw_observation_id = ? WHERE remote_request_id = ?",
        (ids["raw_observation"], ids["remote_request"]),
    )
    with pytest.raises(sqlite3.IntegrityError, match="remote request fields are immutable"):
        connection.execute(
            "UPDATE remote_requests SET raw_observation_id = ? WHERE remote_request_id = ?",
            (other_observation, ids["remote_request"]),
        )


def test_conditional_triggers_allow_noop_updates(
    seeded: tuple[CatalogDatabase, dict[str, int]],
) -> None:
    database, ids = seeded
    connection = database.connection
    connection.execute(
        "UPDATE remote_runs SET target = target WHERE remote_run_id = ?",
        (ids["remote_run"],),
    )
    connection.execute(
        "UPDATE remote_requests SET outcome = outcome WHERE remote_request_id = ?",
        (ids["remote_request"],),
    )


def test_remote_run_inputs_are_immutable_while_state_advances(
    seeded: tuple[CatalogDatabase, dict[str, int]],
) -> None:
    database, ids = seeded
    connection = database.connection
    connection.execute(
        "UPDATE remote_runs SET status = 'complete', request_count = 1, page_count = 1,"
        " record_count = 1, termination_outcome = 'success', finished_at = ?"
        " WHERE remote_run_id = ? AND status = 'running'",
        (NOW, ids["remote_run"]),
    )
    with pytest.raises(sqlite3.IntegrityError, match="remote run inputs are immutable"):
        connection.execute(
            "UPDATE remote_runs SET target = 'fixture:other' WHERE remote_run_id = ?",
            (ids["remote_run"],),
        )
    with pytest.raises(sqlite3.IntegrityError, match="remote run inputs are immutable"):
        connection.execute(
            "UPDATE remote_runs SET transport_key = 'fixture-transport' WHERE remote_run_id = ?",
            (ids["remote_run"],),
        )


def test_current_field_updates_remain_possible(
    seeded: tuple[CatalogDatabase, dict[str, int]],
) -> None:
    database, ids = seeded
    connection = database.connection
    connection.execute(
        'UPDATE observations SET collection_data = \'{"folder":"later"}\' WHERE observation_id = ?',
        (ids["observation"],),
    )
    connection.execute(
        "UPDATE adoption_attempts SET outcome = 'hash_mismatch' WHERE adoption_attempt_id = ?",
        (ids["adoption_attempt"],),
    )
    connection.execute(
        "UPDATE account_match_candidates SET current_state = 'confirmed',"
        " review_revision = 1 WHERE account_candidate_id = ?",
        (ids["account_candidate"],),
    )
    connection.execute(
        "UPDATE match_evidence SET evidence_digest = ? WHERE evidence_id = ?",
        ("f" * 64, ids["evidence"]),
    )


def test_recreated_run_input_triggers_guard_their_primary_keys(
    seeded: tuple[CatalogDatabase, dict[str, int]],
) -> None:
    database, ids = seeded
    connection = database.connection
    connection.execute(
        "UPDATE media_acquisition_runs SET status = status WHERE acquisition_run_id = ?",
        (ids["acquisition_run"],),
    )
    with pytest.raises(sqlite3.IntegrityError, match="media acquisition run inputs"):
        connection.execute(
            "UPDATE media_acquisition_runs SET acquisition_run_id = 4242"
            " WHERE acquisition_run_id = ?",
            (ids["acquisition_run"],),
        )
    connection.execute(
        "UPDATE candidate_lookup_runs SET status = status WHERE candidate_lookup_run_id = ?",
        (ids["lookup_run"],),
    )
    with pytest.raises(sqlite3.IntegrityError, match="candidate lookup run inputs"):
        connection.execute(
            "UPDATE candidate_lookup_runs SET candidate_lookup_run_id = 4242"
            " WHERE candidate_lookup_run_id = ?",
            (ids["lookup_run"],),
        )
    with pytest.raises(sqlite3.IntegrityError, match="media acquisition run inputs"):
        connection.execute(
            "UPDATE media_acquisition_runs SET max_items = max_items + 1"
            " WHERE acquisition_run_id = ?",
            (ids["acquisition_run"],),
        )
    with pytest.raises(sqlite3.IntegrityError, match="candidate lookup run inputs"):
        connection.execute(
            "UPDATE candidate_lookup_runs SET plan_digest = ? WHERE candidate_lookup_run_id = ?",
            ("8" * 64, ids["lookup_run"]),
        )


def test_insert_or_replace_cannot_bypass_delete_guards(
    seeded: tuple[CatalogDatabase, dict[str, int]],
) -> None:
    database, ids = seeded
    connection = database.connection
    with pytest.raises(sqlite3.IntegrityError, match="library expansion plans cannot be deleted"):
        connection.execute(
            """INSERT OR REPLACE INTO library_expansion_plans (
                   library_expansion_plan_id, platform_id, target_kind, target_account_id,
                   seed_account_id, seed_revision, authority_mode, capability_key,
                   capability_version, target_native_id, target_revision, adapter_version,
                   schema_version, source_revision, request_limit, page_limit, record_limit,
                   time_limit_seconds, estimate_state, exclusions_json, plan_digest,
                   material_digest, created_at
               ) VALUES (?, 1, 'account', 1, 1, 'x', 'explicit', 'x', 'x', 'x', 'x', 'x',
                         'x', 'x', 1, 1, 1, 1, 'unknown', '{}', ?, ?, ?)""",
            (ids["expansion_plan"], "9" * 64, "b" * 64, NOW),
        )
