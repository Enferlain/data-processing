"""Discovery orchestration (roadmap P0.1): the composition entry point.

The orchestrator binds existing machinery — seed materialization, lookup
planning materials, the candidate lookup service, the shared adapter
factory — into one session.  These tests pin the binding: input identity,
planner transparency, offline-by-default execution, failure containment, and
budgets.  No synthetic provider fixtures; live paths run against fakes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.discovery.orchestration import DiscoveryOrchestrator

E926_URL = "https://e926.net/posts/6823045"


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path):
        pass
    return path


def _seed_url_session(catalog: Path) -> dict:
    with CatalogDatabase(catalog) as database:
        return DiscoveryOrchestrator(database).start(url=E926_URL)


def test_url_input_materializes_a_seed_and_plans(catalog: Path) -> None:
    result = _seed_url_session(catalog)
    assert result["input_kind"] == "url"
    assert result["seed_post_id"] is not None
    assert result["live_authorized"] is False
    methods = {(step["source"], step["method"]): step for step in result["steps"]}
    for method in ("local_md5", "local_source_url", "local_platform_identity"):
        # Local steps are catalog queries: they complete without --live.
        assert methods[("catalog", method)]["status"] == "complete"
    # The seed carries a canonical URL and no hash: source-URL strategies are
    # planned where declared, hash strategies excluded naming the material.
    assert methods[("danbooru", "source_post_url")]["status"] == "planned"
    assert methods[("danbooru", "verified_md5")]["status"] == "excluded"
    # Providers without declared lookup stay out of the plan entirely.
    assert all(step["source"] != "pawchive" for step in result["steps"])


def test_same_url_reuses_the_seed_identity(catalog: Path) -> None:
    first = _seed_url_session(catalog)
    second = _seed_url_session(catalog)
    assert second["seed_post_id"] == first["seed_post_id"]
    assert second["session_id"] != first["session_id"]


def test_offline_sessions_execute_local_steps_only(catalog: Path) -> None:
    result = _seed_url_session(catalog)
    local = [step for step in result["steps"] if step["source"] == "catalog"]
    assert all(step["status"] == "complete" for step in local)
    providers = [
        step
        for step in result["steps"]
        if step["source"] != "catalog" and step["status"] not in {"excluded", "skipped"}
    ]
    assert providers and all(step["status"] == "planned" for step in providers)
    # Every considered (source, method) pair is reported: the undeclared
    # strategies appear as skipped with their capability reason.
    assert any(step["status"] == "skipped" for step in result["steps"])
    # A scoped empty result records its scope, not a global claim.
    md5 = next(step for step in local if step["method"] == "local_md5")
    assert md5["detail"] == "seed carries no verified or declared hash"


def test_account_seed_with_search_term_plans_artist_strategies(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        platform = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
        ).fetchone()
        connection.execute(
            "INSERT INTO accounts (platform_id, native_account_id, canonical_url,"
            " first_seen_at, last_seen_at)"
            " VALUES (?, '123', 'https://danbooru.donmai.us/artists/123',"
            " '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z')",
            (platform["platform_id"],),
        )
        account_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        # The account carries an artist name; the search term unlocks the
        # artist strategies for every provider that declares them.
        digest = hashlib.sha256(b"some-account-snapshot").hexdigest()
        connection.execute(
            "INSERT INTO account_snapshots (account_id, observed_at, display_name,"
            " snapshot_digest) VALUES (?, '2026-11-01T00:00:00Z', 'some_artist', ?)",
            (account_id, digest),
        )
        database.connection.commit()
        result = DiscoveryOrchestrator(database).start(
            account_id=int(account_id), search_term="some_artist"
        )
    artist_steps = [
        step
        for step in result["steps"]
        if step["method"].startswith("artist_") and step["status"] == "planned"
    ]
    assert artist_steps, result["steps"]


def test_account_seed_excludes_post_local_steps(catalog: Path) -> None:
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
        database.connection.commit()
        result = DiscoveryOrchestrator(database).start(account_id=int(account_id))
    assert result["input_kind"] == "account"
    local = [step for step in result["steps"] if step["source"] == "catalog"]
    assert all(step["status"] == "excluded" for step in local)


def test_exactly_one_input_is_required(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        with pytest.raises(ValueError, match="exactly one input"):
            DiscoveryOrchestrator(database).start()
        with pytest.raises(ValueError, match="exactly one input"):
            DiscoveryOrchestrator(database).start(url=E926_URL, post_id=1)


def _fake_results(*, status: str = "complete", requests: int = 1, results: int = 0):
    from media_catalog.candidate_lookup.service import LookupExecutionResult

    return (
        LookupExecutionResult(
            candidate_lookup_run_id=0,
            provider="danbooru",
            strategy="source_post_url",
            seed="post:1",
            status=status,
            outcome="success" if status == "complete" else "provider_failure",
            request_count=requests,
            page_count=1,
            result_count=results,
        ),
    )


def test_live_session_contains_factory_failures_and_links_runs(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import media_catalog.discovery.orchestration as module

    calls: list[str] = []

    def fake_construction(platform: str):
        def factory(client):
            return object()

        return factory, 0.0

    def fail_construction(platform: str):
        if platform == "gelbooru":
            raise ValueError("configure both GELBOORU_USER_ID and GELBOORU_API_KEY")
        return fake_construction(platform)

    class FakeLookupService:
        def __init__(self, database, adapter, *, minimum_interval_seconds):
            pass

        def plan(self, seed, strategies, *, limits=None, search_term=None):
            return "plan-token"

        def execute(self, plan):
            calls.append("execute")
            return _fake_results(requests=2, results=1)

    monkeypatch.setattr(module, "adapter_construction", fail_construction)
    monkeypatch.setattr(module, "CandidateLookupService", FakeLookupService)
    with CatalogDatabase(catalog) as database:
        result = DiscoveryOrchestrator(database).start(url=E926_URL, live=True)
    by_key = {(step["source"], step["method"]): step for step in result["steps"]}
    gelbooru = by_key[("gelbooru", "source_post_url")]
    assert gelbooru["status"] == "failed"
    assert "GELBOORU_USER_ID" in gelbooru["detail"]
    danbooru = by_key[("danbooru", "source_post_url")]
    assert danbooru["status"] == "complete"
    assert danbooru["result_count"] == 1
    assert danbooru["candidate_lookup_run_id"] is None  # fake reports no persisted run
    assert calls  # provider executions actually ran


def test_session_request_budget_bounds_provider_steps(
    catalog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import media_catalog.discovery.orchestration as module

    monkeypatch.setattr(
        module, "adapter_construction", lambda platform: (lambda client: object(), 0.0)
    )

    class HungryService:
        def __init__(self, database, adapter, *, minimum_interval_seconds):
            pass

        def plan(self, seed, strategies, *, limits=None, search_term=None):
            return "plan"

        def execute(self, plan):
            return _fake_results(requests=6)

    monkeypatch.setattr(module, "CandidateLookupService", HungryService)
    with CatalogDatabase(catalog) as database:
        result = DiscoveryOrchestrator(database).start(url=E926_URL, live=True, request_budget=7)
    provider_steps = [
        step
        for step in result["steps"]
        if step["source"] != "catalog" and step["status"] not in {"excluded", "skipped"}
    ]
    executed = [step for step in provider_steps if step["status"] == "complete"]
    exhausted = [step for step in provider_steps if step.get("outcome") == "budget_exhausted"]
    # 6 requests per step against a budget of 7: at most two steps run
    # before the remainder is marked exhausted without further calls.
    assert 1 <= len(executed) <= 2
    assert exhausted
    assert len(executed) + len(exhausted) == len(provider_steps)


def test_cli_discovers_offline_and_re_reports(
    catalog: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from media_catalog.cli import main

    main(["discover", str(catalog), "--url", E926_URL, "--json"])
    payload = json.loads(capsys.readouterr().out)
    # Offline sessions finish their local steps but stay "planned" overall:
    # provider steps are pending explicit live authorization.
    assert payload["status"] == "planned"
    assert payload["seed_post_id"] is not None
    session_id = payload["session_id"]

    main(["discover", str(catalog), "--session", str(session_id), "--json"])
    again = json.loads(capsys.readouterr().out)
    assert again["session_id"] == session_id
    assert again["status"] == "planned"
    # Step outcomes persist across the reopen: the offline local steps must
    # still read as complete with their scoped details (a regression here
    # once silently rolled every outcome back on close).
    assert [(step["method"], step["status"], step["detail"]) for step in again["steps"][:3]] == [
        (step["method"], step["status"], step["detail"]) for step in payload["steps"][:3]
    ]
    assert again["steps"][0]["status"] == "complete"


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://aibooru.online/posts/3001", "aibooru"),
        ("https://e926.net/posts/6823045", "e926"),
        ("https://rule34.xxx/index.php?page=post&s=view&id=19210742", "rule34"),
        ("https://safebooru.org/index.php?page=post&s=view&id=7272295", "safebooru"),
        ("https://sankaku.app/posts/wvaemE6YDaz", "sankaku"),
        (
            "https://chan.sankakucomplex.com/posts/wvaemE6YDaz",
            "sankaku",
        ),
        (
            "https://pawchive.pw/patreon/user/75232195/post/70439020",
            "pawchive",
        ),
    ],
)
def test_seed_recognition_covers_every_registered_platform(url: str, platform: str) -> None:
    # Discovery inputs materialize through the seed path, so its URL
    # recognizer must know every platform the registry ships — the drift this
    # change closed (aibooru/e926/rule34/sankaku/pawchive were unrecognized,
    # and safebooru post URLs missed the gelbooru query grammar).
    from media_catalog.links import recognize_url

    reference = recognize_url(url).reference
    assert reference is not None
    assert reference.platform == platform
    assert reference.object_kind == "post"
    assert reference.identifier_kind == "stable_id"
