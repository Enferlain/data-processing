from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic, sleep
from types import MappingProxyType

import httpx

from media_catalog.acquisition.policies import (
    CredentialResolver,
    RequestPolicyError,
    RequestRecipe,
    ResolvedCredentials,
    safe_failure_diagnostic,
    validate_redirect,
)
from media_catalog.storage.cas import (
    AssetStorage,
    AssetStorageError,
    RemotePartialState,
    RemoteStagingSession,
    StagedAsset,
)


@dataclass(frozen=True, slots=True)
class TransferLimits:
    max_item_bytes: int
    max_attempts: int
    max_seconds: float
    max_redirects: int
    chunk_size: int = 64 * 1024
    initial_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 5.0

    def __post_init__(self) -> None:
        for name in ("max_item_bytes", "max_attempts", "max_redirects", "chunk_size"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("max_seconds", "initial_backoff_seconds", "max_backoff_seconds"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(slots=True)
class TransferBudget:
    max_bytes: int
    used_bytes: int = 0

    def __post_init__(self) -> None:
        if self.max_bytes <= 0 or self.used_bytes < 0 or self.used_bytes > self.max_bytes:
            raise ValueError("transfer budget must be positive and internally consistent")

    @property
    def remaining_bytes(self) -> int:
        return self.max_bytes - self.used_bytes

    def charge(self, amount: int) -> None:
        if amount < 0:
            raise ValueError("transfer byte charge must not be negative")
        if amount > self.remaining_bytes:
            raise TransferFailure("budget_exhausted", True)
        self.used_bytes += amount


@dataclass(frozen=True, slots=True)
class ResumeState:
    partial: RemotePartialState
    strong_etag: str
    response_size: int | None = None

    def __post_init__(self) -> None:
        if not _strong_etag(self.strong_etag):
            raise ValueError("resume requires a strong ETag")
        if self.response_size is not None and self.response_size < self.partial.byte_count:
            raise ValueError("resume response size is smaller than the partial")


@dataclass(frozen=True, slots=True)
class AttemptTransition:
    attempt_number: int
    state: str
    outcome: str | None
    retryable: bool
    request_identity: str
    status_code: int | None
    redirect_count: int
    received_bytes: int
    response_size: int | None
    response_etag: str | None
    retry_after_seconds: float | None
    diagnostic: str | None


AttemptObserver = Callable[[AttemptTransition], None]
PartialObserver = Callable[[int, ResumeState], None]


@dataclass(frozen=True, slots=True)
class TransferResult:
    state: str
    outcome: str
    retryable: bool
    attempts: tuple[AttemptTransition, ...]
    received_bytes: int
    staged: StagedAsset | None = field(default=None, repr=False)
    resume: ResumeState | None = field(default=None, repr=False)
    status_code: int | None = None
    diagnostic: str | None = None

    @property
    def complete(self) -> bool:
        return self.state == "complete"

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "outcome": self.outcome,
            "retryable": self.retryable,
            "attempt_count": len(self.attempts),
            "received_bytes": self.received_bytes,
            "status_code": self.status_code,
            "diagnostic": self.diagnostic,
            "has_staged_asset": self.staged is not None,
            "has_resumable_partial": self.resume is not None,
        }


class TransferFailure(Exception):
    def __init__(self, outcome: str, retryable: bool) -> None:
        self.outcome = outcome
        self.retryable = retryable
        super().__init__(outcome)


_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+|\*)$")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _strong_etag(value: str | None) -> bool:
    return bool(
        value
        and not value.startswith("W/")
        and len(value) >= 2
        and value.startswith('"')
        and value.endswith('"')
    )


def _content_length(response: httpx.Response) -> int | None:
    value = response.headers.get("Content-Length")
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError as error:
        raise TransferFailure("invalid_content", False) from error
    if parsed < 0:
        raise TransferFailure("invalid_content", False)
    return parsed


def _resume_response_size(response: httpx.Response, offset: int) -> int:
    match = _CONTENT_RANGE.fullmatch(response.headers.get("Content-Range", ""))
    if match is None:
        raise TransferFailure("source_changed", False)
    start, end = int(match[1]), int(match[2])
    if start != offset or end < start or match[3] == "*":
        raise TransferFailure("source_changed", False)
    total = int(match[3])
    if total != end + 1:
        raise TransferFailure("source_changed", False)
    length = _content_length(response)
    if length is not None and length != end - start + 1:
        raise TransferFailure("source_changed", False)
    return total


def _retry_after_seconds(
    value: str | None,
    *,
    wall_now: Callable[[], datetime],
) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(int(value))
    except ValueError:
        try:
            moment = parsedate_to_datetime(value)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            seconds = (moment - wall_now()).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, seconds)


def _credential_headers(
    recipe: RequestRecipe,
    resolver: CredentialResolver | None,
) -> Mapping[str, str]:
    headers = dict(recipe.headers)
    reference = recipe.credential_reference
    if reference is None:
        return MappingProxyType(headers)
    if resolver is None:
        raise TransferFailure("authentication_required", False)
    try:
        credentials = resolver(reference)
    except Exception as error:
        raise TransferFailure("authentication_required", False) from error
    if not isinstance(credentials, ResolvedCredentials):
        raise TransferFailure("authentication_required", False)
    for name, value in credentials.headers.items():
        headers[name] = value
    if credentials.cookies:
        headers["Cookie"] = "; ".join(
            f"{name}={value}" for name, value in credentials.cookies.items()
        )
    return MappingProxyType(headers)


class HTTPTransferEngine:
    """Bounded synchronous media transfer with injected transport and time."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        clock: Callable[[], float] = monotonic,
        wall_now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleeper: Callable[[float], None] = sleep,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self.client = client
        self.clock = clock
        self.wall_now = wall_now
        self.sleeper = sleeper
        self.cancelled = cancelled

    def transfer(
        self,
        recipe: RequestRecipe,
        storage: AssetStorage,
        *,
        limits: TransferLimits,
        budget: TransferBudget,
        resume: ResumeState | None = None,
        credential_resolver: CredentialResolver | None = None,
        observer: AttemptObserver | None = None,
        partial_observer: PartialObserver | None = None,
    ) -> TransferResult:
        started = self.clock()
        deadline = started + limits.max_seconds
        transitions: list[AttemptTransition] = []
        received_total = 0
        current_resume = resume
        last_status: int | None = None

        for attempt_number in range(1, limits.max_attempts + 1):
            running = AttemptTransition(
                attempt_number,
                "running",
                None,
                False,
                recipe.request_identity,
                None,
                0,
                0,
                current_resume.response_size if current_resume else None,
                current_resume.strong_etag if current_resume else None,
                None,
                None,
            )
            if observer:
                observer(running)

            session: RemoteStagingSession | None = None
            response: httpx.Response | None = None
            redirects = 0
            attempt_bytes = 0
            response_size: int | None = None
            response_etag: str | None = None
            retry_after: float | None = None
            outcome = "transient_provider"
            retryable = True
            state = "failed"
            active_resume: ResumeState | None = None
            try:
                self._check_control(deadline)
                session, active_resume = self._open_session(
                    storage, recipe, limits, current_resume
                )
                headers = dict(_credential_headers(recipe, credential_resolver))
                if active_resume is not None:
                    headers["Range"] = f"bytes={active_resume.partial.byte_count}-"
                    headers["If-Range"] = active_resume.strong_etag

                response, redirects = self._request(
                    recipe, headers, limits.max_redirects, deadline
                )
                last_status = response.status_code
                response_etag = response.headers.get("ETag")
                retry_after = _retry_after_seconds(
                    response.headers.get("Retry-After"), wall_now=self.wall_now
                )

                classification = self._classify(recipe, response.status_code)
                if classification[0] != "success":
                    raise TransferFailure(classification[0], classification[1])

                if active_resume is not None:
                    if response.status_code == 206:
                        if response_etag != active_resume.strong_etag:
                            raise TransferFailure("source_changed", False)
                        response_size = _resume_response_size(
                            response, active_resume.partial.byte_count
                        )
                        if (
                            active_resume.response_size is not None
                            and active_resume.response_size != response_size
                        ):
                            raise TransferFailure("source_changed", False)
                    elif response.status_code == 200:
                        self._discard_session(storage, session)
                        session = storage.begin_remote_staging(
                            recipe.request_identity, max_bytes=limits.max_item_bytes
                        )
                        active_resume = None
                        response_size = _content_length(response)
                    else:
                        raise TransferFailure("source_changed", False)
                else:
                    if response.status_code != 200:
                        raise TransferFailure("invalid_content", False)
                    response_size = _content_length(response)

                if not recipe.response.accepts(response.headers.get("Content-Type")):
                    raise TransferFailure("invalid_content", False)
                assert session is not None
                if response_size is not None:
                    remaining = response_size - session.size
                    if response.status_code == 200:
                        remaining = response_size
                    if remaining < 0 or session.size + remaining > limits.max_item_bytes:
                        raise TransferFailure("response_too_large", False)
                    if remaining > budget.remaining_bytes:
                        raise TransferFailure("budget_exhausted", True)

                declared_length = _content_length(response)
                for chunk in response.iter_bytes(chunk_size=limits.chunk_size):
                    self._check_control(deadline)
                    budget.charge(len(chunk))
                    session.write(chunk)
                    attempt_bytes += len(chunk)
                    received_total += len(chunk)
                if declared_length is not None and attempt_bytes != declared_length:
                    raise TransferFailure("source_changed", True)
                if response_size is not None and session.size != response_size:
                    raise TransferFailure("source_changed", True)
                staged = session.finalize(source_label=f"remote:{recipe.provider}")
                session = None
                terminal = self._transition(
                    running,
                    state="complete",
                    outcome="downloaded",
                    retryable=False,
                    status_code=response.status_code,
                    redirects=redirects,
                    received=attempt_bytes,
                    response_size=response_size,
                    etag=response_etag,
                    retry_after=retry_after,
                    provider=recipe.provider,
                )
                transitions.append(terminal)
                if observer:
                    observer(terminal)
                return TransferResult(
                    "complete",
                    "downloaded",
                    False,
                    tuple(transitions),
                    received_total,
                    staged=staged,
                    status_code=response.status_code,
                )
            except TransferFailure as error:
                outcome, retryable = error.outcome, error.retryable
            except httpx.TimeoutException:
                outcome, retryable = "timeout", True
            except httpx.TransportError:
                outcome, retryable = "transient_provider", True
            except RequestPolicyError:
                outcome, retryable = "policy_failure", False
            except AssetStorageError as error:
                outcome = getattr(error, "category", "storage_failure")
                retryable = False
            except OSError:
                outcome, retryable = "storage_failure", False
            finally:
                if response is not None:
                    response.close()

            resumable: ResumeState | None = None
            if session is not None:
                partial_etag = response_etag
                partial_size = response_size
                if active_resume is not None and not _strong_etag(partial_etag):
                    partial_etag = active_resume.strong_etag
                    partial_size = active_resume.response_size
                if retryable and session.size > 0 and _strong_etag(partial_etag):
                    partial = session.detach()
                    session = None
                    assert partial_etag is not None
                    resumable = ResumeState(partial, partial_etag, partial_size)
                    if partial_observer:
                        partial_observer(attempt_number, resumable)
                else:
                    self._discard_session(storage, session)
                    session = None
            current_resume = resumable
            if self.cancelled():
                outcome, retryable, state = "cancelled", True, "interrupted"
            elif self.clock() >= deadline:
                outcome, retryable, state = "timeout", True, "interrupted"
            elif outcome in {
                "transient_provider",
                "timeout",
                "rate_limited",
                "source_changed",
                "budget_exhausted",
            }:
                state = "interrupted" if resumable is not None else "failed"
            terminal = self._transition(
                running,
                state=state,
                outcome=outcome,
                retryable=retryable,
                status_code=last_status,
                redirects=redirects,
                received=attempt_bytes,
                response_size=response_size,
                etag=response_etag,
                retry_after=retry_after,
                provider=recipe.provider,
            )
            transitions.append(terminal)
            if observer:
                observer(terminal)

            can_retry = (
                retryable
                and outcome != "budget_exhausted"
                and attempt_number < limits.max_attempts
                and not self.cancelled()
                and self.clock() < deadline
            )
            if not can_retry:
                return TransferResult(
                    state,
                    outcome,
                    retryable,
                    tuple(transitions),
                    received_total,
                    resume=resumable,
                    status_code=last_status,
                    diagnostic=terminal.diagnostic,
                )
            delay = retry_after
            if delay is None:
                delay = min(
                    limits.initial_backoff_seconds * (2 ** (attempt_number - 1)),
                    limits.max_backoff_seconds,
                )
            if self.clock() + delay >= deadline:
                return TransferResult(
                    state,
                    "timeout",
                    True,
                    tuple(transitions),
                    received_total,
                    resume=resumable,
                    status_code=last_status,
                    diagnostic=safe_failure_diagnostic(recipe.provider, "timeout"),
                )
            self.sleeper(delay)

        raise AssertionError("positive attempt limit should always return")

    @staticmethod
    def _classify(recipe: RequestRecipe, status_code: int) -> tuple[str, bool]:
        classification = recipe.classify_status(status_code)
        return classification.category, classification.retryable

    def _request(
        self,
        recipe: RequestRecipe,
        headers: Mapping[str, str],
        max_redirects: int,
        deadline: float,
    ) -> tuple[httpx.Response, int]:
        url = recipe.url
        redirects = 0
        while True:
            self._check_control(deadline)
            request = self.client.build_request(recipe.method, url, headers=headers)
            response = self.client.send(request, stream=True, follow_redirects=False)
            if response.status_code not in _REDIRECT_STATUSES:
                return response, redirects
            location = response.headers.get("Location")
            response.close()
            if redirects >= max_redirects:
                raise TransferFailure("policy_failure", False)
            if not recipe.redirect_hosts:
                raise TransferFailure("policy_failure", False)
            try:
                url = validate_redirect(
                    str(request.url),
                    location or "",
                    allowed_hosts=recipe.redirect_hosts,
                )
            except RequestPolicyError as error:
                raise TransferFailure("policy_failure", False) from error
            redirects += 1

    def _open_session(
        self,
        storage: AssetStorage,
        recipe: RequestRecipe,
        limits: TransferLimits,
        resume: ResumeState | None,
    ) -> tuple[RemoteStagingSession, ResumeState | None]:
        if resume is None:
            return (
                storage.begin_remote_staging(
                    recipe.request_identity, max_bytes=limits.max_item_bytes
                ),
                None,
            )
        if resume.partial.request_identity != recipe.request_identity:
            old = storage.reopen_remote_staging(
                resume.partial,
                expected_request_identity=resume.partial.request_identity,
                max_bytes=limits.max_item_bytes,
            )
            self._discard_session(storage, old)
            return (
                storage.begin_remote_staging(
                    recipe.request_identity, max_bytes=limits.max_item_bytes
                ),
                None,
            )
        return (
            storage.reopen_remote_staging(
                resume.partial,
                expected_request_identity=recipe.request_identity,
                max_bytes=limits.max_item_bytes,
            ),
            resume,
        )

    @staticmethod
    def _discard_session(storage: AssetStorage, session: RemoteStagingSession) -> None:
        staged = session.finalize(source_label="remote:discarded")
        storage.cleanup_staging(staged)

    def _check_control(self, deadline: float) -> None:
        if self.cancelled():
            raise TransferFailure("cancelled", True)
        if self.clock() >= deadline:
            raise TransferFailure("timeout", True)

    @staticmethod
    def _transition(
        running: AttemptTransition,
        *,
        state: str,
        outcome: str,
        retryable: bool,
        status_code: int | None,
        redirects: int,
        received: int,
        response_size: int | None,
        etag: str | None,
        retry_after: float | None,
        provider: str,
    ) -> AttemptTransition:
        return AttemptTransition(
            running.attempt_number,
            state,
            outcome,
            retryable,
            running.request_identity,
            status_code,
            redirects,
            received,
            response_size,
            etag,
            retry_after,
            safe_failure_diagnostic(provider, outcome) if state != "complete" else None,
        )
