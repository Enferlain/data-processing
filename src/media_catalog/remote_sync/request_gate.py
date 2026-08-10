from __future__ import annotations

from collections.abc import Callable, Mapping

from media_catalog.adapters import AdapterFailure, AdapterOutcome, ResponseEnvelope

from .budget import BudgetExhausted, BudgetTracker

SECRET_PARAMETER_NAMES = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "refresh_token",
    "token",
}


def semantic_request_identity(
    provider: str,
    operation: str,
    target: str,
    endpoint_name: str,
    parameters: Mapping[str, object] | None = None,
) -> str:
    parts = [provider.strip(), operation.strip(), target.strip(), endpoint_name.strip()]
    if not all(parts):
        raise ValueError("semantic request identity components must not be empty")
    public: list[str] = []
    for name, value in sorted((parameters or {}).items()):
        if name.casefold() in SECRET_PARAMETER_NAMES:
            raise ValueError(f"secret parameter is not allowed in request identity: {name}")
        public.append(f"{name}={value}")
    suffix = ":" + "&".join(public) if public else ""
    return ":".join(parts) + suffix


def sanitize_transport_error(error: BaseException, provider: str) -> AdapterFailure:
    error_kind = type(error).__name__[:100]
    return AdapterFailure(
        AdapterOutcome.TRANSIENT_PROVIDER,
        f"{provider} metadata request failed ({error_kind})",
    )


class RequestGate:
    def __init__(
        self,
        budget: BudgetTracker,
        *,
        minimum_interval_seconds: float,
        maximum_retries: int,
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        if minimum_interval_seconds < 0 or maximum_retries < 0:
            raise ValueError("request interval and retry count must not be negative")
        self.budget = budget
        self.minimum_interval_seconds = minimum_interval_seconds
        self.maximum_retries = maximum_retries
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_request_at: float | None = None

    def execute(
        self,
        fetch: Callable[[], ResponseEnvelope],
        retain: Callable[[ResponseEnvelope], None],
    ) -> ResponseEnvelope:
        retries = 0
        while True:
            self._pace()
            self.budget.reserve_request()
            self._last_request_at = self._monotonic()
            try:
                response = fetch()
            except AdapterFailure:
                raise
            except BaseException as error:
                raise sanitize_transport_error(error, "provider") from None
            retain(response)
            delay = self._retry_delay(response)
            if delay is None or retries >= self.maximum_retries or not self.budget.can_request:
                return response
            if delay >= self.budget.remaining_seconds:
                return response
            self._sleep(delay)
            retries += 1

    def _pace(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._monotonic() - self._last_request_at
        delay = max(0.0, self.minimum_interval_seconds - elapsed)
        if delay:
            if delay >= self.budget.remaining_seconds:
                raise BudgetExhausted("time")
            self._sleep(delay)

    @staticmethod
    def _retry_delay(response: ResponseEnvelope) -> float | None:
        if response.status_code != 429 and response.status_code < 500:
            return None
        value = response.headers.get("retry-after")
        if value is not None:
            try:
                return max(0.0, float(value))
            except ValueError:
                pass
        return 1.0
