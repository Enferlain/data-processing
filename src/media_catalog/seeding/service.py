"""Materialize-a-seed: the non-recorded item entry point.

The decided design (catalog plan §12, 2026-10-05): an explicit operator
operation that turns the evidence bundle present at the time into a
provenance-recorded stub post the existing pipeline — planning, lookup,
candidates, review, later real sync — already works on.  The bundle is
retained as raw import evidence; nothing about the stub decides identity,
authorship, or relationships.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.links import recognize_url
from media_catalog.records import PostRecord, RawRecord
from media_catalog.records.metadata import PostExternalReferenceRecord
from media_catalog.writer import CatalogWriter

BUNDLE_VERSION = 1
SOURCE_KIND = "operator_seed"
_SEED_NOTE_LIMIT = 2000


@dataclass(frozen=True, slots=True)
class _RecognizedSeedURL:
    original: str
    canonical: str
    platform: str
    native_id: str


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class SeedMaterializationService:
    """Create provenance-recorded stub posts from operator evidence bundles."""

    def __init__(self, database: CatalogDatabase) -> None:
        self._database = database

    def materialize(
        self,
        urls: list[str] | tuple[str, ...],
        *,
        note: str | None = None,
        declared_md5: str | None = None,
        observed_at: str,
    ) -> dict[str, Any]:
        """Materialize one stub post from the supplied bundle.

        Raises ``ValueError`` with bounded diagnostics (no URL text echoed)
        before any write when the bundle is empty, a URL does not resolve to
        a stable post identity, or two URLs disagree on one platform's id.
        """

        recognized = self._recognize(urls)
        if note is not None and (not note.strip() or len(note) > _SEED_NOTE_LIMIT):
            raise ValueError("seed note must be between 1 and 2000 characters")
        if declared_md5 is not None and not (
            isinstance(declared_md5, str)
            and len(declared_md5) == 32
            and all(character in "0123456789abcdefABCDEF" for character in declared_md5)
        ):
            raise ValueError("declared MD5 must be a 32-character hex hash")

        primary = recognized[0]
        bundle = {
            "version": BUNDLE_VERSION,
            "kind": SOURCE_KIND,
            "urls": [item.original for item in recognized],
            "canonical_urls": [item.canonical for item in recognized],
            "note": note,
            "declared_md5": declared_md5.lower() if declared_md5 else None,
            "platform": primary.platform,
            "native_post_id": primary.native_id,
        }
        payload = json.dumps(bundle, ensure_ascii=False, sort_keys=True).encode()
        digest = _digest(payload)

        with self._database.transaction():
            existing = self._database.connection.execute(
                "SELECT import_run_id, status FROM import_runs "
                "WHERE source_kind = ? AND source_digest = ?",
                (SOURCE_KIND, digest),
            ).fetchone()
            if existing is not None and existing["status"] == "complete":
                return self._existing_result(primary, int(existing["import_run_id"]))
            if existing is not None:
                raise ValueError("an operator seed import run for this bundle is not complete")
            import_run_id = self._begin_import_run(digest, len(payload), observed_at)
            raw_observation_id = CatalogWriter(self._database).store_raw(
                RawRecord(payload, "application/json", "post", primary.native_id, observed_at),
                import_run_id=import_run_id,
            )
            post_id = self._write_stub(primary, raw_observation_id, observed_at)
            reference_count = self._write_references(
                post_id, recognized, raw_observation_id, observed_at
            )
            self._finish_import_run(import_run_id, observed_at)
        return {
            "status": "materialized",
            "seed_kind": "post",
            "platform": primary.platform,
            "native_post_id": primary.native_id,
            "post_id": post_id,
            "import_run_id": import_run_id,
            "url_count": len(recognized),
            "reference_count": reference_count,
        }

    def _recognize(self, urls: list[str] | tuple[str, ...]) -> list[_RecognizedSeedURL]:
        if not urls:
            raise ValueError("materialize-a-seed requires at least one URL")
        recognized: list[_RecognizedSeedURL] = []
        seen: dict[tuple[str, str], str] = {}
        for position, value in enumerate(urls, start=1):
            if not isinstance(value, str) or not value.strip() or len(value) > 2000:
                raise ValueError(f"seed URL #{position} must be text between 1 and 2000 characters")
            result = recognize_url(value)
            reference = result.reference
            if reference is None:
                raise ValueError(f"seed URL #{position} does not resolve to a known platform post")
            if reference.object_kind != "post" or reference.identifier_kind != "stable_id":
                raise ValueError(f"seed URL #{position} is not a stable post identity")
            identity = (reference.platform, reference.instance_host)
            previous = seen.get(identity)
            if previous is not None and previous != reference.native_id:
                raise ValueError(
                    f"seed URL #{position} conflicts with another URL for platform "
                    f"{reference.platform!r}"
                )
            seen[identity] = reference.native_id
            recognized.append(
                _RecognizedSeedURL(
                    original=value.strip(),
                    canonical=result.canonical.canonical_url,
                    platform=reference.platform,
                    native_id=reference.native_id,
                )
            )
        return recognized

    def _begin_import_run(self, digest: str, size: int, observed_at: str) -> int:
        cursor = self._database.connection.execute(
            """INSERT INTO import_runs (
                   source_kind, source_reference, source_digest, source_size,
                   started_at, status
               ) VALUES (?, ?, ?, ?, ?, 'running')""",
            (
                SOURCE_KIND,
                "operator-seed",
                digest,
                size,
                observed_at,
            ),
        )
        if cursor.lastrowid is None:
            raise ValueError("operator seed import run was not assigned an id")
        return int(cursor.lastrowid)

    def _finish_import_run(self, import_run_id: int, observed_at: str) -> None:
        self._database.connection.execute(
            "UPDATE import_runs SET status = 'complete', finished_at = ? WHERE import_run_id = ?",
            (observed_at, import_run_id),
        )

    def _write_stub(
        self, primary: _RecognizedSeedURL, raw_observation_id: int, observed_at: str
    ) -> int:
        return (
            CatalogWriter(self._database)
            .upsert_post(
                PostRecord(
                    primary.platform,
                    primary.native_id,
                    observed_at,
                    canonical_url=primary.canonical,
                    availability="unknown",
                ),
                raw_observation_id=raw_observation_id,
            )
            .id
        )

    def _write_references(
        self,
        post_id: int,
        recognized: list[_RecognizedSeedURL],
        raw_observation_id: int,
        observed_at: str,
    ) -> int:
        writer = CatalogWriter(self._database)
        written = 0
        for item in recognized:
            for record in (
                PostExternalReferenceRecord(
                    reference_kind="source_url",
                    observed_at=observed_at,
                    url=item.canonical,
                ),
                PostExternalReferenceRecord(
                    reference_kind="provider_id",
                    observed_at=observed_at,
                    url=item.canonical,
                    target_platform=item.platform,
                    target_object_kind="post",
                    target_identifier_kind="stable_id",
                    target_native_id=item.native_id,
                ),
            ):
                writer.add_post_external_reference(
                    post_id,
                    record,
                    raw_observation_id=raw_observation_id,
                )
                written += 1
        return written

    def _existing_result(self, primary: _RecognizedSeedURL, import_run_id: int) -> dict[str, Any]:
        connection = self._database.connection
        bundle_row = connection.execute(
            """SELECT rp.payload FROM raw_payloads rp
                 JOIN raw_observations ro ON ro.raw_payload_id = rp.raw_payload_id
                WHERE ro.import_run_id = ? AND ro.object_kind = 'post'
                ORDER BY ro.raw_observation_id LIMIT 1""",
            (import_run_id,),
        ).fetchone()
        url_count = 0
        if bundle_row is not None:
            try:
                url_count = len(json.loads(bundle_row["payload"]).get("urls", ()))
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                url_count = 0
        row = connection.execute(
            """SELECT p.post_id, (
                   SELECT COUNT(*) FROM post_external_references per
                    WHERE per.post_id = p.post_id
                      AND per.raw_observation_id IN (
                          SELECT raw_observation_id FROM raw_observations
                           WHERE import_run_id = ?
                      )
               ) AS reference_count
                 FROM posts p JOIN platforms pl USING (platform_id)
                WHERE pl.platform_key = ? AND p.native_post_id = ?""",
            (import_run_id, primary.platform, primary.native_id),
        ).fetchone()
        if row is None:
            raise ValueError("existing operator seed run has no stub post")
        return {
            "status": "existing",
            "seed_kind": "post",
            "platform": primary.platform,
            "native_post_id": primary.native_id,
            "post_id": int(row["post_id"]),
            "import_run_id": import_run_id,
            "url_count": url_count,
            "reference_count": int(row["reference_count"]),
        }
