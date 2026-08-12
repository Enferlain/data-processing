from __future__ import annotations

import pytest

from media_catalog.adapters import (
    AdapterOperation,
    AdapterRequest,
    Continuation,
    NormalizedItem,
    NormalizedPage,
    ResponseEnvelope,
)
from media_catalog.database import CatalogDatabase
from media_catalog.remote_sync import (
    BoundedRemoteExecutor,
    BudgetExhausted,
    MetadataSyncService,
    RetainedPage,
    SyncLimits,
)

NOW = "2026-08-10T00:00:00Z"


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, delay: float) -> None:
        self.value += delay


class _Adapter:
    provider_key = "pixiv"
    instance_key = "pixiv"
    adapter_version = "adapter-v1"
    schema_version = "schema-v1"

    def __init__(self, responses: list[ResponseEnvelope], pages: list[NormalizedPage]) -> None:
        self.responses = iter(responses)
        self.pages = iter(pages)
        self.requests: list[AdapterRequest] = []
        self.normalized = 0

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        self.requests.append(request)
        return next(self.responses)

    def normalize(self, _response: ResponseEnvelope) -> NormalizedPage:
        self.normalized += 1
        return next(self.pages)


def _response(status_code: int, identity: str) -> ResponseEnvelope:
    return ResponseEnvelope(
        provider="pixiv",
        instance="pixiv",
        operation=AdapterOperation.LIST_ACCOUNT_POSTS,
        request_identity=identity,
        status_code=status_code,
        headers={"retry-after": "0"},
        payload=b"{}",
        observed_at=NOW,
        adapter_version="adapter-v1",
        schema_version="schema-v1",
    )


def _page(*native_ids: str, continuation: Continuation | None = None) -> NormalizedPage:
    return NormalizedPage(
        tuple(
            NormalizedItem(
                "post",
                native_id,
                {"platform": "pixiv", "native_id": native_id},
            )
            for native_id in native_ids
        ),
        continuation,
    )


def _executor(
    adapter: _Adapter,
    *,
    limits: SyncLimits,
    retained: list[tuple[int, int]],
    committed: list[RetainedPage],
    clock: _Clock,
) -> BoundedRemoteExecutor:
    return BoundedRemoteExecutor(
        adapter,
        AdapterOperation.LIST_ACCOUNT_POSTS,
        "account-1",
        limits=limits,
        retain_response=lambda response, attempt: (
            retained.append((response.status_code, attempt)) or len(retained)
        ),
        commit_page=lambda page, budget: (
            committed.append(page) or budget.commit_page(page.page.record_count)
        ),
        minimum_interval_seconds=0,
        maximum_retries=2,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


def test_response_retention_precedes_normalization_and_retries_are_retained() -> None:
    clock = _Clock()
    adapter = _Adapter(
        [_response(429, "retry"), _response(200, "success")],
        [_page("10")],
    )
    retained: list[tuple[int, int]] = []
    committed: list[RetainedPage] = []

    result = _executor(
        adapter,
        limits=SyncLimits(2, 1, 1, 10),
        retained=retained,
        committed=committed,
        clock=clock,
    ).execute()

    assert retained == [(429, 1), (200, 2)]
    assert adapter.normalized == 1
    assert len(committed) == 1
    assert result.budget.requests == 2


def test_metadata_sync_retry_retention_and_result_json_remain_observable(tmp_path) -> None:
    clock = _Clock()
    adapter = _Adapter(
        [_response(429, "retry"), _response(200, "success")],
        [_page("10")],
    )
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        result = MetadataSyncService(
            database,
            adapter,
            minimum_interval_seconds=0,
            maximum_retries=2,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            clock=lambda: NOW,
        ).synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "account-1",
            limits=SyncLimits(2, 1, 1, 10),
        )

        assert result.status == "complete"
        assert (result.request_count, result.page_count, result.record_count) == (2, 1, 1)
        assert set(result.as_dict()) == {
            "remote_run_id",
            "platform",
            "operation",
            "target",
            "status",
            "outcome",
            "request_count",
            "page_count",
            "record_count",
            "resumed_from_run_id",
            "budget_boundary",
            "retry_after",
            "diagnostic",
        }
        assert database.connection.execute(
            "SELECT COUNT(*) FROM remote_requests"
        ).fetchone()[0] == 2
        assert database.connection.execute(
            "SELECT COUNT(*) FROM raw_observations"
        ).fetchone()[0] == 2


def test_whole_page_admission_happens_before_page_commit() -> None:
    clock = _Clock()
    adapter = _Adapter([_response(200, "oversized")], [_page("10", "11")])
    retained: list[tuple[int, int]] = []
    committed: list[RetainedPage] = []
    executor = _executor(
        adapter,
        limits=SyncLimits(1, 1, 1, 10),
        retained=retained,
        committed=committed,
        clock=clock,
    )

    with pytest.raises(BudgetExhausted, match="record budget"):
        executor.execute()

    assert retained == [(200, 1)]
    assert committed == []
    assert executor.budget.pages == 0
    assert executor.budget.records == 0


def test_continuation_is_looped_only_after_a_committed_page() -> None:
    clock = _Clock()
    continuation = Continuation("fixture", "schema-v1", {"offset": 1})
    adapter = _Adapter(
        [_response(200, "first"), _response(200, "second")],
        [_page("10", continuation=continuation), _page("11")],
    )
    retained: list[tuple[int, int]] = []
    committed: list[RetainedPage] = []

    result = _executor(
        adapter,
        limits=SyncLimits(2, 2, 2, 10),
        retained=retained,
        committed=committed,
        clock=clock,
    ).execute()

    assert [request.continuation for request in adapter.requests] == [None, continuation]
    assert [page.page.record_count for page in committed] == [1, 1]
    assert result.continuation is None
    assert (result.budget.pages, result.budget.records) == (2, 2)
