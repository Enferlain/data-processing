"""Reusable bounded remote request and page-loop orchestration.

The executor owns only request pacing/retries, budget admission, response-to-page
ordering, and continuation looping.  Persistence remains a callback so metadata
synchronization and future lookup runs can keep separate tables and transactions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from media_catalog.adapters import (
    Adapter,
    AdapterOperation,
    AdapterRequest,
    Continuation,
    ResponseEnvelope,
)

from .budget import BudgetTracker, SyncLimits
from .request_gate import RequestGate


@dataclass(frozen=True, slots=True)
class RetainedPage:
    """A normalized page paired with its response and retained raw observation."""

    request: object
    response: ResponseEnvelope
    page: Any
    raw_observation_id: int


class ResponseRetainer(Protocol):
    """Callback that durably retains one response and returns its observation ID.

    The attempt number is the request count *after* the request gate reserves the
    request.  Consequently retries are retained as distinct attempts before any
    normalization or page commit occurs.
    """

    def __call__(self, response: ResponseEnvelope, attempt: int) -> int: ...


class PageCommitter(Protocol):
    """Callback that atomically commits one admitted page and its continuation."""

    def __call__(self, page: RetainedPage, budget: BudgetTracker) -> None: ...


@dataclass(frozen=True, slots=True)
class RemoteExecutionResult:
    """State produced after all pages accepted by a bounded execution."""

    budget: BudgetTracker
    continuation: object | None


class BoundedRemoteExecutor:
    """Run finite adapter requests while leaving persistence to supplied callbacks.

    ``commit_page`` is called only after response retention, normalization, and
    whole-page budget admission.  The callback owns its transaction and should
    advance the budget and persist a checkpoint only after normalized data is ready.
    """

    def __init__(
        self,
        adapter: Adapter,
        operation: AdapterOperation,
        target: str,
        *,
        limits: SyncLimits,
        retain_response: ResponseRetainer,
        commit_page: PageCommitter,
        continuation: Continuation | None = None,
        continue_pages: Callable[[object, Any], bool] | None = None,
        request_factory: Callable[[object | None], object] | None = None,
        fetch_page: Callable[[object], ResponseEnvelope] | None = None,
        normalize_page: Callable[[ResponseEnvelope, object], Any] | None = None,
        minimum_interval_seconds: float = 1.0,
        maximum_retries: int = 2,
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self.adapter = adapter
        self.operation = operation
        self.target = target
        self.initial_continuation = continuation
        self.retain_response = retain_response
        self.commit_page = commit_page
        self.continue_pages = continue_pages or _continue_metadata_pages
        self.request_factory = request_factory or (
            lambda current: AdapterRequest(self.operation, self.target, current)
        )
        self.fetch_page = fetch_page or (lambda request: self.adapter.fetch(request))
        self.normalize_page = normalize_page or (
            lambda response, _request: self.adapter.normalize(response)
        )
        self.budget = BudgetTracker(limits, monotonic=monotonic)
        self.gate = RequestGate(
            self.budget,
            minimum_interval_seconds=minimum_interval_seconds,
            maximum_retries=maximum_retries,
            monotonic=monotonic,
            sleep=sleep,
        )

    def execute(self) -> RemoteExecutionResult:
        continuation = self.initial_continuation
        while True:
            request = self.request_factory(continuation)
            captured: list[tuple[ResponseEnvelope, int]] = []

            def retain(
                response: ResponseEnvelope,
                captured_responses: list[tuple[ResponseEnvelope, int]] = captured,
            ) -> None:
                raw_id = self.retain_response(response, self.budget.requests)
                captured_responses.append((response, raw_id))

            response = self.gate.execute(
                lambda current_request=request: self.fetch_page(current_request), retain
            )
            raw_id = next(
                raw_id for retained, raw_id in reversed(captured) if retained is response
            )
            page = self.normalize_page(response, request)
            self.budget.admit_page(page.record_count)
            self.commit_page(
                RetainedPage(
                    request=request,
                    response=response,
                    page=page,
                    raw_observation_id=raw_id,
                ),
                self.budget,
            )
            continuation = page.continuation
            if continuation is None or not self.continue_pages(request, page):
                return RemoteExecutionResult(self.budget, continuation)


def _continue_metadata_pages(_request: object, _page: Any) -> bool:
    """Metadata sync follows continuations only for account-post listings."""

    return (
        isinstance(_request, AdapterRequest)
        and _request.operation is AdapterOperation.LIST_ACCOUNT_POSTS
    )
