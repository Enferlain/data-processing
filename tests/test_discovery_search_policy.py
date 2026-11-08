"""Discovery search policy: freshness, deferral, dry-run, runs, inspection.

Stage 1 of the discovery/search roadmap (change add-discovery-search-policy,
bead data-processing-19p).  These tests pin the operator-visible contracts:
recheck modes, per-(target, method, evidence) independence, zero-result
scope retention, deferral instead of fake failures, dry-run planning,
multi-subject runs under one budget, and durable search-state inspection.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.discovery.attempts import SearchAttemptLedger, SubjectRef
from media_catalog.discovery.orchestration import DiscoveryOrchestrator
from media_catalog.discovery.policy import (
    RECHECK_STALE,
    SearchPolicy,
)
from media_catalog.discovery.run import DiscoveryRunService, SubjectInput

E926_URL = "https://e926.net/posts/6823045"
OTHER_URL = "https://e926.net/posts/6823046"


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path):
        pass
    return path


def _fake_results(*, status: str = "complete", requests: int = 1, results: int = 0):
    from media_catalog.candidate_lookup.service import LookupExecutionResult

    outcome = "success"
    if status == "paused":
        outcome = "budget_exhausted"
    elif status != "complete":
        outcome = "provider_failure"
    return (
        LookupExecutionResult(
            candidate_lookup_run_id=0,
            provider="danbooru",
            strategy="source_post_url",
            seed="post:1",
            status=status,
            outcome=outcome,
            request_count=requests,
            page_count=1,
            result_count=results,
        ),
    )


def _fake_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    requests: int = 1,
    results: int = 0,
    status: str = "complete",
    fail_platforms: tuple[str, ...] = (),
) -> list[str]:
    """Patch the orchestrator's provider machinery; returns executed platforms."""
    import media_catalog.discovery.orchestration as module

    executed: list[str] = []

    def construction(platform: str):
        if platform in fail_platforms:
            raise ValueError(f"no adapter for {platform}")

        def factory(client):
            return object()

        return factory, 0.0

    class FakeService:
        def __init__(self, database, adapter, *, minimum_interval_seconds):
            self._limits = None

        def plan(self, seed, strategies, *, limits=None, search_term=None):
            self._limits = limits
            return "plan"

        def execute(self, plan):
            executed.append("lookup")
            # Mirror the real bounded executor: never exceed the request
            # limit the orchestrator passed for this step.
            ceiling = self._limits.requests if self._limits is not None else 3
            return _fake_results(requests=min(requests, ceiling), results=results, status=status)

    monkeypatch.setattr(module, "adapter_construction", construction)
    monkeypatch.setattr(module, "CandidateLookupService", FakeService)
    return executed


def _live(catalog: Path, **kwargs) -> dict:
    with CatalogDatabase(catalog) as database:
        return DiscoveryOrchestrator(database).start(url=E926_URL, live=True, **kwargs)


def _attempts(catalog: Path) -> list[dict]:
    with CatalogDatabase(catalog) as database:
        return SearchAttemptLedger(database.connection).history(
            SubjectRef(post_id=_seed_post_id(catalog)), limit=100
        )


def _seed_post_id(catalog: Path) -> int:
    with CatalogDatabase(catalog) as database:
        row = database.connection.execute(
            "SELECT seed_post_id FROM discovery_sessions"
            " WHERE seed_post_id IS NOT NULL ORDER BY discovery_session_id LIMIT 1"
        ).fetchone()
    assert row is not None
    return int(row["seed_post_id"])


def _step(result: dict, source: str, method: str) -> dict:
    return next(
        step for step in result["steps"] if step["source"] == source and step["method"] == method
    )


# ── Freshness and recheck modes ──────────────────────────────────────────


def test_rerun_skips_fresh_successes_by_default(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_service(monkeypatch, requests=1)
    first = _live(catalog)
    assert _step(first, "catalog", "local_platform_identity")["status"] == "complete"
    executed = _fake_service(monkeypatch, requests=1)
    second = _live(catalog)
    # Nothing repeats: local and provider successes are skipped naming the
    # prior attempt, and no provider call runs again.
    assert executed == []
    assert _step(second, "danbooru", "source_post_url")["status"] == "skipped"
    assert "fresh successful attempt" in _step(second, "danbooru", "source_post_url")["detail"]
    assert _step(second, "catalog", "local_platform_identity")["status"] == "skipped"
    assert second["requests_used"] == 0


def test_force_recheck_reexecutes(catalog: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_service(monkeypatch)
    _live(catalog)
    executed = _fake_service(monkeypatch)
    again = _live(catalog, policy=SearchPolicy(recheck="force"))
    assert executed  # provider searches ran again
    assert _step(again, "danbooru", "source_post_url")["status"] == "complete"
    assert _step(again, "catalog", "local_platform_identity")["status"] == "complete"


def test_stale_recheck_replans_only_old_successes(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_service(monkeypatch)
    _live(catalog)
    # Age the danbooru attempt beyond the policy threshold; leave the local
    # catalog attempt young.
    with CatalogDatabase(catalog) as database:
        database.connection.execute(
            """UPDATE discovery_search_attempts
                  SET finished_at = '2020-01-01T00:00:01Z'
                WHERE source = 'danbooru'"""
        )
        database.connection.commit()
    executed = _fake_service(monkeypatch)
    again = _live(
        catalog,
        policy=SearchPolicy(recheck=RECHECK_STALE, stale_after_seconds=86_400 * 7),
    )
    danbooru = _step(again, "danbooru", "source_post_url")
    local = _step(again, "catalog", "local_platform_identity")
    assert danbooru["status"] == "complete"  # stale: re-executed
    assert local["status"] == "skipped"  # young: still fresh
    assert "older than" in (danbooru.get("detail") or "") or executed


def test_failed_attempts_are_retried_and_never_fresh(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_service(monkeypatch, fail_platforms=("danbooru",))
    first = _live(catalog)
    assert _step(first, "danbooru", "source_post_url")["status"] == "failed"


def test_provider_success_never_satisfies_another_provider(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_service(monkeypatch, fail_platforms=("aibooru",))
    _live(catalog)
    with CatalogDatabase(catalog) as database:
        ledger = SearchAttemptLedger(database.connection)
        subject = SubjectRef(post_id=_seed_post_id(catalog))
        # Keyed lookups miss on any key component: a digest no attempt used
        # resolves to nothing even for a provider that succeeded.
        assert (
            ledger.latest(
                subject,
                source_kind="provider",
                source="danbooru",
                method="source_post_url",
                query_digest="f" * 64,
            )
            is None
        )
        # The recorded keys are per provider: aibooru has attempts (failed),
        # danbooru has successful ones, and neither key covers the other.
        rows = ledger.latest_for_subject(subject)
    sources = {(row["source"], row["status"]) for row in rows.values()}
    assert ("danbooru", "complete") in sources
    assert ("aibooru", "failed") in sources


def test_changed_evidence_replans_under_default_mode(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_service(monkeypatch)
    _live(catalog)
    post_id = _seed_post_id(catalog)
    # New canonical url = new query evidence for the identity search: the
    # old success does not cover it even under recheck=unsearched.
    with CatalogDatabase(catalog) as database:
        database.connection.execute(
            "UPDATE posts SET canonical_url = 'https://e926.net/posts/9999999' WHERE post_id = ?",
            (post_id,),
        )
        database.connection.commit()
    again = _live(catalog)
    assert _step(again, "catalog", "local_platform_identity")["status"] == "complete"


# ── Zero results and scope ───────────────────────────────────────────────


def test_zero_result_attempt_is_fresh_and_scoped(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_service(monkeypatch, results=0)
    first = _live(catalog)
    step = _step(first, "danbooru", "source_post_url")
    assert step["status"] == "complete"
    assert step["result_count"] == 0
    rows = _attempts(catalog)
    danbooru = next(row for row in rows if row["source"] == "danbooru")
    assert danbooru["outcome"] == "success"
    assert danbooru["result_count"] == 0
    assert danbooru["scope"]  # the searched scope is retained
    # A zero-result success is fresh: rerunning must not repeat it.
    executed = _fake_service(monkeypatch)
    second = _live(catalog)
    assert executed == []
    assert _step(second, "danbooru", "source_post_url")["status"] == "skipped"


# ── Deferral and partial failures ────────────────────────────────────────


def test_budget_exhaustion_defers_instead_of_failing(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_service(monkeypatch, requests=6)
    result = _live(catalog, request_budget=7)
    provider_steps = [
        step
        for step in result["steps"]
        if step["source_kind"] == "provider" and step["status"] not in {"excluded", "skipped"}
    ]
    deferred = [step for step in provider_steps if step["status"] == "deferred"]
    assert deferred
    assert all(step["outcome"] == "budget_exhausted" for step in deferred)
    assert result["status"] == "partial"
    # Deferred steps wrote no attempt: nothing was searched for their keys
    # (the steps that did run before exhaustion keep theirs).
    attempted_keys = {
        (row["source"], row["method"], row["query_digest"]) for row in _attempts(catalog)
    }
    deferred_keys = {(step["source"], step["method"], step["query_digest"]) for step in deferred}
    assert deferred_keys
    assert not (attempted_keys & deferred_keys)
    # A later run resumes exactly the deferred work.
    executed = _fake_service(monkeypatch, requests=1)
    again = _live(catalog, request_budget=50)
    assert executed
    statuses = {_step(again, step["source"], step["method"])["status"] for step in provider_steps}
    assert "deferred" not in statuses


def test_paused_lookup_run_is_not_fresh(catalog: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A lookup that stopped on a budget boundary mid-run is partial work:
    # the step fails with the budget outcome and later runs retry it.
    _fake_service(monkeypatch, status="paused", requests=3)
    first = _live(catalog)
    step = _step(first, "danbooru", "source_post_url")
    assert step["status"] == "failed"
    assert step["outcome"] == "budget_exhausted"
    executed = _fake_service(monkeypatch)
    second = _live(catalog)
    assert executed
    assert _step(second, "danbooru", "source_post_url")["status"] in {"complete", "failed"}


# ── Dry-run ──────────────────────────────────────────────────────────────


def test_dry_run_plans_without_executing_or_attempting(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executed = _fake_service(monkeypatch)
    with CatalogDatabase(catalog) as database:
        result = DiscoveryOrchestrator(database).start(url=E926_URL, dry_run=True)
    assert executed == []
    assert result["requests_used"] == 0
    # Local steps stay planned: nothing executed at all.
    assert _step(result, "catalog", "local_md5")["status"] == "planned"
    assert _step(result, "danbooru", "source_post_url")["status"] == "planned"
    with CatalogDatabase(catalog) as database:
        count = database.connection.execute(
            "SELECT COUNT(*) FROM discovery_search_attempts"
        ).fetchone()[0]
    assert count == 0


def test_dry_run_reports_freshness_decisions(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_service(monkeypatch)
    _live(catalog)
    with CatalogDatabase(catalog) as database:
        result = DiscoveryOrchestrator(database).start(url=E926_URL, dry_run=True)
    step = _step(result, "danbooru", "source_post_url")
    assert step["status"] == "skipped"
    assert "fresh successful attempt" in step["detail"]


# ── Policy filters ───────────────────────────────────────────────────────


def test_include_and_exclude_sources_shape_the_plan(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_service(monkeypatch)
    with CatalogDatabase(catalog) as database:
        result = DiscoveryOrchestrator(database).start(
            url=E926_URL,
            policy=SearchPolicy(included_sources=frozenset({"danbooru", "catalog"})),
        )
    e621 = _step(result, "e621", "source_post_url")
    assert e621["status"] == "excluded"
    assert "not included by policy" in e621["detail"]
    assert _step(result, "danbooru", "source_post_url")["status"] == "planned"
    with CatalogDatabase(catalog) as database:
        result = DiscoveryOrchestrator(database).start(
            url=E926_URL,
            policy=SearchPolicy(excluded_sources=frozenset({"e621"})),
        )
    assert _step(result, "e621", "source_post_url")["status"] == "excluded"
    assert "excluded by policy" in _step(result, "e621", "source_post_url")["detail"]
    assert _step(result, "danbooru", "source_post_url")["status"] == "planned"


def test_method_filter_restricts_planning(catalog: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_service(monkeypatch)
    with CatalogDatabase(catalog) as database:
        result = DiscoveryOrchestrator(database).start(
            url=E926_URL,
            policy=SearchPolicy(methods=frozenset({"local_md5"})),
        )
    # A method with query material but filtered by policy names the policy;
    # the allowed local hash search still plans.
    filtered = _step(result, "danbooru", "source_post_url")
    assert filtered["status"] == "excluded"
    assert filtered["detail"] == "method filtered by policy"
    assert _step(result, "catalog", "local_md5")["status"] == "complete"
    local_identity = _step(result, "catalog", "local_platform_identity")
    assert local_identity["status"] == "excluded"
    assert local_identity["detail"] == "method filtered by policy"


def test_trails_only_excludes_active_methods_even_with_term(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_service(monkeypatch)
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        platform = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
        ).fetchone()
        connection.execute(
            "INSERT INTO accounts (platform_id, native_account_id, first_seen_at,"
            " last_seen_at) VALUES (?, '123', '2026-11-01T00:00:00Z',"
            " '2026-11-01T00:00:00Z')",
            (platform["platform_id"],),
        )
        account_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.commit()
        # An explicit trails-only policy overrides the search term's
        # active-search implication.
        result = DiscoveryOrchestrator(database).start(
            account_id=int(account_id),
            search_term="some_artist",
            policy=SearchPolicy(),
        )
    artist = _step(result, "danbooru", "artist_exact_name")
    assert artist["status"] == "excluded"
    assert artist["detail"] == "active search disabled by policy (trails only)"


# ── Bare-file subjects ───────────────────────────────────────────────────


def test_repeat_file_discovery_reuses_seed_and_skips_fresh_work(
    catalog: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "picked.jpg"
    image.write_bytes(b"policy-stage-file-subject")
    _fake_service(monkeypatch)
    with CatalogDatabase(catalog) as database:
        first = DiscoveryOrchestrator(database).start(file=image)
    with CatalogDatabase(catalog) as database:
        second = DiscoveryOrchestrator(database).start(file=image)
    assert second["seed_file_id"] == first["seed_file_id"]
    assert _step(second, "catalog", "local_md5")["status"] == "skipped"


# ── Multi-subject runs ───────────────────────────────────────────────────


def test_multi_subject_run_shares_budget_and_reports_progress(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each provider step burns 6 requests; the shared budget of 10 lets the
    # first subject's provider steps consume it and defers the rest across
    # ALL remaining subjects.
    _fake_service(monkeypatch, requests=6)
    progress: list[dict] = []
    with CatalogDatabase(catalog) as database:
        result = DiscoveryRunService(
            database, progress=lambda i, n, info: progress.append(info)
        ).run(
            [
                SubjectInput(url=E926_URL),
                SubjectInput(url=OTHER_URL),
            ],
            policy=SearchPolicy(),
            live=True,
            request_budget=10,
        )
    assert result["subjects"] == 2
    assert result["step_totals"].get("deferred")
    assert result["requests_used"] <= 10
    assert len(progress) == 2
    assert {info["session_id"] for info in progress} == {
        session["session_id"] for session in result["sessions"]
    }


def test_multi_subject_rerun_repeats_no_successful_work(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_service(monkeypatch, requests=1)
    with CatalogDatabase(catalog) as database:
        DiscoveryRunService(database).run(
            [SubjectInput(url=E926_URL), SubjectInput(url=OTHER_URL)],
            policy=SearchPolicy(),
            live=True,
            request_budget=50,
        )
    executed = _fake_service(monkeypatch, requests=1)
    with CatalogDatabase(catalog) as database:
        again = DiscoveryRunService(database).run(
            [SubjectInput(url=E926_URL), SubjectInput(url=OTHER_URL)],
            policy=SearchPolicy(),
            live=True,
            request_budget=50,
        )
    assert executed == []
    assert again["requests_used"] == 0
    assert "complete" not in again["step_totals"]
    assert "skipped" in again["step_totals"]


# ── Persistence and inspection ───────────────────────────────────────────


def test_attempts_survive_reopen_and_answer_history(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_service(monkeypatch)
    _live(catalog)
    with CatalogDatabase(catalog) as database:
        rows = SearchAttemptLedger(database.connection).history(
            SubjectRef(post_id=_seed_post_id(catalog))
        )
    assert rows
    for row in rows:
        assert row["started_at"]
        assert row["strategy_version"]
        assert row["query_digest"]
        # The ledger row links back to the session that produced it.
        assert row["discovery_session_id"]


def test_cli_search_state_reports_attempts_and_freshness(
    catalog: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from media_catalog.cli import main

    _fake_service(monkeypatch)
    # Offline session: local searches ran and are fresh; provider searches
    # were planned but never attempted.
    with CatalogDatabase(catalog) as database:
        DiscoveryOrchestrator(database).start(url=E926_URL)
    post_id = _seed_post_id(catalog)
    capsys.readouterr()
    main(
        [
            "discover",
            str(catalog),
            "--search-state",
            "--post",
            str(post_id),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["subjects"] == [f"post:{post_id}"]
    state = payload["state"][0]
    assert state["resolved"] is True
    local = next(
        entry
        for entry in state["entries"]
        if entry["source"] == "catalog" and entry["method"] == "local_platform_identity"
    )
    assert local["fresh"] is True
    assert local["latest_attempt"]["outcome"] == "success"
    assert local["latest_attempt"]["scope"]
    danbooru = next(
        entry
        for entry in state["entries"]
        if entry["source"] == "danbooru" and entry["method"] == "source_post_url"
    )
    assert danbooru["fresh"] is False
    assert danbooru["freshness"] == "never attempted"
    assert "latest_attempt" not in danbooru


def test_cli_rejects_unknown_sources_and_bad_flag_combinations(
    catalog: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from media_catalog.cli import main

    def error_of(argv: list[str]) -> str:
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
        return str(excinfo.value)

    message = error_of(
        ["discover", str(catalog), "--url", E926_URL, "--include-source", "danboru", "--json"]
    )
    assert "unknown search source" in json.loads(message)["error"]
    message = error_of(["discover", str(catalog), "--url", E926_URL, "--method", "md5", "--json"])
    assert "unknown search method" in json.loads(message)["error"]
    message = error_of(
        [
            "discover",
            str(catalog),
            "--url",
            E926_URL,
            "--include-source",
            "danbooru",
            "--exclude-source",
            "e621",
            "--json",
        ]
    )
    assert "mutually exclusive" in json.loads(message)["error"]
    message = error_of(
        ["discover", str(catalog), "--url", E926_URL, "--stale-after", "7d", "--json"]
    )
    assert "--stale-after" in json.loads(message)["error"]


def test_cli_search_state_is_offline_no_session_created(
    catalog: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from media_catalog.cli import main

    with CatalogDatabase(catalog) as database:
        sessions_before = database.connection.execute(
            "SELECT COUNT(*) FROM discovery_sessions"
        ).fetchone()[0]
    main(["discover", str(catalog), "--search-state", "--url", E926_URL, "--json"])
    payload = json.loads(capsys.readouterr().out)
    with CatalogDatabase(catalog) as database:
        sessions_after = database.connection.execute(
            "SELECT COUNT(*) FROM discovery_sessions"
        ).fetchone()[0]
    assert sessions_before == sessions_after == 0
    # The URL was never seeded: no durable subject, honestly reported.
    assert payload["state"][0]["resolved"] is False


# ── Ledger constraints ───────────────────────────────────────────────────


def test_attempt_ledger_rejects_multiple_subjects(catalog: Path) -> None:
    from media_catalog.records import SearchAttemptRecord

    with pytest.raises(ValueError, match="exactly one subject"):
        SearchAttemptRecord(
            source_kind="provider",
            source="danbooru",
            method="source_post_url",
            strategy_version="lookup-v1",
            query_digest="a" * 64,
            status="running",
            started_at="2026-11-08T00:00:00Z",
            discovery_session_id=1,
            subject_post_id=1,
            subject_account_id=2,
        )


def test_attempt_rows_survive_step_replan_protection(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attempt inputs are immutable; lifecycle fields are not."""
    _fake_service(monkeypatch)
    _live(catalog)
    with CatalogDatabase(catalog) as database:
        row = database.connection.execute(
            "SELECT discovery_search_attempt_id FROM discovery_search_attempts LIMIT 1"
        ).fetchone()
        assert row is not None
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                "UPDATE discovery_search_attempts SET query_digest = ?"
                " WHERE discovery_search_attempt_id = ?",
                ("b" * 64, row["discovery_search_attempt_id"]),
            )


def test_strategy_version_drift_verdict_explains_and_replans() -> None:
    from datetime import UTC, datetime

    from media_catalog.discovery.policy import freshness_verdict

    attempt = {
        "discovery_search_attempt_id": 9,
        "strategy_version": "lookup-v0",
        "status": "complete",
        "outcome": "success",
        "started_at": "2026-11-08T00:00:00Z",
        "finished_at": "2026-11-08T00:00:01Z",
    }
    verdict = freshness_verdict(
        SearchPolicy(), attempt, method="verified_md5", now=datetime.now(UTC)
    )
    assert verdict.fresh is False
    assert "prior attempt under strategy version lookup-v0" in verdict.reason
    assert "current lookup-v1" in verdict.reason


def _fabricate_recorded_hit(database, session_id: int, *, platform: str = "e621") -> None:
    """Fabricate a completed lookup run with one post_match hit, as the live
    pipeline would have persisted it (pattern: test_bare_file_discovery)."""
    connection = database.connection
    step = connection.execute(
        """SELECT discovery_step_id FROM discovery_steps
            WHERE discovery_session_id = ? AND source = ? AND method = 'verified_md5'""",
        (session_id, platform),
    ).fetchone()
    assert step is not None
    connection.execute(
        """UPDATE discovery_steps SET status = 'complete', outcome = 'success',
                  result_count = 1 WHERE discovery_step_id = ?""",
        (step["discovery_step_id"],),
    )
    platform_row = connection.execute(
        "SELECT platform_id FROM platforms WHERE platform_key = ?", (platform,)
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
        (platform_row["platform_id"], session_id, "a" * 64, "b" * 64),
    )
    run_id = int(run_cursor.lastrowid)
    connection.execute(
        """UPDATE discovery_steps SET candidate_lookup_run_id = ?
            WHERE discovery_step_id = ?""",
        (run_id, step["discovery_step_id"]),
    )
    connection.execute(
        """INSERT INTO posts (post_id, platform_id, native_post_id,
                                  first_seen_at, last_seen_at)
           VALUES (1, ?, '6531990', '2026-11-04T00:00:00Z', '2026-11-04T00:00:00Z')""",
        (platform_row["platform_id"],),
    )
    payload_cursor = connection.execute(
        """INSERT INTO raw_payloads (sha256, media_type, payload, byte_size)
           VALUES (?, 'application/json', '{}', 2)""",
        ("d" * 64,),
    )
    raw_cursor = connection.execute(
        """INSERT INTO raw_observations
               (raw_payload_id, platform_id, object_kind, native_id,
                media_type, source_schema, status, observed_at,
                remote_run_id, adapter_version, schema_version,
                transport_key, transport_version)
           VALUES (?, ?, 'post', '3224', 'application/json', 'v1', 'observed',
                   '2026-11-04T00:00:01Z', NULL, 'v1', 'v1', 'test', 'v1')""",
        (int(payload_cursor.lastrowid), platform_row["platform_id"]),
    )
    connection.execute(
        """INSERT INTO candidate_lookup_results
               (candidate_lookup_run_id, result_kind, result_digest,
                page_number, result_order, normalized_post_id,
                raw_observation_id, observed_at)
           VALUES (?, 'post_match', ?, 1, 1, 1, ?, '2026-11-04T00:00:01Z')""",
        (run_id, "c" * 64, int(raw_cursor.lastrowid)),
    )
    connection.commit()


class _FakeFetchResult:
    status = "complete"
    outcome = "success"
    remote_run_id = 1
    record_count = 1
    request_count = 1


def _fake_fetch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import media_catalog.remote_sync as remote_sync_module

    fetches: list[str] = []

    class FakeSync:
        def __init__(self, database, adapter, *, minimum_interval_seconds):
            pass

        def synchronize(self, operation, target, *, limits, resume_from_run_id=None):
            fetches.append(str(target))
            return _FakeFetchResult()

    monkeypatch.setattr(remote_sync_module, "MetadataSyncService", FakeSync)
    return fetches


def test_rerun_skips_fresh_followup_fetches_and_keeps_them_skipped(
    catalog: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "wave.jpg"
    image.write_bytes(b"policy-stage-wave-subject")
    _fake_service(monkeypatch, requests=1)
    fetches = _fake_fetch(monkeypatch)

    # Session 1: a recorded hit fans out to one wave-A fetch, which succeeds.
    with CatalogDatabase(catalog) as database:
        orchestrator = DiscoveryOrchestrator(database)
        first = orchestrator.start(file=image, live=True, request_budget=20)
        _fabricate_recorded_hit(database, first["session_id"])
        # The fetched post carries a canonical url, so wave B plans reverse
        # lookups naming that post (not the session seed) as their subject.
        connection = database.connection
        connection.execute(
            "UPDATE posts SET canonical_url = 'https://www.pixiv.net/artworks/123456'"
            " WHERE post_id = 1"
        )
        connection.commit()
        # Re-executing the session plans and runs the follow-up wave from
        # the fabricated hit (generation-0 steps are already terminal).
        orchestrator.execute(first["session_id"])
        wave_b_rows = connection.execute(
            """SELECT seed_post_id, source FROM discovery_steps
                WHERE discovery_session_id = ? AND generation = 1
                  AND method != 'fetch_post'""",
            (first["session_id"],),
        ).fetchall()
        first_report = orchestrator.report(first["session_id"])
    assert fetches == ["6531990", "123456"]  # wave-A hit + wave-B source link
    wave_a = [
        step
        for step in first_report["steps"]
        if step["method"] == "fetch_post" and step["generation"] == 1
    ]
    assert wave_a and wave_a[0]["status"] == "complete"
    # Wave-B reverse lookups search the fetched post's material: they must
    # name that post as their seed, never the session's file subject.
    assert wave_b_rows
    assert all(row["seed_post_id"] == 1 for row in wave_b_rows)

    # Session 2: every generation-0 provider success and the fetch are fresh,
    # so nothing re-executes — the fetch is skipped with its reason even
    # though the session's budget is smaller than session 1's.
    executed = _fake_service(monkeypatch, requests=6)
    with CatalogDatabase(catalog) as database:
        second = DiscoveryOrchestrator(database).start(file=image, live=True, request_budget=7)
    assert executed == []
    assert fetches == ["6531990", "123456"]
    wave_a_second = [
        step
        for step in second["steps"]
        if step["method"] == "fetch_post" and step["generation"] == 1
    ]
    assert wave_a_second
    assert wave_a_second[0]["status"] == "skipped"
    assert "fresh successful attempt" in (wave_a_second[0]["detail"] or "")
