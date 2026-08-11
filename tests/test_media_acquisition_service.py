from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

import media_catalog.acquisition.publication as publication_module
from media_catalog.acquisition import AcquisitionSelection, plan_acquisition
from media_catalog.acquisition.service import AcquisitionService
from media_catalog.acquisition.transfer import AttemptTransition, HTTPTransferEngine
from media_catalog.asset_storage import InspectionLimits
from media_catalog.database import CatalogDatabase
from media_catalog.records import AcquisitionLimits

NOW = "2026-08-10T16:00:00Z"


def _png(color: tuple[int, int, int] = (20, 40, 60)) -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 3), color=color).save(output, format="PNG")
    return output.getvalue()


def _seed(database: CatalogDatabase, pixiv: bytes, danbooru: bytes | None = None) -> None:
    connection = database.connection
    pixiv_platform = int(
        connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'pixiv'"
        ).fetchone()[0]
    )
    connection.execute(
        """INSERT INTO posts (
               post_id, platform_id, native_post_id, first_seen_at, last_seen_at
           ) VALUES (1, ?, '100', ?, ?)""",
        (pixiv_platform, NOW, NOW),
    )
    connection.execute(
        """INSERT INTO media_occurrences (
               media_occurrence_id, post_id, source_key, media_index, media_type,
               remote_url, mime_type, width, height, declared_md5, declared_file_size,
               variants_json, availability, observed_at
           ) VALUES (1, 1, '100:p0', 0, 'image/png', ?, 'image/png', 4, 3, ?, ?, ?,
                     'available', ?)""",
        (
            "https://i.pximg.net/100_p0.png",
            hashlib.md5(pixiv, usedforsecurity=False).hexdigest(),
            len(pixiv),
            json.dumps(
                {
                    "variants": [
                        {"role": "original", "url": "https://i.pximg.net/100_p0.png"}
                    ]
                }
            ),
            NOW,
        ),
    )
    if danbooru is None:
        return
    danbooru_platform = int(
        connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
        ).fetchone()[0]
    )
    connection.execute(
        """INSERT INTO posts (
               post_id, platform_id, native_post_id, first_seen_at, last_seen_at
           ) VALUES (2, ?, '200', ?, ?)""",
        (danbooru_platform, NOW, NOW),
    )
    connection.execute(
        """INSERT INTO media_occurrences (
               media_occurrence_id, post_id, source_key, media_index, media_type,
               remote_url, mime_type, width, height, declared_md5, declared_file_size,
               variants_json, availability, observed_at
           ) VALUES (2, 2, 'primary', 0, 'image/png', ?, 'image/png', 4, 3, ?, ?, ?,
                     'available', ?)""",
        (
            "https://cdn.donmai.us/200.png",
            hashlib.md5(danbooru, usedforsecurity=False).hexdigest(),
            len(danbooru),
            json.dumps(
                {
                    "variants": [
                        {"role": "original", "url": "https://cdn.donmai.us/200.png"}
                    ]
                }
            ),
            NOW,
        ),
    )


def _limits(*, total: int = 10000) -> AcquisitionLimits:
    return AcquisitionLimits(10, 5000, total, 2, 30, 3, 5000, 1)


def test_executes_pixiv_and_danbooru_serially_with_shared_cas_deduplication(
    tmp_path: Path,
) -> None:
    payload = _png()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            200,
            headers={
                "Content-Type": "image/png",
                "Content-Length": str(len(payload)),
                "ETag": '"fixture"',
            },
            content=payload,
        )

    managed = tmp_path / "managed"
    managed.mkdir()
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed(database, payload, payload)
        preview = plan_acquisition(
            database,
            [AcquisitionSelection(1, "original"), AcquisitionSelection(2, "original")],
            max_items=10,
            clock=lambda: NOW,
        )
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            summary = AcquisitionService(
                database,
                HTTPTransferEngine(client),
                managed,
                inspection_limits=InspectionLimits(
                    max_bytes=5000, max_pixels=1000, max_frames=10
                ),
                clock=lambda: NOW,
            ).execute(preview, _limits())

        assert summary.complete
        assert summary.completed_count == 2
        assert len(requests) == 2
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
        assert database.connection.execute(
            "SELECT COUNT(*) FROM occurrence_assets"
        ).fetchone()[0] == 2
        assert database.connection.execute(
            "SELECT COUNT(*) FROM asset_locations"
        ).fetchone()[0] == 1
        assert database.connection.execute(
            "SELECT COUNT(*) FROM media_acquisition_attempts"
        ).fetchone()[0] == 2
        location = database.connection.execute(
            "SELECT relative_path FROM asset_locations"
        ).fetchone()[0]
        assert (managed / location).is_file()


def test_repeated_execution_is_satisfied_without_network_and_stale_plan_never_requests(
    tmp_path: Path,
) -> None:
    payload = _png()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=payload)

    managed = tmp_path / "managed"
    managed.mkdir()
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed(database, payload)
        preview = plan_acquisition(
            database,
            [AcquisitionSelection(1, "original")],
            max_items=1,
            clock=lambda: NOW,
        )
        with database.transaction():
            database.connection.execute(
                "UPDATE media_occurrences SET remote_url = ? WHERE media_occurrence_id = 1",
                ("https://i.pximg.net/changed.png",),
            )
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            stale = AcquisitionService(
                database, HTTPTransferEngine(client), managed, clock=lambda: NOW
            ).execute(preview, _limits())
        assert stale.outcome == "stale"
        assert calls == 0
        with database.transaction():
            database.connection.execute(
                "UPDATE media_occurrences SET remote_url = ? WHERE media_occurrence_id = 1",
                ("https://i.pximg.net/100_p0.png",),
            )
        preview = plan_acquisition(
            database,
            [AcquisitionSelection(1, "original")],
            max_items=1,
            clock=lambda: NOW,
        )
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            service = AcquisitionService(
                database, HTTPTransferEngine(client), managed, clock=lambda: NOW
            )
            first = service.execute(preview, _limits())
            second = service.execute(preview, _limits())
        assert first.complete and second.complete
        assert second.counts == {"already_satisfied": 1}
        assert calls == 1


def test_database_interruption_after_publication_reconciles_without_redownload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _png()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=payload)

    managed = tmp_path / "managed"
    managed.mkdir()
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed(database, payload)
        preview = plan_acquisition(
            database,
            [AcquisitionSelection(1, "original")],
            max_items=1,
            clock=lambda: NOW,
        )
        original_persist = publication_module._persist_asset

        def interrupted_persist(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise OSError("injected database-boundary interruption")

        monkeypatch.setattr(publication_module, "_persist_asset", interrupted_persist)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            first = AcquisitionService(
                database, HTTPTransferEngine(client), managed, clock=lambda: NOW
            ).execute(preview, _limits())
        assert first.status == "failed"
        assert calls == 1
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
        assert database.connection.execute(
            "SELECT COUNT(*) FROM media_acquisition_run_items WHERE sha256 IS NOT NULL"
        ).fetchone()[0] == 1

        monkeypatch.setattr(publication_module, "_persist_asset", original_persist)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            recovered = AcquisitionService(
                database, HTTPTransferEngine(client), managed, clock=lambda: NOW
            ).execute(preview, _limits())
        assert recovered.complete
        assert recovered.counts == {"existing": 1}
        assert calls == 1
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1


def test_retry_claims_durable_partial_and_resumes_with_range(tmp_path: Path) -> None:
    payload = _png()
    split = len(payload) // 2

    class InterruptedStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield payload[:split]
            raise httpx.ReadError("injected interruption")

    managed = tmp_path / "managed"
    managed.mkdir()
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed(database, payload)
        preview = plan_acquisition(
            database,
            [AcquisitionSelection(1, "original")],
            max_items=1,
            clock=lambda: NOW,
        )
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={
                        "Content-Type": "image/png",
                        "Content-Length": str(len(payload)),
                        "ETag": '"strong-v1"',
                    },
                    stream=InterruptedStream(),
                )
            )
        ) as client:
            interrupted = AcquisitionService(
                database,
                HTTPTransferEngine(client),
                managed,
                transfer_chunk_size=16,
                clock=lambda: NOW,
            ).execute(preview, AcquisitionLimits(1, 5000, 5000, 1, 30, 3, 5000))
        assert interrupted.outcome == "interrupted"
        assert database.connection.execute(
            "SELECT COUNT(*) FROM media_acquisition_partials WHERE state = 'active'"
        ).fetchone()[0] == 1
        resume_offset = int(
            database.connection.execute(
                "SELECT byte_count FROM media_acquisition_partials WHERE state = 'active'"
            ).fetchone()[0]
        )

        requests: list[httpx.Request] = []

        def resume_handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            assert request.headers["Range"] == f"bytes={resume_offset}-"
            assert request.headers["If-Range"] == '"strong-v1"'
            return httpx.Response(
                206,
                headers={
                    "Content-Type": "image/png",
                    "Content-Length": str(len(payload) - resume_offset),
                    "Content-Range": (
                        f"bytes {resume_offset}-{len(payload) - 1}/{len(payload)}"
                    ),
                    "ETag": '"strong-v1"',
                },
                content=payload[resume_offset:],
            )

        with httpx.Client(transport=httpx.MockTransport(resume_handler)) as client:
            recovered = AcquisitionService(
                database, HTTPTransferEngine(client), managed, clock=lambda: NOW
            ).retry(interrupted.acquisition_run_id)
        assert recovered.complete
        assert len(requests) == 1
        assert database.connection.execute(
            "SELECT COUNT(*) FROM media_acquisition_attempts"
        ).fetchone()[0] == 2
        assert database.connection.execute(
            "SELECT COUNT(*) FROM media_acquisition_partials WHERE state = 'active'"
        ).fetchone()[0] == 0
        predecessor = database.connection.execute(
            "SELECT resumed_from_run_id FROM media_acquisition_runs WHERE acquisition_run_id = ?",
            (recovered.acquisition_run_id,),
        ).fetchone()[0]
        assert predecessor == interrupted.acquisition_run_id


def test_retry_excludes_nonretryable_items_unless_explicit(tmp_path: Path) -> None:
    payload = _png()
    calls = 0

    def missing(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    managed = tmp_path / "managed"
    managed.mkdir()
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed(database, payload)
        preview = plan_acquisition(
            database,
            [AcquisitionSelection(1, "original")],
            max_items=1,
            clock=lambda: NOW,
        )
        with httpx.Client(transport=httpx.MockTransport(missing)) as client:
            service = AcquisitionService(
                database, HTTPTransferEngine(client), managed, clock=lambda: NOW
            )
            failed = service.execute(preview, _limits())
            with pytest.raises(ValueError, match="no selected retry items"):
                service.retry(failed.acquisition_run_id)
            retried = service.retry(
                failed.acquisition_run_id, include_nonretryable=True
            )
        assert retried.status == "failed"
        assert calls == 2
        assert database.connection.execute(
            "SELECT COUNT(*) FROM media_acquisition_attempts"
        ).fetchone()[0] == 2


def test_midstream_budget_exhaustion_retains_partial_and_retries_by_default(
    tmp_path: Path,
) -> None:
    payload = _png()

    class PayloadStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield payload

    managed = tmp_path / "managed"
    managed.mkdir()
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed(database, payload)
        preview = plan_acquisition(
            database,
            [AcquisitionSelection(1, "original")],
            max_items=1,
            clock=lambda: NOW,
        )
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={"Content-Type": "image/png", "ETag": '"budget-v1"'},
                    stream=PayloadStream(),
                )
            )
        ) as client:
            interrupted = AcquisitionService(
                database,
                HTTPTransferEngine(client),
                managed,
                transfer_chunk_size=16,
                clock=lambda: NOW,
            ).execute(preview, _limits(total=20))
        assert interrupted.status == "partial"
        assert interrupted.outcome == "interrupted"
        assert interrupted.counts == {"budget_exhausted": 1}
        run_item = database.connection.execute(
            """SELECT state, retryable FROM media_acquisition_run_items
               WHERE acquisition_run_id = ?""",
            (interrupted.acquisition_run_id,),
        ).fetchone()
        assert tuple(run_item) == ("interrupted", 1)
        resume_offset = int(
            database.connection.execute(
                "SELECT byte_count FROM media_acquisition_partials WHERE state = 'active'"
            ).fetchone()[0]
        )
        assert resume_offset == 16

        requests: list[httpx.Request] = []

        def resume(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            assert request.headers["Range"] == f"bytes={resume_offset}-"
            assert request.headers["If-Range"] == '"budget-v1"'
            remainder = payload[resume_offset:]
            return httpx.Response(
                206,
                headers={
                    "Content-Type": "image/png",
                    "Content-Length": str(len(remainder)),
                    "Content-Range": (
                        f"bytes {resume_offset}-{len(payload) - 1}/{len(payload)}"
                    ),
                    "ETag": '"budget-v1"',
                },
                content=remainder,
            )

        with httpx.Client(transport=httpx.MockTransport(resume)) as client:
            recovered = AcquisitionService(
                database,
                HTTPTransferEngine(client),
                managed,
                transfer_chunk_size=16,
                clock=lambda: NOW,
            ).retry(interrupted.acquisition_run_id, limits=_limits())
        assert recovered.complete
        assert len(requests) == 1


def test_running_attempt_is_recovered_as_interrupted_before_retry(tmp_path: Path) -> None:
    payload = _png()

    class CrashAfterAttemptStart(HTTPTransferEngine):
        def transfer(self, recipe, storage, **kwargs):  # type: ignore[no-untyped-def]
            del storage
            observer = kwargs["observer"]
            observer(
                AttemptTransition(
                    1,
                    "running",
                    None,
                    False,
                    recipe.request_identity,
                    None,
                    0,
                    0,
                    None,
                    None,
                    None,
                    None,
                )
            )
            raise RuntimeError("injected process interruption")

    managed = tmp_path / "managed"
    managed.mkdir()
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed(database, payload)
        preview = plan_acquisition(
            database,
            [AcquisitionSelection(1, "original")],
            max_items=1,
            clock=lambda: NOW,
        )
        crash_transport = httpx.MockTransport(lambda _request: httpx.Response(500))
        with httpx.Client(transport=crash_transport) as client:
            crashing = AcquisitionService(
                database, CrashAfterAttemptStart(client), managed, clock=lambda: NOW
            )
            with pytest.raises(RuntimeError, match="process interruption"):
                crashing.execute(preview, _limits())
        run_id = int(
            database.connection.execute(
                "SELECT acquisition_run_id FROM media_acquisition_runs"
            ).fetchone()[0]
        )
        assert database.connection.execute(
            "SELECT state FROM media_acquisition_attempts"
        ).fetchone()[0] == "running"

        calls = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, headers={"Content-Type": "image/png"}, content=payload)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            recovered = AcquisitionService(
                database, HTTPTransferEngine(client), managed, clock=lambda: NOW
            ).retry(run_id)
        assert recovered.complete
        assert calls == 1
        predecessor = database.connection.execute(
            "SELECT status, termination_outcome FROM media_acquisition_runs "
            "WHERE acquisition_run_id = ?",
            (run_id,),
        ).fetchone()
        assert tuple(predecessor) == ("partial", "interrupted")
        assert database.connection.execute(
            "SELECT state FROM media_acquisition_attempts "
            "WHERE acquisition_run_item_id IN ("
            "SELECT acquisition_run_item_id FROM media_acquisition_run_items "
            "WHERE acquisition_run_id = ?)",
            (run_id,),
        ).fetchone()[0] == "interrupted"
