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
from pathlib import Path
from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.links import recognize_url
from media_catalog.records import PostRecord, RawRecord
from media_catalog.records.catalog import MediaOccurrenceRecord
from media_catalog.records.metadata import PostExternalReferenceRecord
from media_catalog.records.storage import ManagedRootRecord, OccurrenceSourceRecord
from media_catalog.storage.adoption import adopt_assets
from media_catalog.storage.cas import InspectionLimits
from media_catalog.writer import CatalogWriter

BUNDLE_VERSION = 1
SOURCE_KIND = "operator_seed"
OCCURRENCE_SOURCE_KEY = "operator-seed"
_SEED_NOTE_LIMIT = 2000
_FILE_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class _RecognizedSeedURL:
    original: str
    canonical: str
    platform: str
    native_id: str


@dataclass(frozen=True, slots=True)
class _SeedFile:
    path: Path
    size: int
    sha256: str
    md5: str

    @property
    def name(self) -> str:
        return self.path.name

    def bundle_entry(self) -> dict[str, Any]:
        # The absolute path stays out of the retained bundle; it lives in the
        # managed-root and occurrence-source rows like every other local path.
        return {"name": self.name, "size": self.size, "sha256": self.sha256}


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
        file: str | Path | None = None,
        media_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Materialize one stub post from the supplied bundle.

        Raises ``ValueError`` with bounded diagnostics (no URL or path text
        echoed) before any write when the bundle is empty, a URL does not
        resolve to a stable post identity, two URLs disagree on one platform's
        id, or a supplied file is missing, irregular, or oversized.
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
        seed_file = self._validate_file(file)
        if seed_file is not None and media_root is None:
            raise ValueError("a media root is required when seeding with a local file")
        if seed_file is None and media_root is not None:
            raise ValueError("a media root is only used with a local seed file")
        if (
            seed_file is not None
            and declared_md5 is not None
            and declared_md5.lower() != seed_file.md5
        ):
            # A declared hash that disagrees with the held bytes fails closed
            # before any write, exactly as adoption's verification would.
            raise ValueError("declared MD5 does not match the supplied file")

        primary = recognized[0]
        bundle = {
            "version": BUNDLE_VERSION,
            "kind": SOURCE_KIND,
            "urls": [item.original for item in recognized],
            "canonical_urls": [item.canonical for item in recognized],
            "note": note,
            "declared_md5": declared_md5.lower() if declared_md5 else None,
            "file": seed_file.bundle_entry() if seed_file is not None else None,
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
                result = self._existing_result(primary, int(existing["import_run_id"]))
            elif existing is not None:
                raise ValueError("an operator seed import run for this bundle is not complete")
            else:
                import_run_id = self._begin_import_run(digest, len(payload), observed_at)
                raw_observation_id = CatalogWriter(self._database).store_raw(
                    RawRecord(payload, "application/json", "post", primary.native_id, observed_at),
                    import_run_id=import_run_id,
                )
                post_id = self._write_stub(primary, raw_observation_id, observed_at)
                reference_count = self._write_references(
                    post_id, recognized, raw_observation_id, observed_at
                )
                if seed_file is not None:
                    self._write_occurrence(post_id, seed_file, declared_md5, observed_at)
                self._finish_import_run(import_run_id, observed_at)
                result = {
                    "status": "materialized",
                    "seed_kind": "post",
                    "platform": primary.platform,
                    "native_post_id": primary.native_id,
                    "post_id": post_id,
                    "import_run_id": import_run_id,
                    "url_count": len(recognized),
                    "reference_count": reference_count,
                }
        if seed_file is not None:
            if media_root is None:  # pragma: no cover - validated above
                raise ValueError("a media root is required when seeding with a local file")
            result["adoption"] = self._ensure_adopted(int(result["post_id"]), seed_file, media_root)
        return result

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

    def _validate_file(self, file: str | Path | None) -> _SeedFile | None:
        if file is None:
            return None
        path = Path(file)
        if not path.is_file():
            raise ValueError("seed file must be an existing regular file")
        size = path.stat().st_size
        maximum = InspectionLimits().max_bytes
        if not 0 < size <= maximum:
            raise ValueError(f"seed file size must be between 1 and {maximum} bytes")
        sha256 = hashlib.sha256()
        md5 = hashlib.md5()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_FILE_CHUNK_BYTES), b""):
                sha256.update(chunk)
                md5.update(chunk)
        return _SeedFile(path.resolve(), size, sha256.hexdigest(), md5.hexdigest())

    def _write_occurrence(
        self,
        post_id: int,
        seed_file: _SeedFile,
        declared_md5: str | None,
        observed_at: str,
    ) -> None:
        """Land the local file as the stub's occurrence and adoptable source."""

        writer = CatalogWriter(self._database)
        occurrence = writer.upsert_media(
            post_id,
            MediaOccurrenceRecord(
                OCCURRENCE_SOURCE_KEY,
                0,
                "image",
                declared_md5=declared_md5.lower() if declared_md5 else None,
                observed_at=observed_at,
                local_path=seed_file.name,
            ),
        )
        source_root = seed_file.path.parent
        root_identity = hashlib.sha256(str(source_root).encode()).hexdigest()
        root_id = writer.register_managed_root(
            ManagedRootRecord(
                root_kind="source",
                root_identity=root_identity,
                display_label="operator-seed source",
                private_path=str(source_root),
            )
        )
        writer.add_occurrence_source(
            OccurrenceSourceRecord(
                occurrence.id,
                "legacy_local",
                seed_file.name,
                observed_at,
                managed_root_id=root_id,
                source_identity=root_identity,
            )
        )

    def _ensure_adopted(
        self,
        post_id: int,
        seed_file: _SeedFile,
        media_root: str | Path,
    ) -> dict[str, Any]:
        """Adopt the seed file into managed storage once, with verified facts."""

        connection = self._database.connection
        occurrence_id = connection.execute(
            "SELECT media_occurrence_id FROM media_occurrences "
            "WHERE post_id = ? AND source_key = ?",
            (post_id, OCCURRENCE_SOURCE_KEY),
        ).fetchone()
        if occurrence_id is None:
            raise ValueError("seed occurrence is missing for local-byte adoption")
        occurrence_id = int(occurrence_id[0])
        fingerprint = self._asset_fingerprint(occurrence_id)
        if fingerprint is not None:
            return {"status": "already-adopted", **fingerprint}
        summary = adopt_assets(
            self._database,
            seed_file.path.parent,
            media_root,
            occurrence_ids={occurrence_id},
            limits=InspectionLimits(),
        )
        fingerprint = self._asset_fingerprint(occurrence_id)
        if fingerprint is None:
            diagnostic = next(
                (
                    str(item.get("diagnostic") or item.get("outcome"))
                    for item in summary.items
                    if not item.get("asset_id")
                ),
                "adoption produced no asset",
            )
            raise ValueError(f"seed file adoption failed: {diagnostic}")
        return {
            "status": "adopted",
            "run_id": summary.run_id,
            **fingerprint,
        }

    def _asset_fingerprint(self, occurrence_id: int) -> dict[str, Any] | None:
        row = self._database.connection.execute(
            """SELECT a.verified_sha256, a.verified_md5, a.byte_size,
                      COALESCE(a.detected_width, a.width) AS width,
                      COALESCE(a.detected_height, a.height) AS height,
                      EXISTS (SELECT 1 FROM asset_fingerprints f
                               WHERE f.asset_id = a.asset_id
                                 AND f.fingerprint_kind = 'phash') AS phash_recorded
                 FROM occurrence_assets oa JOIN assets a USING (asset_id)
                WHERE oa.media_occurrence_id = ?
                ORDER BY oa.asset_id LIMIT 1""",
            (occurrence_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "verified_sha256": row["verified_sha256"],
            "verified_md5": row["verified_md5"],
            "width": row["width"],
            "height": row["height"],
            "byte_size": row["byte_size"],
            "phash_recorded": bool(row["phash_recorded"]),
        }

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
