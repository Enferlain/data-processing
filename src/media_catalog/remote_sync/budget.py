from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from media_catalog.adapters import AdapterFailure, AdapterOutcome


class BudgetExhausted(AdapterFailure):
    def __init__(self, boundary: str) -> None:
        self.boundary = boundary
        super().__init__(
            AdapterOutcome.BUDGET_EXHAUSTED,
            f"remote synchronization {boundary} budget exhausted",
        )


@dataclass(frozen=True, slots=True)
class SyncLimits:
    requests: int
    pages: int
    records: int
    elapsed_seconds: float

    def __post_init__(self) -> None:
        if self.requests <= 0 or self.pages <= 0 or self.records <= 0:
            raise ValueError("request, page, and record budgets must be positive")
        if self.elapsed_seconds <= 0:
            raise ValueError("elapsed-time budget must be positive")


class BudgetTracker:
    def __init__(
        self,
        limits: SyncLimits,
        *,
        monotonic: Callable[[], float],
    ) -> None:
        self.limits = limits
        self._monotonic = monotonic
        self.started_at = monotonic()
        self.requests = 0
        self.pages = 0
        self.records = 0

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self._monotonic() - self.started_at)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.limits.elapsed_seconds - self.elapsed_seconds)

    @property
    def can_request(self) -> bool:
        return self.requests < self.limits.requests and self.remaining_seconds > 0

    def reserve_request(self) -> None:
        if self.remaining_seconds <= 0:
            self._exhausted("time")
        if self.requests >= self.limits.requests:
            self._exhausted("request")
        self.requests += 1

    def admit_page(self, record_count: int) -> None:
        if record_count < 0:
            raise ValueError("record count must not be negative")
        if self.remaining_seconds <= 0:
            self._exhausted("time")
        if self.pages >= self.limits.pages:
            self._exhausted("page")
        if self.records + record_count > self.limits.records:
            self._exhausted("record")

    def commit_page(self, record_count: int) -> None:
        self.admit_page(record_count)
        self.pages += 1
        self.records += record_count

    @staticmethod
    def _exhausted(boundary: str) -> None:
        raise BudgetExhausted(boundary)
