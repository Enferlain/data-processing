"""Whole-catalog cross-check (bead data-processing-p1t, change
add-catalog-cross-check): corpus selection, reuse, budget stops at item
boundaries, durable resume, rate-limit visibility, and that matches never
become relationships."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import ClassVar

import pytest

from media_catalog.adapters.contracts import (
    LookupCapabilities,
    LookupPlanContext,
    LookupStrategy,
)
from media_catalog.crosscheck import CrosscheckBudget, select_corpus
from media_catalog.database import CatalogDatabase

MD5 = "0123456789abcdef0123456789abcdef"


class _FakeResult:
    def __init__(
        self,
        *,
        run_id: int,
        request_count: int = 1,
        result_count: int = 0,
        retry_after: str | None = None,
    ) -> None:
        self.candidate_lookup_run_id = run_id
        self.provider = "danbooru"
        self.strategy = "verified_md5"
        self.seed = "post:1"
        self.status = "complete"
        self.outcome = "success"
        self.request_count = request_count
        self.page_count = 1
        self.result_count = result_count
        self.retry_after = retry_after
        self.budget_boundary = None
        self.diagnostic = None


class _FakeAdapter:
    instance_key = "danbooru"
    adapter_version = "fake-adapter-v1"
    schema_version = "fake-schema-v1"

    def __init__(self) -> None:
        self.instance = self  # the coordinator reads capabilities off .instance
        self.lookup_plan_context = LookupPlanContext(
            provider="danbooru",
            instance_key="danbooru",
            adapter_version=self.adapter_version,
            schema_version=self.schema_version,
            lookup_capabilities=LookupCapabilities(
                frozenset(
                    strategy
                    for strategy in LookupStrategy
                    if strategy in (LookupStrategy.VERIFIED_MD5, LookupStrategy.DECLARED_MD5)
                )
            ),
        )


class _FakeService:
    calls: ClassVar[list[tuple[str, str]]] = []
    results_for: ClassVar[dict[tuple[str, str], int]] = {}
    retry_once_for: ClassVar[dict[tuple[str, str], str]] = {}
    # run id 0 = no run row (the real service creates run rows; the fake
    # keeps FK-safe NULL provenance — run-id provenance is exercised by the
    # real-data run)
    _run_id = 0

    def __init__(self, database, adapter, minimum_interval_seconds: float = 0.0) -> None:
        self.database = database
        self.adapter = adapter

    def plan(self, seed, strategies, *, limits=None, search_term=None):
        class _Plan:
            def __init__(self, seed_, strategies_):
                self.seed = seed_
                self.strategies = strategies_

        return _Plan(seed, strategies)

    def execute(self, plan):
        return tuple(self._one(plan.seed, strategy.value) for strategy in plan.strategies)

    def _one(self, seed: str, strategy: str) -> _FakeResult:
        _FakeService.calls.append((seed, strategy))
        matched = _FakeService.results_for.get((seed, strategy), 0)
        retry = _FakeService.retry_once_for.pop((seed, strategy), None)
        return _FakeResult(
            run_id=_FakeService._run_id,
            request_count=1,
            result_count=matched,
            retry_after=retry,
        )


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database, database.transaction():
        platform = database.connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'gelbooru'"
        ).fetchone()
        assert platform is not None
        platform_id = int(platform["platform_id"])
        hashed = database.connection.execute(
            """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
               VALUES (?, 'cc-1', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
            (platform_id,),
        )
        database.connection.execute(
            """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                              media_type, declared_md5, observed_at)
               VALUES (?, 'cc:p0', 0, 'image/png', ?, '2026-01-01T00:00:00Z')""",
            (int(hashed.lastrowid), MD5),
        )
        second_hashed = database.connection.execute(
            """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
               VALUES (?, 'cc-3', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
            (platform_id,),
        )
        database.connection.execute(
            """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                              media_type, declared_md5, observed_at)
               VALUES (?, 'cc:p2', 0, 'image/png', ?, '2026-01-01T00:00:00Z')""",
            (int(second_hashed.lastrowid), "f" * 32),
        )
        bare = database.connection.execute(
            """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
               VALUES (?, 'cc-2', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
            (platform_id,),
        )
        database.connection.execute(
            """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                              media_type, observed_at)
               VALUES (?, 'cc:p1', 0, 'image/png', '2026-01-01T00:00:00Z')""",
            (int(bare.lastrowid),),
        )
    return path


@pytest.fixture()
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> type[_FakeService]:
    import media_catalog.crosscheck as crosscheck_module

    monkeypatch.setattr(crosscheck_module, "CandidateLookupService", _FakeService)
    monkeypatch.setattr(
        "media_catalog.adapter_factory.adapter_construction",
        lambda platform: (lambda client: _FakeAdapter(), 0.0),
    )
    _FakeService.calls.clear()
    _FakeService.results_for = {}
    _FakeService.retry_once_for = {}
    return _FakeService


def test_corpus_selection_distinguishes_material(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        hashed = select_corpus(database.connection, "hash-material")
        downloaded = select_corpus(database.connection, "downloaded")
        everything = select_corpus(database.connection, "all")
    assert len(hashed) == 2  # only the md5-bearing posts
    assert downloaded == []  # nothing acquired
    assert len(everything) == 3


def test_budget_stops_at_item_boundary_and_resumes(
    catalog: Path, fake_provider: type[_FakeService]
) -> None:
    from media_catalog.crosscheck import run_crosscheck

    with CatalogDatabase(catalog) as database:
        first = run_crosscheck(
            database,
            corpus="hash-material",
            providers=("danbooru",),
            budget=CrosscheckBudget(max_requests=1),
        )
    assert first["counts"]["pending"] >= 1
    assert first["stopped_reason"] == "request budget reached"

    with CatalogDatabase(catalog) as database:
        second = run_crosscheck(
            database,
            corpus="hash-material",
            providers=("danbooru",),
            budget=CrosscheckBudget(max_requests=10),
        )
    assert second["counts"]["pending"] == 0
    assert second["stopped_reason"] is None
    # terminal items from the first pass are reused, never re-executed
    # only the previously-pending item ran in the resume pass
    assert len(_FakeService.calls) == 2


def test_matches_recorded_as_candidates_never_relationships(
    catalog: Path, fake_provider: type[_FakeService]
) -> None:
    _FakeService.results_for = {
        ("post:1", "verified_md5"): 3,
        ("post:1", "declared_md5"): 3,
        ("post:2", "declared_md5"): 1,
    }
    from media_catalog.crosscheck import run_crosscheck

    with CatalogDatabase(catalog) as database:
        result = run_crosscheck(
            database,
            corpus="hash-material",
            providers=("danbooru",),
            budget=CrosscheckBudget(),
        )
    assert result["counts"]["matched"] >= 1
    connection = sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)
    matched_items = connection.execute(
        "SELECT count(*) FROM crosscheck_items WHERE state = 'matched'"
    ).fetchone()[0]
    pairs = connection.execute("SELECT count(*) FROM pair_labels").fetchone()[0]
    relations = connection.execute("SELECT count(*) FROM relationships").fetchone()[0]
    connection.close()
    assert matched_items >= 1
    assert pairs == 0 and relations == 0


def test_rate_limit_surfaces_as_failed_reason(
    catalog: Path, fake_provider: type[_FakeService]
) -> None:
    _FakeService.retry_once_for = {("post:1", "declared_md5"): "120"}
    from media_catalog.crosscheck import run_crosscheck

    with CatalogDatabase(catalog) as database:
        result = run_crosscheck(
            database,
            corpus="hash-material",
            providers=("danbooru",),
            budget=CrosscheckBudget(),
        )
    assert result["counts"]["failed"] >= 1
    assert any("retry_after=120" in reason for reason in result["summary"]["reasons"])


def _insert_file_seed(connection: sqlite3.Connection, md5: str) -> int:
    session = connection.execute(
        "INSERT INTO discovery_sessions (input_kind, started_at)"
        " VALUES ('local_file', '2026-11-14T00:00:00Z')"
    )
    seed = connection.execute(
        """INSERT INTO discovery_file_seeds
               (discovery_session_id, verified_md5, verified_sha256, byte_size,
                source_path, observed_at)
           VALUES (?, ?, ?, 1, 'seed.bin', '2026-11-14T00:00:00Z')""",
        (int(session.lastrowid), md5, "s" * 64),
    )
    return int(seed.lastrowid)


def test_file_seeds_corpus_selects_canonical_bare_file_seeds(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database, database.transaction():
        first = _insert_file_seed(database.connection, MD5)
        second = _insert_file_seed(database.connection, "f" * 32)
        _insert_file_seed(database.connection, MD5)  # duplicate hash pair, higher id
    with CatalogDatabase(catalog) as database:
        subjects = select_corpus(database.connection, "file-seeds")
    # one canonical subject per verified hash pair: the lowest seed id only
    assert subjects == [("file", first), ("file", second)]


def test_file_seed_subjects_crosscheck_via_verified_md5(
    catalog: Path, fake_provider: type[_FakeService]
) -> None:
    from media_catalog.crosscheck import run_crosscheck

    with CatalogDatabase(catalog) as database, database.transaction():
        seed_id = _insert_file_seed(database.connection, MD5)
    _FakeService.results_for = {(f"file:{seed_id}", "verified_md5"): 2}

    with CatalogDatabase(catalog) as database:
        result = run_crosscheck(
            database,
            corpus="file-seeds",
            providers=("danbooru",),
            budget=CrosscheckBudget(),
        )

    assert result["subjects"] == 1
    # the verified md5 is the only query material a bare file carries
    assert _FakeService.calls == [(f"file:{seed_id}", "verified_md5")]
    connection = sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)
    items = connection.execute(
        "SELECT strategy, state, matched_count FROM crosscheck_items"
        " WHERE seed_kind = 'file' ORDER BY strategy"
    ).fetchall()
    batch_corpus = connection.execute(
        "SELECT corpus FROM crosscheck_batches WHERE crosscheck_batch_id = ?",
        (result["batch_id"],),
    ).fetchone()[0]
    pairs = connection.execute("SELECT count(*) FROM pair_labels").fetchone()[0]
    relations = connection.execute("SELECT count(*) FROM relationships").fetchone()[0]
    connection.close()
    assert batch_corpus == "file-seeds"
    assert [(row[0], row[1], row[2]) for row in items] == [
        ("declared_md5", "skipped", 0),  # no declared material on a bare file
        ("verified_md5", "matched", 2),
    ]
    assert pairs == 0 and relations == 0  # matches stay candidates


def test_corpus_check_widened_by_migration_preserving_batches(tmp_path: Path) -> None:
    from media_catalog.database import available_migrations, current_schema_version

    path = tmp_path / "v34.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        for number, _name, sql in available_migrations()[:34]:
            connection.executescript(sql)
            connection.execute(f"PRAGMA user_version = {number}")
        batch = connection.execute(
            """INSERT INTO crosscheck_batches
                   (batch_key, corpus, providers, recheck, started_at)
               VALUES ('downloaded|danbooru|unsearched', 'downloaded', 'danbooru',
                       'unsearched', '2026-11-01T00:00:00Z')"""
        )
        connection.execute(
            """INSERT INTO crosscheck_items
                   (crosscheck_batch_id, seed_kind, seed_id, provider, strategy,
                    state, updated_at)
               VALUES (?, 'post', 1, 'danbooru', 'verified_md5', 'checked',
                       '2026-11-01T00:00:00Z')""",
            (int(batch.lastrowid),),
        )
        connection.commit()

    with CatalogDatabase(path) as database:
        assert database.schema_version == current_schema_version()
        rows = database.connection.execute(
            "SELECT batch_key, corpus FROM crosscheck_batches ORDER BY crosscheck_batch_id"
        ).fetchall()
        checked = database.connection.execute(
            "SELECT count(*) FROM crosscheck_items WHERE state = 'checked'"
        ).fetchone()[0]
        database.connection.execute(
            """INSERT INTO crosscheck_batches
                   (batch_key, corpus, providers, recheck, started_at)
               VALUES ('file-seeds|danbooru|unsearched', 'file-seeds', 'danbooru',
                       'unsearched', '2026-11-14T00:00:00Z')"""
        )
        next_id = database.connection.execute("SELECT last_insert_rowid()").fetchone()[0]

    # the pre-migration batch and its item survive the rebuild; the widened
    # CHECK admits file-seeds; the AUTOINCREMENT sequence continues past 1
    assert [(row[0], row[1]) for row in rows] == [("downloaded|danbooru|unsearched", "downloaded")]
    assert checked == 1
    assert next_id == 2
