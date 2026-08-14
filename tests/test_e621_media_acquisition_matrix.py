"""Focused OpenSpec 7.3 matrix for explicit e621 media acquisition.

All transfers use real catalog/storage services with injected ``httpx`` transports.  The
returned e621 URLs are never contacted by metadata synchronization or library expansion until
an explicit acquisition plan is executed.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Iterator
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from media_catalog.acquisition import AcquisitionSelection, plan_acquisition
from media_catalog.acquisition.queries import get_acquisition_run
from media_catalog.acquisition.service import AcquisitionService
from media_catalog.acquisition.transfer import HTTPTransferEngine
from media_catalog.adapters import AdapterOperation, load_fixture_suite
from media_catalog.adapters.e621 import E621, E621Adapter
from media_catalog.database import CatalogDatabase
from media_catalog.library import (
    ArtistLibraryExpansionService,
    ExpansionLimits,
    plan_library_expansion,
)
from media_catalog.records import (
    AccountRecord,
    AcquisitionLimits,
    AttributionRecord,
    TagObservationRecord,
)
from media_catalog.remote_sync import MetadataSyncService, SyncLimits
from media_catalog.storage.cas import InspectionLimits
from media_catalog.writer import CatalogWriter

NOW = "2026-08-13T00:00:00Z"
FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
SUITE = load_fixture_suite(FIXTURES / "e621.json")


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 3), color=(20, 40, 60)).save(output, format="PNG")
    return output.getvalue()


def _body(name: str) -> object:
    case = next(case for case in SUITE.cases if case.name == name)
    return json.loads(case.response.payload)


def _limits(*, total: int = 10_000, attempts: int = 2) -> AcquisitionLimits:
    return AcquisitionLimits(10, 5_000, total, attempts, 30, 3, 5_000, 1)


def _seed_e621_occurrence(
    database: CatalogDatabase,
    *,
    occurrence_id: int = 1,
    native_id: str = "5001",
    remote_url: str | None = "https://static1.e621.net/original/ab/file.png",
    preview_url: str | None = None,
    variants: dict[str, str | None] | None = None,
    declared_md5: str | None = None,
    declared_size: int | None = None,
    declared_mime: str | None = "image/png",
    declared_width: int | None = 4,
    declared_height: int | None = 3,
) -> None:
    connection = database.connection
    platform_id = int(
        connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'e621'"
        ).fetchone()[0]
    )
    connection.execute(
        """INSERT INTO posts (
               post_id, platform_id, native_post_id, first_seen_at, last_seen_at
           ) VALUES (?, ?, ?, ?, ?)""",
        (occurrence_id, platform_id, native_id, NOW, NOW),
    )
    if variants is None:
        variants = {
            "original": remote_url,
            "sample": "https://static1.e621.net/sample/ab/sample.png",
            "preview": preview_url or "https://static1.e621.net/preview/ab/preview.png",
        }
    variants_json = json.dumps(
        {
            "version": "e621-variants-v1",
            "variants": [
                {"role": role, "url": url} for role, url in variants.items() if url is not None
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    connection.execute(
        """INSERT INTO media_occurrences (
               media_occurrence_id, post_id, source_key, media_index, media_type,
               remote_url, preview_url, mime_type, width, height, variants_json,
               declared_md5, declared_file_size, availability, observed_at
           ) VALUES (?, ?, 'primary', 0, 'image/png', ?, ?, ?, ?, ?, ?, ?, ?, 'available', ?)""",
        (
            occurrence_id,
            occurrence_id,
            remote_url,
            preview_url,
            declared_mime,
            declared_width,
            declared_height,
            variants_json,
            declared_md5,
            declared_size,
            NOW,
        ),
    )


def _service(
    database: CatalogDatabase,
    managed: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    transfer_chunk_size: int = 64 * 1024,
) -> AcquisitionService:
    managed.mkdir(parents=True, exist_ok=True)
    return AcquisitionService(
        database,
        HTTPTransferEngine(httpx.Client(transport=httpx.MockTransport(handler))),
        managed,
        inspection_limits=InspectionLimits(max_bytes=5_000, max_pixels=1_000, max_frames=10),
        transfer_chunk_size=transfer_chunk_size,
        clock=lambda: NOW,
    )


def _plan(database: CatalogDatabase, *selections: AcquisitionSelection):
    return plan_acquisition(database, selections, max_items=len(selections), clock=lambda: NOW)


def test_e621_allowed_original_and_derivatives_verify_without_inheriting_claims(
    tmp_path: Path,
) -> None:
    payload = _png()
    digest = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            200,
            headers={"Content-Type": "image/png", "Content-Length": str(len(payload))},
            content=payload,
        )

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed_e621_occurrence(
                database,
                declared_md5=digest,
                declared_size=len(payload),
            )
        plan = _plan(
            database,
            AcquisitionSelection(1, "original"),
            AcquisitionSelection(1, "sample"),
            AcquisitionSelection(1, "preview"),
        )
        assert all(item.eligibility == "eligible" for item in plan.items)
        summary = _service(database, tmp_path / "managed", handler).execute(plan, _limits())

        assert summary.complete
        assert summary.completed_count == 3
        assert len(requests) == 3
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
        # The neutral occurrence relation is idempotent while each named
        # variant still has its own completed acquisition run item.
        assert (
            database.connection.execute("SELECT COUNT(*) FROM occurrence_assets").fetchone()[0] == 1
        )
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM media_acquisition_run_items WHERE state = 'complete'"
            ).fetchone()[0]
            == 3
        )
        run_items = database.connection.execute(
            """SELECT api.variant_key, ari.state, ari.sha256
                 FROM media_acquisition_run_items ari
                 JOIN media_acquisition_plan_items api USING(acquisition_plan_item_id)
                ORDER BY api.variant_key"""
        ).fetchall()
        assert [(row[0], row[1], row[2] is not None) for row in run_items] == [
            ("original", "complete", True),
            ("preview", "complete", True),
            ("sample", "complete", True),
        ]
        claim_counts = database.connection.execute(
            """SELECT api.variant_key, COUNT(mav.acquisition_verification_id)
                 FROM media_acquisition_plan_items api
                 LEFT JOIN media_acquisition_run_items ari USING(acquisition_plan_item_id)
                 LEFT JOIN media_acquisition_verifications mav USING(acquisition_run_item_id)
                GROUP BY api.variant_key"""
        ).fetchall()
        assert {row[0]: row[1] for row in claim_counts} == {
            "original": 5,
            "preview": 0,
            "sample": 0,
        }
        claims = database.connection.execute(
            "SELECT claim_kind, comparison_result FROM media_acquisition_verifications"
        ).fetchall()
        assert {row[0] for row in claims} == {"md5", "file_size", "mime_type", "width", "height"}
        assert all(row[1] == "matched" for row in claims)


def test_e621_exact_hash_mismatch_quarantines_but_representation_mismatches_do_not(
    tmp_path: Path,
) -> None:
    payload = _png()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=payload)

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed_e621_occurrence(database, declared_md5="0" * 32, declared_size=len(payload))
        mismatch = _service(database, tmp_path / "managed", handler).execute(
            _plan(database, AcquisitionSelection(1, "original")), _limits()
        )
        assert mismatch.outcome == "quarantined"
        assert mismatch.counts == {"hash_mismatch": 1}
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM media_acquisition_quarantine"
            ).fetchone()[0]
            == 1
        )

    with CatalogDatabase(tmp_path / "representation.sqlite3") as database:
        with database.transaction():
            _seed_e621_occurrence(
                database,
                declared_md5=hashlib.md5(payload, usedforsecurity=False).hexdigest(),
                declared_size=len(payload) + 1,
                declared_mime="image/jpeg",
                declared_width=1,
                declared_height=1,
            )
        summary = _service(database, tmp_path / "managed-representation", handler).execute(
            _plan(database, AcquisitionSelection(1, "original")), _limits()
        )
        assert summary.complete
        assert summary.counts == {"downloaded": 1}
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM media_acquisition_quarantine"
            ).fetchone()[0]
            == 0
        )
        comparisons = database.connection.execute(
            "SELECT claim_kind, comparison_result FROM media_acquisition_verifications"
        ).fetchall()
        assert {row[0] for row in comparisons if row[1] == "mismatched"} == {
            "file_size",
            "mime_type",
            "width",
            "height",
        }


@pytest.mark.parametrize(
    ("url", "location"),
    [
        ("https://example.com/not-e621.png", None),
        (
            "https://static1.e621.net/original/ab/file.png",
            "https://example.com/redirected.png",
        ),
    ],
)
def test_e621_host_and_redirect_policy_fail_before_untrusted_media_request(
    tmp_path: Path,
    url: str,
    location: str | None,
) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if location is not None:
            return httpx.Response(302, headers={"Location": location})
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=_png())

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed_e621_occurrence(database, remote_url=url, variants={"original": url})
        plan = _plan(database, AcquisitionSelection(1, "original"))
        summary = _service(database, tmp_path / "managed", handler).execute(plan, _limits())
        assert summary.outcome == "failed"
        assert summary.counts == {"policy_failure": 1}
        assert len(requests) == (1 if location is not None else 0)
        run = get_acquisition_run(database, summary.acquisition_run_id)
        assert run is not None
        assert run["items"][0]["outcome"] == "policy_failure"
        if location is not None:
            assert run["items"][0]["attempts"][0]["redirect_count"] == 0


def test_e621_null_urls_are_excluded_without_a_media_request(tmp_path: Path) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(500)

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed_e621_occurrence(
                database,
                remote_url=None,
                preview_url=None,
                variants={"original": None, "sample": None, "preview": None},
            )
        plan = _plan(database, AcquisitionSelection(1, "original"))
        assert plan.items[0].eligibility == "excluded"
        assert plan.items[0].exclusion_reason == "missing_variant"
        summary = _service(database, tmp_path / "managed", handler).execute(plan, _limits())
        assert summary.counts == {"policy_failure": 1}
        assert requests == []
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM media_acquisition_attempts"
            ).fetchone()[0]
            == 0
        )


def test_e621_interruption_resumes_and_reuses_cas_without_redownloading(tmp_path: Path) -> None:
    payload = _png()
    split = len(payload) // 2
    first_calls = 0

    class InterruptedStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield payload[:split]
            raise httpx.ReadError("injected interruption")

    def interrupted(request: httpx.Request) -> httpx.Response:
        nonlocal first_calls
        first_calls += 1
        return httpx.Response(
            200,
            headers={
                "Content-Type": "image/png",
                "Content-Length": str(len(payload)),
                "ETag": '"e621-v1"',
            },
            stream=InterruptedStream(),
        )

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed_e621_occurrence(
                database,
                declared_md5=hashlib.md5(payload, usedforsecurity=False).hexdigest(),
                declared_size=len(payload),
            )
        plan = _plan(database, AcquisitionSelection(1, "original"))
        first = _service(
            database, tmp_path / "managed", interrupted, transfer_chunk_size=16
        ).execute(plan, _limits(attempts=1))
        assert first.outcome == "interrupted"
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM media_acquisition_partials WHERE state = 'active'"
            ).fetchone()[0]
            == 1
        )
        offset = int(
            database.connection.execute(
                "SELECT byte_count FROM media_acquisition_partials WHERE state = 'active'"
            ).fetchone()[0]
        )

        requests: list[httpx.Request] = []

        def resume(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            assert request.headers["Range"] == f"bytes={offset}-"
            assert request.headers["If-Range"] == '"e621-v1"'
            return httpx.Response(
                206,
                headers={
                    "Content-Type": "image/png",
                    "Content-Length": str(len(payload) - offset),
                    "Content-Range": f"bytes {offset}-{len(payload) - 1}/{len(payload)}",
                    "ETag": '"e621-v1"',
                },
                content=payload[offset:],
            )

        recovered = _service(database, tmp_path / "managed", resume).retry(
            first.acquisition_run_id, limits=_limits()
        )
        assert recovered.complete
        assert len(requests) == 1
        assert first_calls == 1
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
        again = _service(
            database, tmp_path / "managed", lambda _request: pytest.fail("CAS should satisfy")
        ).execute(plan, _limits())
        assert again.complete
        assert again.counts == {"already_satisfied": 1}


def test_e621_public_acquisition_results_redact_returned_url_and_private_paths(
    tmp_path: Path,
) -> None:
    payload = _png()
    secret_url = "https://static1.e621.net/original/ab/file.png?token=e621-private"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=payload)

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed_e621_occurrence(
                database, remote_url=secret_url, variants={"original": secret_url}
            )
        plan = _plan(database, AcquisitionSelection(1, "original"))
        summary = _service(database, tmp_path / "managed-private", handler).execute(plan, _limits())
        public = json.dumps(
            {
                "plan": plan.as_dict(),
                "summary": summary.as_dict(),
                "run": get_acquisition_run(database, summary.acquisition_run_id),
            },
            sort_keys=True,
        )
        assert secret_url not in public
        assert "e621-private" not in public
        assert str(tmp_path / "managed-private") not in public


def test_metadata_sync_and_library_expansion_never_start_media_acquisition(tmp_path: Path) -> None:
    requested_hosts: list[str] = []
    first_page = _body("listing_first")
    assert isinstance(first_page, list)
    first_page = [copy.deepcopy(entry) for entry in first_page]

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host or "")
        body = _body("normal_post") if request.url.path.endswith("/posts/5001.json") else first_page
        return httpx.Response(200, headers={"content-type": "application/json"}, json=body)

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        adapter = E621Adapter(
            E621,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            clock=lambda: NOW,
        )
        try:
            metadata = MetadataSyncService(
                database,
                adapter,
                minimum_interval_seconds=0,
                maximum_retries=0,
                sleep=lambda _seconds: None,
                clock=lambda: NOW,
            ).synchronize(AdapterOperation.FETCH_POST, "5001", limits=SyncLimits(1, 1, 20, 10))
            assert metadata.status == "complete"
            writer = CatalogWriter(database)
            with database.transaction():
                seed_id = writer.upsert_account(AccountRecord("x", "9001", NOW)).id
                attribution_id = writer.upsert_attribution(
                    AttributionRecord(
                        "e621", "tag:12345", "e621-native-v1", NOW, instance_host="e621.net"
                    )
                ).id
                writer.upsert_tag_record(
                    TagObservationRecord(
                        "e621",
                        "artist",
                        "artist_a",
                        "artist_a",
                        NOW,
                        "provider-tag-v1",
                        provider_tag_id="12345",
                        native_category="artist",
                        native_category_code=1,
                    )
                )
            plan = plan_library_expansion(
                database,
                f"account:{seed_id}",
                target=f"attribution:{attribution_id}",
                selection_note="operator selected the reviewed e621 artist tag",
                limits=ExpansionLimits(requests=1, pages=1, records=20, seconds=30),
            )
            expansion = ArtistLibraryExpansionService(
                database,
                adapter,
                minimum_interval_seconds=0,
                maximum_retries=0,
                sleep=lambda _seconds: None,
                clock=lambda: NOW,
            ).run(plan)
            assert expansion.sync.status in {"complete", "paused"}
            assert (
                database.connection.execute(
                    "SELECT COUNT(*) FROM media_acquisition_runs"
                ).fetchone()[0]
                == 0
            )
            assert (
                database.connection.execute(
                    "SELECT COUNT(*) FROM media_acquisition_attempts"
                ).fetchone()[0]
                == 0
            )
            assert requested_hosts and all(host == "e621.net" for host in requested_hosts)
        finally:
            adapter._client.close()
