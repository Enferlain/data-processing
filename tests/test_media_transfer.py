from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from media_catalog.acquisition.policies import PIXIV_MEDIA_POLICY
from media_catalog.acquisition.transfer import (
    AttemptTransition,
    HTTPTransferEngine,
    ResumeState,
    TransferBudget,
    TransferLimits,
)
from media_catalog.storage.cas import AssetStorage, InspectionLimits


def _recipe(url: str = "https://i.pximg.net/file.jpg?signature=secret"):
    return PIXIV_MEDIA_POLICY.recipe(
        media_occurrence_id=1,
        variant_key="original",
        selected_url=url,
    )


def _limits(**changes: object) -> TransferLimits:
    values: dict[str, object] = {
        "max_item_bytes": 100,
        "max_attempts": 1,
        "max_seconds": 30.0,
        "max_redirects": 3,
        "chunk_size": 3,
        "initial_backoff_seconds": 1.0,
        "max_backoff_seconds": 4.0,
    }
    values.update(changes)
    return TransferLimits(**values)  # type: ignore[arg-type]


def _storage(root: Path) -> AssetStorage:
    root.mkdir()
    return AssetStorage.for_remote(
        root,
        limits=InspectionLimits(max_bytes=1000, max_pixels=10_000, max_frames=10),
        chunk_size=4,
    )


def test_streams_fixed_chunks_into_descriptor_bound_staging(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"Content-Type": "image/jpeg", "Content-Length": "6", "ETag": '"v1"'},
            content=b"abcdef",
        )

    with _storage(tmp_path / "managed") as storage, httpx.Client(
        transport=httpx.MockTransport(handler)
    ) as client:
        result = HTTPTransferEngine(client).transfer(
            _recipe(), storage, limits=_limits(), budget=TransferBudget(10)
        )

        assert result.complete
        assert result.received_bytes == 6
        assert result.staged is not None
        assert result.staged.size == 6
        assert result.attempts[0].received_bytes == 6
        assert seen[0].headers["Referer"] == "https://app-api.pixiv.net/"
        assert seen[0].extensions.get("timeout") is not None
        storage.cleanup_staging(result.staged)


def test_manual_redirects_validate_each_hop_before_request(tmp_path: Path) -> None:
    seen: list[str] = []

    def allowed_handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if len(seen) == 1:
            return httpx.Response(302, headers={"Location": "/next.jpg"})
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"ok")

    with _storage(tmp_path / "allowed") as storage, httpx.Client(
        transport=httpx.MockTransport(allowed_handler)
    ) as client:
        result = HTTPTransferEngine(client).transfer(
            _recipe(), storage, limits=_limits(), budget=TransferBudget(10)
        )
        assert result.complete
        assert len(seen) == 2
        assert result.attempts[0].redirect_count == 1
        assert result.staged is not None
        storage.cleanup_staging(result.staged)

    seen.clear()

    def blocked_handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "https://example.com/private.jpg?token=leak"},
        )

    with _storage(tmp_path / "blocked") as storage, httpx.Client(
        transport=httpx.MockTransport(blocked_handler)
    ) as client:
        result = HTTPTransferEngine(client).transfer(
            _recipe(), storage, limits=_limits(), budget=TransferBudget(10)
        )
        assert result.outcome == "policy_failure"
        assert not result.retryable
        assert len(seen) == 1
        assert "leak" not in str(result.as_dict())


class _FakeTime:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def test_retries_respect_retry_after_attempt_limit_and_observer(tmp_path: Path) -> None:
    calls = 0
    transitions: list[AttemptTransition] = []
    fake = _FakeTime()

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"yes")

    with _storage(tmp_path / "managed") as storage, httpx.Client(
        transport=httpx.MockTransport(handler)
    ) as client:
        result = HTTPTransferEngine(
            client, clock=fake.clock, sleeper=fake.sleep
        ).transfer(
            _recipe(),
            storage,
            limits=_limits(max_attempts=2),
            budget=TransferBudget(10),
            observer=transitions.append,
        )
        assert result.complete
        assert calls == 2
        assert fake.sleeps == [2.0]
        assert [event.state for event in transitions] == [
            "running",
            "failed",
            "running",
            "complete",
        ]
        assert result.staged is not None
        storage.cleanup_staging(result.staged)


@pytest.mark.parametrize(
    ("status", "outcome", "retryable"),
    [
        (401, "authentication_required", False),
        (403, "authorization_denied", False),
        (404, "unavailable", False),
        (410, "unavailable", False),
        (429, "rate_limited", True),
        (503, "transient_provider", True),
    ],
)
def test_typed_http_outcomes(
    tmp_path: Path, status: int, outcome: str, retryable: bool
) -> None:
    with _storage(tmp_path / str(status)) as storage, httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(status))
    ) as client:
        result = HTTPTransferEngine(client).transfer(
            _recipe(), storage, limits=_limits(), budget=TransferBudget(10)
        )
        assert (result.outcome, result.retryable) == (outcome, retryable)


def test_content_length_and_chunked_bodies_obey_both_budgets(tmp_path: Path) -> None:
    requests = 0

    def oversized_length(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "image/jpeg", "Content-Length": "101"},
            content=b"",
        )

    with _storage(tmp_path / "length") as storage, httpx.Client(
        transport=httpx.MockTransport(oversized_length)
    ) as client:
        result = HTTPTransferEngine(client).transfer(
            _recipe(), storage, limits=_limits(), budget=TransferBudget(1000)
        )
        assert result.outcome == "response_too_large"
        assert result.received_bytes == 0
        assert requests == 1

    class ChunkedStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"123"
            yield b"456"

    with _storage(tmp_path / "budget") as storage, httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, headers={"Content-Type": "image/jpeg"}, stream=ChunkedStream()
            )
        )
    ) as client:
        budget = TransferBudget(5)
        result = HTTPTransferEngine(client).transfer(
            _recipe(), storage, limits=_limits(), budget=budget
        )
        assert result.outcome == "budget_exhausted"
        assert result.retryable
        assert len(result.attempts) == 1
        assert result.received_bytes == 3
        assert budget.used_bytes == 3


class _FailingStream(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield b"abc"
        raise httpx.ReadError("signed URL and authorization are private")


def test_interrupted_strong_etag_resumes_only_with_coherent_206(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def first(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={
                "Content-Type": "image/jpeg",
                "Content-Length": "6",
                "ETag": '"strong-v1"',
            },
            stream=_FailingStream(),
        )

    with _storage(tmp_path / "managed") as storage:
        with httpx.Client(transport=httpx.MockTransport(first)) as client:
            interrupted = HTTPTransferEngine(client).transfer(
                _recipe(), storage, limits=_limits(), budget=TransferBudget(10)
            )
        assert interrupted.state == "interrupted"
        assert interrupted.resume is not None
        assert interrupted.resume.partial.byte_count == 3
        assert "private" not in str(interrupted.as_dict())

        def second(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            assert request.headers["Range"] == "bytes=3-"
            assert request.headers["If-Range"] == '"strong-v1"'
            return httpx.Response(
                206,
                headers={
                    "Content-Type": "image/jpeg",
                    "Content-Length": "3",
                    "Content-Range": "bytes 3-5/6",
                    "ETag": '"strong-v1"',
                },
                content=b"def",
            )

        with httpx.Client(transport=httpx.MockTransport(second)) as client:
            completed = HTTPTransferEngine(client).transfer(
                _recipe(),
                storage,
                limits=_limits(),
                budget=TransferBudget(10),
                resume=interrupted.resume,
            )
        assert completed.complete
        assert completed.received_bytes == 3
        assert completed.staged is not None
        assert completed.staged.size == 6
        storage.cleanup_staging(completed.staged)


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Range": "bytes 2-5/6", "ETag": '"strong-v1"'},
        {"Content-Range": "bytes 3-5/7", "ETag": '"strong-v1"'},
        {"Content-Range": "bytes 3-5/6", "ETag": '"changed"'},
        {"Content-Range": "bytes 3-4/6", "ETag": '"strong-v1"'},
    ],
)
def test_invalid_resume_responses_never_append(
    tmp_path: Path, headers: dict[str, str]
) -> None:
    with _storage(tmp_path / "managed") as storage:
        session = storage.begin_remote_staging(_recipe().request_identity, max_bytes=100)
        session.write(b"abc")
        partial = ResumeState(session.detach(), '"strong-v1"', 6)
        response_headers = {
            "Content-Type": "image/jpeg",
            "Content-Length": "3",
            **headers,
        }
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(206, headers=response_headers, content=b"def")
            )
        ) as client:
            result = HTTPTransferEngine(client).transfer(
                _recipe(),
                storage,
                limits=_limits(),
                budget=TransferBudget(10),
                resume=partial,
            )
        assert result.outcome == "source_changed"
        assert not result.retryable
        assert result.staged is None
        assert result.resume is None


def test_ignored_range_restarts_from_zero_without_concatenation(tmp_path: Path) -> None:
    with _storage(tmp_path / "managed") as storage:
        session = storage.begin_remote_staging(_recipe().request_identity, max_bytes=100)
        session.write(b"abc")
        partial = ResumeState(session.detach(), '"strong-v1"', 6)
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={
                        "Content-Type": "image/jpeg",
                        "Content-Length": "6",
                        "ETag": '"strong-v2"',
                    },
                    content=b"uvwxyz",
                )
            )
        ) as client:
            result = HTTPTransferEngine(client).transfer(
                _recipe(),
                storage,
                limits=_limits(),
                budget=TransferBudget(10),
                resume=partial,
            )
        assert result.complete
        assert result.staged is not None
        assert result.staged.size == 6
        assert result.staged.sha256 != partial.partial.prefix_sha256
        storage.cleanup_staging(result.staged)


def test_weak_or_missing_etag_interruption_discards_partial(tmp_path: Path) -> None:
    for index, etag in enumerate((None, 'W/"weak"')):
        headers = {"Content-Type": "image/jpeg", "Content-Length": "6"}
        if etag:
            headers["ETag"] = etag
        with _storage(tmp_path / f"managed-{index}") as storage, httpx.Client(
            transport=httpx.MockTransport(
                lambda _request, headers=headers: httpx.Response(
                    200, headers=headers, stream=_FailingStream()
                )
            )
        ) as client:
            result = HTTPTransferEngine(client).transfer(
                _recipe(), storage, limits=_limits(), budget=TransferBudget(10)
            )
            assert result.resume is None
            assert result.outcome == "transient_provider"


def test_elapsed_deadline_and_cancellation_are_checked_between_chunks(
    tmp_path: Path,
) -> None:
    fake = _FakeTime()
    cancelled = False

    class ControlledStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            nonlocal cancelled
            yield b"abc"
            cancelled = True
            yield b"def"

    with _storage(tmp_path / "managed") as storage, httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "image/jpeg", "ETag": '"v1"'},
                stream=ControlledStream(),
            )
        )
    ) as client:
        result = HTTPTransferEngine(
            client, clock=fake.clock, cancelled=lambda: cancelled
        ).transfer(
            _recipe(), storage, limits=_limits(), budget=TransferBudget(10)
        )
        assert result.outcome == "cancelled"
        assert result.state == "interrupted"
        assert result.received_bytes == 3
        assert result.resume is not None


def test_elapsed_deadline_stops_between_chunks_and_retains_strong_partial(
    tmp_path: Path,
) -> None:
    fake = _FakeTime()

    class DeadlineStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"abc"
            fake.value = 31.0
            yield b"def"

    with _storage(tmp_path / "managed") as storage, httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "image/jpeg", "ETag": '"v1"'},
                stream=DeadlineStream(),
            )
        )
    ) as client:
        result = HTTPTransferEngine(client, clock=fake.clock).transfer(
            _recipe(), storage, limits=_limits(), budget=TransferBudget(10)
        )
        assert result.outcome == "timeout"
        assert result.state == "interrupted"
        assert result.received_bytes == 3
        assert result.resume is not None


def test_changed_request_identity_discards_old_partial_and_starts_at_zero(
    tmp_path: Path,
) -> None:
    old_recipe = _recipe("https://i.pximg.net/old.jpg")
    new_recipe = _recipe("https://i.pximg.net/new.jpg")
    seen_headers: list[httpx.Headers] = []
    with _storage(tmp_path / "managed") as storage:
        session = storage.begin_remote_staging(old_recipe.request_identity, max_bytes=100)
        session.write(b"old")
        old_resume = ResumeState(session.detach(), '"old"', 3)

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.append(request.headers)
            return httpx.Response(
                200, headers={"Content-Type": "image/jpeg"}, content=b"new"
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = HTTPTransferEngine(client).transfer(
                new_recipe,
                storage,
                limits=_limits(),
                budget=TransferBudget(10),
                resume=old_resume,
            )
        assert result.complete
        assert "Range" not in seen_headers[0]
        assert "If-Range" not in seen_headers[0]
        assert result.staged is not None
        assert result.staged.size == 3
        storage.cleanup_staging(result.staged)


def test_retryable_status_preserves_existing_partial_without_new_etag(
    tmp_path: Path,
) -> None:
    recipe = _recipe()
    with _storage(tmp_path / "managed") as storage:
        session = storage.begin_remote_staging(recipe.request_identity, max_bytes=100)
        session.write(b"abc")
        partial = ResumeState(session.detach(), '"strong-v1"', 6)
        with httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(503))
        ) as client:
            result = HTTPTransferEngine(client).transfer(
                recipe,
                storage,
                limits=_limits(),
                budget=TransferBudget(10),
                resume=partial,
            )
        assert result.outcome == "transient_provider"
        assert result.resume is not None
        assert result.resume.partial.byte_count == 3
        assert result.resume.strong_etag == '"strong-v1"'


def test_redirect_and_retry_backoff_cannot_cross_elapsed_deadline(tmp_path: Path) -> None:
    fake = _FakeTime()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, headers={"Retry-After": "30"})

    with _storage(tmp_path / "managed") as storage, httpx.Client(
        transport=httpx.MockTransport(handler)
    ) as client:
        result = HTTPTransferEngine(
            client, clock=fake.clock, sleeper=fake.sleep
        ).transfer(
            _recipe(),
            storage,
            limits=_limits(max_attempts=3, max_seconds=10.0),
            budget=TransferBudget(10),
        )
        assert result.outcome == "timeout"
        assert calls == 1
        assert fake.sleeps == []
