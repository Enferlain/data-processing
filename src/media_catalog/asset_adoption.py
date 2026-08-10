"""Offline planning, adoption orchestration, and inspection queries.

The filesystem implementation in :mod:`media_catalog.asset_storage` is kept
independent from SQLite.  This module supplies the small amount of orchestration
needed to bind a source occurrence to a verified CAS asset.  Planning deliberately
uses a read-only catalog connection and only stats candidate files; execution is
committed one item at a time so a bad source cannot roll back prior successes.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from media_catalog.asset_storage import (
    AssetStorage,
    AssetStorageError,
    ExactEvidence,
    InspectionLimits,
    InspectionResult,
    LimitExceededError,
    SourceChangedError,
    StorageIntegrityError,
    UnsafePathError,
    _open_relative_directory,
    _regular,
    _same_source,
    _stream_hash,
)
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    AdoptionAttemptRecord,
    AdoptionItemRecord,
    AdoptionLimits,
    AdoptionRunRecord,
    AssetFingerprintRecord,
    AssetLocationRecord,
    AssetRecord,
    ManagedRootRecord,
)
from media_catalog.writer import CatalogWriter

_ALGORITHM_VERSION = "adoption-v1"
_SHA256_ALGORITHM = "sha256-v1"
_MD5_ALGORITHM = "md5-v1"
_PHASH_ALGORITHM = "imagehash.phash"
_PHASH_VERSION = "imagehash.phash-v1"
_SUCCESS_OUTCOMES = frozenset({"adopted", "adopted_exact_only", "existing"})


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _absolute_path(value: str | os.PathLike[str]) -> Path:
    """Make a root absolute without resolving away symlink components."""

    return Path(os.path.abspath(os.fspath(value)))


def _legacy_root_identity(path: Path) -> str:
    """Identity used by the x-likes importer for a source directory."""

    return hashlib.sha256(str(path).encode()).hexdigest()


def _public_source_path(value: str, classification: str) -> str:
    """Keep unsafe/private source path text out of structured public output."""

    if classification == "unsafe_path" or value.startswith("/"):
        return "<redacted>"
    return value


def _redact_row_paths(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("storage_path", "private_path"):
        value = row.get(key)
        if isinstance(value, str) and value.startswith("/"):
            row[key] = "<redacted>"
    return row


def _connection(database: CatalogDatabase | Path | str) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, CatalogDatabase):
        # A live writer may have committed frames in its WAL that an immutable
        # sidecar-free URI would ignore.  Snapshot it into memory instead: the
        # query connection is genuinely read-only and sees the writer's current
        # state without opening or mutating SQLite sidecars.
        snapshot = sqlite3.connect(":memory:")
        snapshot.row_factory = sqlite3.Row
        try:
            database.connection.backup(snapshot)
            snapshot.execute("PRAGMA query_only = ON")
        except BaseException:
            snapshot.close()
            raise
        return snapshot, True
    opened = CatalogDatabase.open_read_only(Path(database))
    return opened.connection, True


def _close_connection(connection: sqlite3.Connection, owned: bool) -> None:
    if owned:
        connection.close()


@dataclass(frozen=True, slots=True)
class AdoptionPlanItem:
    """One occurrence/source pair considered by a plan.

    ``classification`` is ``eligible`` for items that execution may read.  All
    other classifications are persisted as bounded, isolated outcomes by
    :func:`adopt_assets` without opening the candidate file.
    """

    item_key: str
    media_occurrence_id: int
    occurrence_source_id: int
    relative_path: str
    classification: str
    byte_size: int | None = None
    legacy_sha256: str | None = None
    legacy_md5: str | None = None
    diagnostic: str | None = None

    @property
    def eligible(self) -> bool:
        return self.classification == "eligible"


@dataclass(frozen=True, slots=True)
class AdoptionPlan:
    source_root: str
    managed_root: str
    source_root_identity: str
    managed_root_identity: str
    items: tuple[AdoptionPlanItem, ...]

    @property
    def planned_count(self) -> int:
        return sum(item.eligible for item in self.items)

    @property
    def skipped_count(self) -> int:
        return len(self.items) - self.planned_count

    @property
    def planned_bytes(self) -> int:
        return sum(item.byte_size or 0 for item in self.items if item.eligible)

    @property
    def known_bytes(self) -> bool:
        return all(item.byte_size is not None for item in self.items if item.eligible)

    @property
    def counts(self) -> dict[str, int]:
        counts: Counter[str] = Counter(item.classification for item in self.items)
        counts["total"] = len(self.items)
        return {key: counts[key] for key in sorted(counts)}

    @property
    def invalid_count(self) -> int:
        return self.skipped_count

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_root": self.source_root,
            "managed_root": self.managed_root,
            "planned_count": self.planned_count,
            "skipped_count": self.skipped_count,
            "invalid_count": self.invalid_count,
            "counts": self.counts,
            "planned_bytes": self.planned_bytes,
            "known_bytes": self.known_bytes,
            "items": [
                {
                    "item_key": item.item_key,
                    "media_occurrence_id": item.media_occurrence_id,
                    "occurrence_source_id": item.occurrence_source_id,
                    "relative_path": _public_source_path(item.relative_path, item.classification),
                    "classification": item.classification,
                    "byte_size": item.byte_size,
                    "legacy_sha256": item.legacy_sha256,
                    "legacy_md5": item.legacy_md5,
                    "diagnostic": item.diagnostic,
                }
                for item in self.items
            ],
        }


@dataclass(frozen=True, slots=True)
class AdoptionSummary:
    run_id: int
    status: str
    planned_count: int
    completed_count: int
    failed_count: int
    outcomes: dict[str, int]
    items: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "planned_count": self.planned_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "outcomes": dict(self.outcomes),
            "items": [dict(item) for item in self.items],
        }


def _candidate_rows(
    connection: sqlite3.Connection,
    source_root: Path,
    source_identity: str,
    *,
    occurrence_ids: set[int] | None = None,
    path_prefix: str | None = None,
) -> list[sqlite3.Row]:
    """Select local source references without touching source bytes."""

    # An imported x-likes root uses the hash identity, while callers may have
    # registered a descriptor identity.  Matching either keeps an imported
    # catalog relocatable without guessing among unrelated source roots.
    path_text = str(source_root)
    identities = {_legacy_root_identity(source_root), source_identity}
    sql = """
        SELECT os.occurrence_source_id, os.media_occurrence_id, os.relative_path,
               m.declared_sha256, m.declared_md5,
               (SELECT a.verified_sha256 FROM occurrence_assets oa
                  JOIN assets a ON a.asset_id = oa.asset_id
                 WHERE oa.media_occurrence_id = m.media_occurrence_id
                 ORDER BY oa.asset_id LIMIT 1) AS asset_sha256,
               (SELECT a.verified_md5 FROM occurrence_assets oa
                  JOIN assets a ON a.asset_id = oa.asset_id
                 WHERE oa.media_occurrence_id = m.media_occurrence_id
                 ORDER BY oa.asset_id LIMIT 1) AS asset_md5
          FROM occurrence_sources os
          JOIN media_occurrences m ON m.media_occurrence_id = os.media_occurrence_id
          JOIN managed_roots r ON r.managed_root_id = os.managed_root_id
         WHERE os.source_kind = 'legacy_local'
           AND r.root_kind = 'source'
           AND (r.private_path = ? OR r.root_identity IN (?, ?))
         ORDER BY os.occurrence_source_id
    """
    rows = list(connection.execute(sql, (path_text, *identities)))
    if occurrence_ids is not None:
        rows = [row for row in rows if int(row["media_occurrence_id"]) in occurrence_ids]
    if path_prefix is not None:
        prefix = path_prefix.rstrip("/") + "/"
        rows = [
            row
            for row in rows
            if str(row["relative_path"]) == path_prefix
            or str(row["relative_path"]).startswith(prefix)
        ]
    # A rerun registers the same physical source under a descriptor identity;
    # retain one deterministic source reference instead of adopting it twice.
    unique: dict[tuple[int, str], sqlite3.Row] = {}
    for row in rows:
        key = (int(row["media_occurrence_id"]), str(row["relative_path"]))
        unique.setdefault(key, row)
    return list(unique.values())


def plan_adoption(
    database: CatalogDatabase | Path | str,
    source_root: str | os.PathLike[str],
    managed_root: str | os.PathLike[str],
    *,
    occurrence_ids: Iterable[int] | None = None,
    path_prefix: str | None = None,
    limit: int | None = None,
    max_bytes: int | None = None,
) -> AdoptionPlan:
    """Create a no-write adoption plan.

    The catalog is opened with ``mode=ro`` when a path is supplied (and the
    caller's connection is only queried when a :class:`CatalogDatabase` is
    supplied).  Root opening and ``fstat`` are the only filesystem operations;
    no managed layout, journal, staging file, or CAS target is created.
    """

    source_path = _absolute_path(source_root)
    managed_path = _absolute_path(managed_root)
    ids = None if occurrence_ids is None else {int(value) for value in occurrence_ids}
    if limit is not None and limit < 0:
        raise ValueError("limit must not be negative")
    if max_bytes is not None and max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    connection, owned = _connection(database)
    try:
        items: list[AdoptionPlanItem] = []
        # initialize_layout=False is important: planning must not create storage
        # directories, even when the selected root is empty.
        with AssetStorage(source_path, managed_path, initialize_layout=False) as storage:
            source_identity = f"{storage.source.identity[0]}:{storage.source.identity[1]}"
            rows = _candidate_rows(
                connection,
                source_path,
                source_identity,
                occurrence_ids=ids,
                path_prefix=path_prefix,
            )
            for row in rows:
                if limit is not None and len(items) >= limit:
                    break
                relative = str(row["relative_path"])
                item_key = (
                    f"occurrence:{int(row['media_occurrence_id'])}:"
                    f"source:{int(row['occurrence_source_id'])}"
                )
                legacy_sha = row["declared_sha256"] or row["asset_sha256"]
                legacy_md5 = row["declared_md5"] or row["asset_md5"]
                try:
                    opened = storage.open_source(relative)
                except UnsafePathError:
                    items.append(
                        AdoptionPlanItem(
                            item_key,
                            int(row["media_occurrence_id"]),
                            int(row["occurrence_source_id"]),
                            relative,
                            "unsafe_path",
                            legacy_sha256=legacy_sha,
                            legacy_md5=legacy_md5,
                            diagnostic="unsafe source path",
                        )
                    )
                    continue
                except FileNotFoundError:
                    items.append(
                        AdoptionPlanItem(
                            item_key,
                            int(row["media_occurrence_id"]),
                            int(row["occurrence_source_id"]),
                            relative,
                            "missing",
                            legacy_sha256=legacy_sha,
                            legacy_md5=legacy_md5,
                            diagnostic="source file is missing",
                        )
                    )
                    continue
                except OSError:
                    items.append(
                        AdoptionPlanItem(
                            item_key,
                            int(row["media_occurrence_id"]),
                            int(row["occurrence_source_id"]),
                            relative,
                            "unreadable",
                            legacy_sha256=legacy_sha,
                            legacy_md5=legacy_md5,
                            diagnostic="source file could not be opened",
                        )
                    )
                    continue
                try:
                    size = int(opened.before.st_size)
                finally:
                    opened.close()
                if max_bytes is not None and size > max_bytes:
                    classification = "limit_exceeded"
                    diagnostic = "source exceeds the configured byte limit"
                    eligible_size = None
                else:
                    classification = "eligible"
                    diagnostic = None
                    eligible_size = size
                items.append(
                    AdoptionPlanItem(
                        item_key,
                        int(row["media_occurrence_id"]),
                        int(row["occurrence_source_id"]),
                        relative,
                        classification,
                        eligible_size,
                        legacy_sha,
                        legacy_md5,
                        diagnostic,
                    )
                )
        return AdoptionPlan(
            source_path.name or "source",
            managed_path.name or "managed",
            source_identity,
            f"{storage.media.identity[0]}:{storage.media.identity[1]}",
            tuple(items),
        )
    finally:
        _close_connection(connection, owned)


def _error_outcome(error: BaseException) -> tuple[str, str]:
    if isinstance(error, FileNotFoundError):
        return "missing", "source file is missing"
    if isinstance(error, PermissionError):
        return "unreadable", "source file could not be read"
    if isinstance(error, LimitExceededError):
        return "limit_exceeded", "source exceeds an inspection limit"
    if isinstance(error, AssetStorageError):
        return error.category, str(error)[:1000]
    if isinstance(error, OSError):
        return "unreadable", "source file could not be read"
    return "unreadable", "source adoption failed"


def _persist_failure(
    database: CatalogDatabase,
    writer: CatalogWriter,
    run_id: int,
    item: AdoptionPlanItem,
    outcome: str,
    diagnostic: str,
    *,
    started_at: str,
    exact_evidence: ExactEvidence | None = None,
) -> dict[str, Any]:
    with database.transaction():
        item_id = writer.record_adoption_item(
            AdoptionItemRecord(
                run_id,
                item.item_key,
                outcome,
                media_occurrence_id=item.media_occurrence_id,
                occurrence_source_id=item.occurrence_source_id,
                sha256=exact_evidence.sha256 if exact_evidence else None,
                md5=exact_evidence.md5 if exact_evidence else None,
                byte_size=exact_evidence.size if exact_evidence else None,
                diagnostic=diagnostic,
            )
        )
        writer.record_adoption_attempt(
            AdoptionAttemptRecord(
                item_id,
                1,
                outcome,
                started_at,
                _now(),
                sha256=exact_evidence.sha256 if exact_evidence else None,
                md5=exact_evidence.md5 if exact_evidence else None,
                byte_size=exact_evidence.size if exact_evidence else None,
                diagnostic=diagnostic,
            )
        )
    return {
        "item_key": item.item_key,
        "media_occurrence_id": item.media_occurrence_id,
        "occurrence_source_id": item.occurrence_source_id,
        "outcome": outcome,
        "sha256": exact_evidence.sha256 if exact_evidence else None,
        "md5": exact_evidence.md5 if exact_evidence else None,
        "byte_size": exact_evidence.size if exact_evidence else None,
        "diagnostic": diagnostic,
    }


def _existing_location(
    connection: sqlite3.Connection,
    occurrence_id: int,
    managed_root_id: int,
    relative_path: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """SELECT a.asset_id, a.verified_sha256, a.verified_md5, a.byte_size,
                          a.detected_mime_type, a.detected_width, a.detected_height,
                          a.detected_frame_count, l.relative_path
                     FROM occurrence_assets oa
                     JOIN assets a ON a.asset_id = oa.asset_id
                     JOIN asset_locations l ON l.asset_id = a.asset_id
                    WHERE oa.media_occurrence_id = ? AND l.managed_root_id = ?
                      AND l.relative_path = ?
                    ORDER BY l.asset_location_id LIMIT 1""",
        (occurrence_id, managed_root_id, relative_path),
    ).fetchone()


def _hash_open_source(storage: AssetStorage, relative_path: str) -> ExactEvidence:
    """Hash an already-adopted source without creating another staging file."""

    opened = storage.open_source(relative_path)
    try:
        before = opened.before
        sha256 = hashlib.sha256()
        md5 = hashlib.md5(usedforsecurity=False)
        size = 0
        os.lseek(opened.fd, 0, os.SEEK_SET)
        while True:
            chunk = os.read(opened.fd, storage.chunk_size)
            if not chunk:
                break
            size += len(chunk)
            if size > storage.limits.max_bytes:
                raise LimitExceededError("source exceeds the configured byte limit")
            sha256.update(chunk)
            md5.update(chunk)
        after = os.fstat(opened.fd)
        evidence = ExactEvidence(size, sha256.hexdigest(), md5.hexdigest())
        if (
            (int(before.st_dev), int(before.st_ino))
            != (int(after.st_dev), int(after.st_ino))
            or before.st_size != size
            or after.st_size != size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            error = SourceChangedError("source metadata changed while it was read")
            error.exact_evidence = evidence
            raise error
        return evidence
    finally:
        opened.close()


def _verify_existing_cas(
    storage: AssetStorage, relative_path: str, expected_sha256: str, expected_size: int | None
) -> None:
    """Verify an existing CAS target descriptor without following components."""

    components = relative_path.split("/")
    if len(components) != 4 or components[0] != "sha256":
        raise StorageIntegrityError("managed location is not a CAS path")
    parent_fd = _open_relative_directory(storage.media.fd, components[:-1], create=False)
    try:
        try:
            fd = os.open(
                components[-1],
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except FileNotFoundError as error:
            raise StorageIntegrityError("managed CAS target is missing") from error
        except OSError as error:
            raise StorageIntegrityError("managed CAS target is unsafe") from error
        try:
            before = os.fstat(fd)
            if not _regular(before):
                raise StorageIntegrityError("managed CAS target is not a regular file")
            size, sha256, _md5 = _stream_hash(fd, max_bytes=storage.limits.max_bytes)
            after = os.fstat(fd)
            if not _same_source(before, after, size) or sha256 != expected_sha256.lower():
                raise StorageIntegrityError("managed CAS target has corrupt bytes")
            if expected_size is not None and size != expected_size:
                raise StorageIntegrityError("managed CAS target has an unexpected size")
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def adopt_assets(
    database: CatalogDatabase,
    source_root: str | os.PathLike[str],
    managed_root: str | os.PathLike[str],
    *,
    plan: AdoptionPlan | None = None,
    occurrence_ids: Iterable[int] | None = None,
    path_prefix: str | None = None,
    limit: int | None = None,
    limits: InspectionLimits | None = None,
) -> AdoptionSummary:
    """Adopt all items in a plan, committing each item independently."""

    if plan is None:
        plan = plan_adoption(
            database,
            source_root,
            managed_root,
            occurrence_ids=occurrence_ids,
            path_prefix=path_prefix,
            limit=limit,
            max_bytes=limits.max_bytes if limits is not None else None,
        )
    storage_limits = limits or InspectionLimits()
    source_path = _absolute_path(source_root)
    managed_path = _absolute_path(managed_root)
    with AssetStorage(
        source_path,
        managed_path,
        limits=storage_limits,
        initialize_layout=False,
    ) as storage:
        opened_source_identity = f"{storage.source.identity[0]}:{storage.source.identity[1]}"
        opened_managed_identity = f"{storage.media.identity[0]}:{storage.media.identity[1]}"
        if (
            opened_source_identity != plan.source_root_identity
            or opened_managed_identity != plan.managed_root_identity
        ):
            raise SourceChangedError("source or managed root identity changed after planning")
        storage._ensure_layout()
        # The lock is acquired before any catalog mutation.  A competing process
        # therefore cannot create a run row while another owner holds this root.
        with storage.lock():
            writer = CatalogWriter(database)
            source_identity = opened_source_identity
            managed_identity = opened_managed_identity
            started = _now()
            with database.transaction():
                source_id = writer.register_managed_root(
                    ManagedRootRecord(
                        "source", source_identity, source_path.name or "source", str(source_path)
                    )
                )
                managed_id = writer.register_managed_root(
                    ManagedRootRecord(
                        "managed",
                        managed_identity,
                        managed_path.name or "managed",
                        str(managed_path),
                    )
                )
                run_id = writer.begin_adoption_run(
                    AdoptionRunRecord(
                        managed_id,
                        managed_identity,
                        _ALGORITHM_VERSION,
                        started,
                        source_root_id=source_id,
                        source_root_identity=source_identity,
                        fingerprint_algorithm=_PHASH_ALGORITHM,
                        limits=AdoptionLimits(
                            storage_limits.max_bytes,
                            storage_limits.max_pixels,
                            storage_limits.max_frames,
                        ),
                        planned_count=len(plan.items),
                    )
                )
            result_items: list[dict[str, Any]] = []
            counts: Counter[str] = Counter()
            completed = 0
            failed = 0
            try:
                for item in plan.items:
                    item_started = _now()
                    if not item.eligible:
                        result = _persist_failure(
                            database,
                            writer,
                            run_id,
                            item,
                            item.classification,
                            item.diagnostic or item.classification,
                            started_at=item_started,
                        )
                        failed += 1
                        counts[item.classification] += 1
                        result_items.append(result)
                        continue
                    exact_evidence: ExactEvidence | None = None
                    try:
                        # A successful prior item can be reused without another
                        # staging file.  We still securely open and hash the
                        # source, so a deleted or changed legacy source remains
                        # a bounded failure rather than silently becoming valid.
                        existing = None
                        if item.legacy_sha256:
                            existing = _existing_location(
                                database.connection,
                                item.media_occurrence_id,
                                managed_id,
                                AssetStorage.cas_path(item.legacy_sha256),
                            )
                        if existing is not None:
                            exact_evidence = _hash_open_source(storage, item.relative_path)
                            size = exact_evidence.size
                            source_sha = exact_evidence.sha256
                            source_md5 = exact_evidence.md5
                            existing_md5 = existing["verified_md5"]
                            if source_sha != str(existing["verified_sha256"]).lower() or (
                                existing_md5 and source_md5 != str(existing_md5).lower()
                            ):
                                existing = None
                            else:
                                _verify_existing_cas(
                                    storage,
                                    str(existing["relative_path"]),
                                    str(existing["verified_sha256"]),
                                    existing["byte_size"],
                                )
                        if existing is not None:
                            inspection = InspectionResult(
                                int(existing["byte_size"] or size),
                                str(existing["verified_sha256"]).lower(),
                                source_md5,
                                str(existing["detected_mime_type"] or "application/octet-stream"),
                                existing["detected_width"],
                                existing["detected_height"],
                                existing["detected_frame_count"],
                                exact_only=existing["detected_width"] is None,
                            )
                            adopted_relative_path = str(existing["relative_path"])
                            outcome = "existing"
                        else:
                            adopted = storage.adopt(
                                item.relative_path,
                                legacy_sha256=item.legacy_sha256,
                                legacy_md5=item.legacy_md5,
                            )
                            inspection = adopted.inspection
                            assert inspection is not None
                            adopted_relative_path = adopted.relative_path
                            outcome = adopted.status
                        with database.transaction():
                            asset_id = writer.link_asset(
                                item.media_occurrence_id,
                                AssetRecord(
                                    inspection.sha256,
                                    inspection.md5,
                                    None,
                                    inspection.size,
                                    "managed",
                                    None,
                                    _now(),
                                    "adoption",
                                    inspection.mime_type,
                                    inspection.width,
                                    inspection.height,
                                    inspection.frame_count,
                                ),
                                relationship="reference",
                            )
                            writer.add_asset_location(
                                AssetLocationRecord(
                                    asset_id,
                                    managed_id,
                                    adopted_relative_path
                                    or AssetStorage.cas_path(inspection.sha256),
                                    byte_size=inspection.size,
                                    recorded_sha256=inspection.sha256,
                                )
                            )
                            observed = _now()
                            writer.add_asset_fingerprint(
                                AssetFingerprintRecord(
                                    asset_id,
                                    "sha256",
                                    inspection.sha256,
                                    "sha256",
                                    _SHA256_ALGORITHM,
                                    "adoption",
                                    "verified",
                                    observed,
                                )
                            )
                            writer.add_asset_fingerprint(
                                AssetFingerprintRecord(
                                    asset_id,
                                    "md5",
                                    inspection.md5,
                                    "md5",
                                    _MD5_ALGORITHM,
                                    "adoption",
                                    "verified",
                                    observed,
                                )
                            )
                            if inspection.phash is not None:
                                writer.add_asset_fingerprint(
                                    AssetFingerprintRecord(
                                        asset_id,
                                        "phash",
                                        inspection.phash,
                                        _PHASH_ALGORITHM,
                                        _PHASH_VERSION,
                                        "adoption",
                                        "calculated",
                                        observed,
                                    )
                                )
                            item_id = writer.record_adoption_item(
                                AdoptionItemRecord(
                                    run_id,
                                    item.item_key,
                                    outcome,
                                    media_occurrence_id=item.media_occurrence_id,
                                    occurrence_source_id=item.occurrence_source_id,
                                    asset_id=asset_id,
                                    sha256=inspection.sha256,
                                    md5=inspection.md5,
                                    byte_size=inspection.size,
                                    detected_mime_type=inspection.mime_type,
                                    detected_width=inspection.width,
                                    detected_height=inspection.height,
                                    detected_frame_count=inspection.frame_count,
                                )
                            )
                            writer.record_adoption_attempt(
                                AdoptionAttemptRecord(
                                    item_id,
                                    1,
                                    outcome,
                                    item_started,
                                    _now(),
                                    sha256=inspection.sha256,
                                    md5=inspection.md5,
                                    byte_size=inspection.size,
                                    detected_mime_type=inspection.mime_type,
                                    detected_width=inspection.width,
                                    detected_height=inspection.height,
                                    detected_frame_count=inspection.frame_count,
                                )
                            )
                        completed += 1
                        counts[outcome] += 1
                        result_items.append(
                            {
                                "item_key": item.item_key,
                                "media_occurrence_id": item.media_occurrence_id,
                                "occurrence_source_id": item.occurrence_source_id,
                                "asset_id": asset_id,
                                "outcome": outcome,
                                "sha256": inspection.sha256,
                                "relative_path": adopted_relative_path,
                            }
                        )
                    except Exception as error:  # item isolation is intentional
                        outcome, diagnostic = _error_outcome(error)
                        result = _persist_failure(
                            database,
                            writer,
                            run_id,
                            item,
                            outcome,
                            diagnostic,
                            started_at=item_started,
                            exact_evidence=getattr(error, "exact_evidence", exact_evidence),
                        )
                        failed += 1
                        counts[outcome] += 1
                        result_items.append(result)
                status = "complete" if failed == 0 else "partial"
                with database.transaction():
                    writer.finish_adoption_run(
                        run_id,
                        status=status,
                        finished_at=_now(),
                        completed_count=completed,
                        failed_count=failed,
                    )
            except Exception as error:
                with database.transaction():
                    writer.finish_adoption_run(
                        run_id,
                        status="failed",
                        finished_at=_now(),
                        completed_count=completed,
                        failed_count=max(failed, 1),
                        diagnostic=str(error)[:1000],
                    )
                raise
            return AdoptionSummary(
                run_id,
                status,
                len(plan.items),
                completed,
                failed,
                dict(counts),
                tuple(result_items),
            )


def list_assets(
    database: CatalogDatabase | Path | str,
    *,
    sha256: str | None = None,
    asset_id: int | None = None,
) -> list[dict[str, Any]]:
    """Read public asset metadata and managed locations.

    ``assets.storage_path`` predates occurrence-level provenance and may contain
    a private legacy filename or an arbitrary relative path.  It is deliberately
    omitted from this default query; legacy assertions are represented only by
    bounded counts/classification fields and the detail query's redacted
    assertion metadata.
    """

    connection, owned = _connection(database)
    try:
        clauses: list[str] = []
        values: list[Any] = []
        if sha256 is not None:
            clauses.append("a.verified_sha256 = ?")
            values.append(sha256.lower())
        if asset_id is not None:
            clauses.append("a.asset_id = ?")
            values.append(asset_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = connection.execute(
            f"""SELECT a.asset_id, a.verified_sha256, a.verified_md5, a.phash,
                              a.byte_size, a.mime_type, a.width, a.height, a.storage_kind,
                              a.verified_at, a.verification_method,
                              a.detected_mime_type, a.detected_width, a.detected_height,
                              a.detected_frame_count,
                              (SELECT COUNT(*) FROM asset_legacy_assertions la
                                WHERE la.asset_id = a.asset_id) AS legacy_assertion_count,
                              (SELECT COUNT(*) FROM asset_legacy_assertions la
                                WHERE la.asset_id = a.asset_id
                                  AND la.associated_occurrence_id IS NULL)
                                AS legacy_assertion_unassociated_count,
                              (SELECT MIN(la.assertion_kind) FROM asset_legacy_assertions la
                                WHERE la.asset_id = a.asset_id)
                                AS legacy_assertion_classification,
                              l.asset_location_id, l.managed_root_id, l.relative_path,
                              l.location_kind, l.byte_size AS location_byte_size,
                              l.recorded_sha256, r.display_label AS root_label
                         FROM assets a
                    LEFT JOIN asset_locations l ON l.asset_id = a.asset_id
                        AND l.location_kind <> 'legacy'
                    LEFT JOIN managed_roots r ON r.managed_root_id = l.managed_root_id
                        {where}
                     ORDER BY a.asset_id, l.asset_location_id""",
            values,
        )
        return [_redact_row_paths(dict(row)) for row in rows]
    finally:
        _close_connection(connection, owned)


def legacy_assertion_summary(
    database: CatalogDatabase | Path | str,
) -> dict[str, Any]:
    """Return bounded counts/classification for migrated legacy asset paths.

    The summary intentionally never returns ``legacy_path`` values.  It is safe
    for default list/show output and gives callers a stable way to explain the
    migration's ambiguous and currently unassociated assertions.
    """

    connection, owned = _connection(database)
    try:
        rows = list(
            connection.execute(
                """SELECT assertion_kind,
                              COUNT(*) AS count,
                              SUM(CASE WHEN associated_occurrence_id IS NULL THEN 1 ELSE 0 END)
                                AS unassociated_count
                         FROM asset_legacy_assertions
                     GROUP BY assertion_kind ORDER BY assertion_kind"""
            )
        )
        by_classification = {
            str(row["assertion_kind"]): int(row["count"]) for row in rows
        }
        return {
            "total": sum(by_classification.values()),
            "ambiguous": sum(
                count
                for kind, count in by_classification.items()
                if kind == "ambiguous_asset_path"
            ),
            "unassociated": sum(int(row["unassociated_count"] or 0) for row in rows),
            "by_classification": by_classification,
        }
    finally:
        _close_connection(connection, owned)


def get_asset(
    database: CatalogDatabase | Path | str, identifier: int | str
) -> dict[str, Any] | None:
    rows = list_assets(
        database,
        asset_id=identifier if isinstance(identifier, int) else None,
        sha256=identifier if isinstance(identifier, str) else None,
    )
    return rows[0] if rows else None


def get_asset_detail(
    database: CatalogDatabase | Path | str, identifier: int | str
) -> dict[str, Any] | None:
    """Return one asset with its locations, fingerprints, and occurrences."""

    asset = get_asset(database, identifier)
    if asset is None:
        return None
    asset_id = int(asset["asset_id"])
    connection, owned = _connection(database)
    try:
        locations = [
            dict(row)
            for row in connection.execute(
                """SELECT l.*, r.display_label AS root_label
                            FROM asset_locations l
                        LEFT JOIN managed_roots r ON r.managed_root_id = l.managed_root_id
                            WHERE l.asset_id = ? AND l.location_kind <> 'legacy'
                         ORDER BY l.asset_location_id""",
                (asset_id,),
            )
        ]
        legacy_assertions = [
            {
                "asset_legacy_assertion_id": row["asset_legacy_assertion_id"],
                "asset_id": row["asset_id"],
                "assertion_kind": row["assertion_kind"],
                "associated_occurrence_id": row["associated_occurrence_id"],
                "recorded_at": row["recorded_at"],
            }
            for row in connection.execute(
                """SELECT asset_legacy_assertion_id, asset_id, assertion_kind,
                                  associated_occurrence_id, recorded_at
                             FROM asset_legacy_assertions
                            WHERE asset_id = ? ORDER BY asset_legacy_assertion_id""",
                (asset_id,),
            )
        ]
        fingerprints = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM asset_fingerprints WHERE asset_id = ? "
                "ORDER BY asset_fingerprint_id",
                (asset_id,),
            )
        ]
        occurrences = [
            dict(row)
            for row in connection.execute(
                """SELECT oa.media_occurrence_id, oa.relationship, oa.verification_source,
                                  m.post_id, m.source_key, m.media_index
                             FROM occurrence_assets oa
                             JOIN media_occurrences m
                               ON m.media_occurrence_id = oa.media_occurrence_id
                            WHERE oa.asset_id = ? ORDER BY oa.media_occurrence_id""",
                (asset_id,),
            )
        ]
        return {
            "asset": asset,
            "locations": locations,
            "legacy_assertions": legacy_assertions,
            "fingerprints": fingerprints,
            "occurrences": occurrences,
        }
    finally:
        _close_connection(connection, owned)


def list_adoption_runs(
    database: CatalogDatabase | Path | str, *, status: str | None = None
) -> list[dict[str, Any]]:
    connection, owned = _connection(database)
    try:
        if status is None:
            rows = connection.execute("SELECT * FROM adoption_runs ORDER BY adoption_run_id DESC")
        else:
            rows = connection.execute(
                "SELECT * FROM adoption_runs WHERE status = ? ORDER BY adoption_run_id DESC",
                (status,),
            )
        return [dict(row) for row in rows]
    finally:
        _close_connection(connection, owned)


def get_adoption_run(
    database: CatalogDatabase | Path | str, run_id: int
) -> dict[str, Any] | None:
    connection, owned = _connection(database)
    try:
        run = connection.execute(
            "SELECT * FROM adoption_runs WHERE adoption_run_id = ?", (run_id,)
        ).fetchone()
        if run is None:
            return None
        items = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM adoption_items WHERE adoption_run_id = ? "
                "ORDER BY adoption_item_id",
                (run_id,),
            )
        ]
        attempts = [
            dict(row)
            for row in connection.execute(
                """SELECT aa.* FROM adoption_attempts aa
                         JOIN adoption_items ai ON ai.adoption_item_id = aa.adoption_item_id
                        WHERE ai.adoption_run_id = ?
                        ORDER BY aa.adoption_attempt_id""",
                (run_id,),
            )
        ]
        return {"run": dict(run), "items": items, "attempts": attempts}
    finally:
        _close_connection(connection, owned)


def list_failed_adoption_items(
    database: CatalogDatabase | Path | str, *, run_id: int | None = None
) -> list[dict[str, Any]]:
    connection, owned = _connection(database)
    try:
        if run_id is None:
            rows = connection.execute(
                "SELECT * FROM adoption_items "
                "WHERE outcome NOT IN ('adopted','adopted_exact_only','existing') "
                "ORDER BY adoption_item_id"
            )
        else:
            rows = connection.execute(
                "SELECT * FROM adoption_items WHERE adoption_run_id = ? "
                "AND outcome NOT IN ('adopted','adopted_exact_only','existing') "
                "ORDER BY adoption_item_id",
                (run_id,),
            )
        return [dict(row) for row in rows]
    finally:
        _close_connection(connection, owned)


def find_exact_duplicates(database: CatalogDatabase | Path | str) -> list[dict[str, Any]]:
    """Return assets referenced by more than one media occurrence."""

    connection, owned = _connection(database)
    try:
        rows = connection.execute(
            """SELECT a.verified_sha256 AS sha256, a.asset_id,
                      COUNT(DISTINCT oa.media_occurrence_id) AS occurrence_count,
                      GROUP_CONCAT(DISTINCT oa.media_occurrence_id) AS occurrence_ids
                 FROM assets a JOIN occurrence_assets oa ON oa.asset_id = a.asset_id
             GROUP BY a.asset_id, a.verified_sha256
               HAVING COUNT(DISTINCT oa.media_occurrence_id) > 1
             ORDER BY a.asset_id"""
        )
        return [dict(row) for row in rows]
    finally:
        _close_connection(connection, owned)


class AssetQueryService:
    """Convenience object for read-only asset/run inspection."""

    def __init__(self, database: CatalogDatabase | Path | str) -> None:
        self.database = database

    def assets(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list_assets(self.database, **kwargs)

    def legacy_assertion_summary(self) -> dict[str, Any]:
        return legacy_assertion_summary(self.database)

    def asset(self, identifier: int | str) -> dict[str, Any] | None:
        return get_asset(self.database, identifier)

    def asset_detail(self, identifier: int | str) -> dict[str, Any] | None:
        return get_asset_detail(self.database, identifier)

    def runs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list_adoption_runs(self.database, **kwargs)

    def run(self, run_id: int) -> dict[str, Any] | None:
        return get_adoption_run(self.database, run_id)

    def failures(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list_failed_adoption_items(self.database, **kwargs)

    def exact_duplicates(self) -> list[dict[str, Any]]:
        return find_exact_duplicates(self.database)


class AssetAdoptionService:
    """Stateful facade used by command interfaces and offline callers."""

    def __init__(
        self,
        database: CatalogDatabase,
        source_root: str | os.PathLike[str],
        managed_root: str | os.PathLike[str],
        *,
        limits: InspectionLimits | None = None,
    ) -> None:
        self.database = database
        self.source_root = source_root
        self.managed_root = managed_root
        self.limits = limits

    def plan(self, **kwargs: Any) -> AdoptionPlan:
        return plan_adoption(
            self.database,
            self.source_root,
            self.managed_root,
            **kwargs,
        )

    def adopt(self, **kwargs: Any) -> AdoptionSummary:
        return adopt_assets(
            self.database,
            self.source_root,
            self.managed_root,
            limits=self.limits,
            **kwargs,
        )


# Short command-facing spellings retained alongside the explicit names.
plan = plan_adoption
adopt = adopt_assets


__all__ = [
    "AdoptionPlan",
    "AdoptionPlanItem",
    "AdoptionSummary",
    "AssetAdoptionService",
    "AssetQueryService",
    "adopt",
    "adopt_assets",
    "find_exact_duplicates",
    "get_adoption_run",
    "get_asset",
    "get_asset_detail",
    "legacy_assertion_summary",
    "list_adoption_runs",
    "list_assets",
    "list_failed_adoption_items",
    "plan",
    "plan_adoption",
]
