from __future__ import annotations

import pytest

from media_catalog.adapters import (
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    ResponseEnvelope,
)
from media_catalog.remote_sync import (
    BudgetTracker,
    EnvironmentCredentialResolver,
    RequestGate,
    SyncLimits,
    sanitize_transport_error,
    semantic_request_identity,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.value += delay


def _response(status: int, headers=None) -> ResponseEnvelope:
    return ResponseEnvelope(
        provider="danbooru",
        instance="danbooru",
        operation=AdapterOperation.FETCH_POST,
        request_identity=f"danbooru:fetch_post:1:{status}",
        status_code=status,
        headers=headers or {},
        payload=b"{}",
        observed_at="2026-08-10T00:00:00Z",
        adapter_version="v1",
        schema_version="v1",
    )


def test_budgets_are_positive_and_pages_are_admitted_atomically() -> None:
    with pytest.raises(ValueError, match="positive"):
        SyncLimits(0, 1, 1, 1)
    clock = FakeClock()
    tracker = BudgetTracker(SyncLimits(2, 1, 2, 10), monotonic=clock.monotonic)
    tracker.reserve_request()
    tracker.commit_page(2)
    assert (tracker.requests, tracker.pages, tracker.records) == (1, 1, 2)
    with pytest.raises(AdapterFailure) as error:
        tracker.admit_page(1)
    assert error.value.outcome is AdapterOutcome.BUDGET_EXHAUSTED
    assert (tracker.pages, tracker.records) == (1, 2)


def test_request_gate_retains_every_attempt_and_bounds_rate_limit_retries() -> None:
    clock = FakeClock()
    tracker = BudgetTracker(SyncLimits(3, 1, 1, 20), monotonic=clock.monotonic)
    gate = RequestGate(
        tracker,
        minimum_interval_seconds=0.5,
        maximum_retries=2,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    responses = iter((_response(429, {"retry-after": "2"}), _response(200)))
    retained: list[int] = []
    result = gate.execute(
        lambda: next(responses),
        lambda response: retained.append(response.status_code),
    )
    assert result.status_code == 200
    assert retained == [429, 200]
    assert tracker.requests == 2
    assert clock.sleeps == [2.0]


def test_request_gate_does_not_retry_past_request_or_time_budget() -> None:
    clock = FakeClock()
    tracker = BudgetTracker(SyncLimits(1, 1, 1, 1), monotonic=clock.monotonic)
    gate = RequestGate(
        tracker,
        minimum_interval_seconds=0,
        maximum_retries=5,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    retained: list[int] = []
    result = gate.execute(
        lambda: _response(429, {"retry-after": "10"}),
        lambda response: retained.append(response.status_code),
    )
    assert result.status_code == 429
    assert retained == [429]
    assert tracker.requests == 1
    assert clock.sleeps == []


def test_semantic_request_identity_rejects_secret_parameters() -> None:
    identity = semantic_request_identity(
        "pixiv", "fetch_post", "123", "illust_detail", {"lang": "en"}
    )
    assert identity == "pixiv:fetch_post:123:illust_detail:lang=en"
    with pytest.raises(ValueError, match="secret parameter"):
        semantic_request_identity(
            "pixiv", "fetch_post", "123", "illust_detail", {"refresh_token": "sentinel"}
        )


def test_credentials_and_transport_errors_never_render_secret_values() -> None:
    resolver = EnvironmentCredentialResolver({"PIXIV_REFRESH_TOKEN": "sentinel-secret"})
    secret = resolver.resolve("PIXIV_REFRESH_TOKEN")
    assert secret is not None
    assert str(secret) == "<redacted>"
    assert "sentinel-secret" not in repr(secret)

    error = sanitize_transport_error(
        RuntimeError("request https://example.test?api_key=sentinel-secret failed"), "pixiv"
    )
    assert error.outcome is AdapterOutcome.TRANSIENT_PROVIDER
    assert "sentinel-secret" not in str(error)
    assert "api_key" not in str(error)


def test_missing_required_credential_fails_before_transport() -> None:
    resolver = EnvironmentCredentialResolver({})
    with pytest.raises(ValueError, match="PIXIV_REFRESH_TOKEN"):
        resolver.resolve("PIXIV_REFRESH_TOKEN")
