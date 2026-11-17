"""Provider lanes (bead data-processing-jq1, change add-crosscheck-provider-lanes):
lanes overlap network waits, items record exactly once, budgets stop across
lanes, and per-lane sequencing preserves behavior."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import ClassVar

import pytest

from media_catalog.adapters.contracts import (
    LookupCapabilities,
    LookupPlanContext,
    LookupStrategy,
)
from media_catalog.crosscheck import CrosscheckBudget, run_crosscheck
from media_catalog.database import CatalogDatabase

MD5 = "0123456789abcdef0123456789abcdef"


class _FakeResult:
    def __init__(self) -> None:
        self.candidate_lookup_run_id = 0
        self.provider = "danbooru"
        self.strategy = "verified_md5"
        self.status = "complete"
        self.outcome = "success"
        self.request_count = 1
        self.result_count = 0
        self.retry_after = None
        self.budget_boundary = None
        self.diagnostic = None


class _FakeAdapter:
    instance_key = "danbooru"
    adapter_version = "fake-adapter-v1"
    schema_version = "fake-schema-v1"

    def __init__(self) -> None:
        self.instance = self
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


class _LaneFakeService:
    calls: ClassVar[list[tuple[str, str]]] = []
    threads_seen: ClassVar[set[int]] = set()
    barrier: ClassVar[threading.Barrier | None] = None

    def __init__(self, database, adapter, minimum_interval_seconds: float = 0.0):
        type(self).threads_seen.add(threading.get_ident())
        barrier = type(self).barrier
        if barrier is not None:
            barrier.wait()

    def plan(self, seed, strategies, *, limits=None, search_term=None):
        class _Plan:
            def __init__(self, seed_, strategies_):
                self.seed = seed_
                self.strategies = strategies_

        return _Plan(seed, strategies)

    def execute(self, plan):
        return tuple(self._one(plan.seed, strategy.value) for strategy in plan.strategies)

    def _one(self, seed: str, strategy: str) -> _FakeResult:
        type(self).calls.append((seed, strategy))
        return _FakeResult()


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database, database.transaction():
        platform = database.connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'gelbooru'"
        ).fetchone()
        assert platform is not None
        platform_id = int(platform["platform_id"])
        for native, md5 in (("lc-1", MD5), ("lc-2", "f" * 32)):
            post = database.connection.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform_id, native),
            )
            database.connection.execute(
                """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                                      media_type, declared_md5, observed_at)
                   VALUES (?, 'lc:p', 0, 'image/png', ?, '2026-01-01T00:00:00Z')""",
                (int(post.lastrowid), md5),
            )
    return path


@pytest.fixture()
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> type[_LaneFakeService]:
    import media_catalog.crosscheck as crosscheck_module

    monkeypatch.setattr(crosscheck_module, "CandidateLookupService", _LaneFakeService)
    monkeypatch.setattr(
        "media_catalog.adapter_factory.adapter_construction",
        lambda platform: (lambda client: _FakeAdapter(), 0.0),
    )
    _LaneFakeService.calls.clear()
    _LaneFakeService.threads_seen.clear()
    _LaneFakeService.barrier = None
    return _LaneFakeService


def test_lanes_overlap_and_items_record_exactly_once(
    catalog: Path, fake_provider: type[_LaneFakeService]
) -> None:
    # the barrier only opens when the second provider's lane constructs its
    # service concurrently — a sequential implementation times out here
    _LaneFakeService.barrier = threading.Barrier(2, timeout=10)
    with CatalogDatabase(catalog) as database:
        result = run_crosscheck(
            database,
            corpus="hash-material",
            providers=("danbooru", "aibooru"),
            budget=CrosscheckBudget(),
        )
    assert len(_LaneFakeService.threads_seen) == 2
    connection = sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT provider, count(*) FROM crosscheck_items"
        " WHERE state IN ('checked', 'matched') GROUP BY 1"
    ).fetchall()
    connection.close()
    providers = {row[0] for row in rows}
    assert providers == {"danbooru", "aibooru"}
    assert sum(row[1] for row in rows) == len(_LaneFakeService.calls)
    assert result["subjects"] == 2


def test_shared_budget_stops_across_lanes(
    catalog: Path, fake_provider: type[_LaneFakeService]
) -> None:
    with CatalogDatabase(catalog) as database:
        result = run_crosscheck(
            database,
            corpus="hash-material",
            providers=("danbooru", "aibooru"),
            budget=CrosscheckBudget(max_requests=1),
        )
    assert result["stopped_reason"] == "request budget reached"
    assert result["requests_used"] >= 1
    assert result["counts"]["pending"] >= 1
