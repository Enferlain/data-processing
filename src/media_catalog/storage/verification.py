"""Read-only reconciliation for managed content-addressed media.

The adoption service owns publication of files.  This module intentionally has
no writer dependency: it opens the catalog in SQLite read-only mode, walks an
already-existing managed root through directory descriptors, and reports what
it observes.  In particular, verification never creates the managed layout,
reclaims staging files, or repairs catalog records.
"""

from __future__ import annotations

import errno
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.storage.cas import (
    AssetStorage,
    AssetStorageError,
    RootHandle,
    UnsafePathError,
    _flags,
    _normal_hash,
    _open_child_directory,
    _open_relative_directory,
    _regular,
    _safe_components,
    _same_source,
    _stream_hash,
)


class VerificationError(AssetStorageError):
    """Base class for verifier configuration failures."""

    category = "verification_error"


@dataclass(frozen=True, slots=True)
class VerificationFinding:
    """One bounded observation from the catalog or managed filesystem."""

    status: str
    relative_path: str
    asset_id: int | None = None
    asset_location_id: int | None = None
    expected_sha256: str | None = None
    actual_sha256: str | None = None
    expected_size: int | None = None
    actual_size: int | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Stable, structured result of one read-only verification pass."""

    managed_root_id: int | None
    managed_root_label: str | None
    findings: tuple[VerificationFinding, ...]
    entries_examined: int = 0

    @property
    def valid(self) -> tuple[VerificationFinding, ...]:
        return self._for_status("valid")

    @property
    def missing(self) -> tuple[VerificationFinding, ...]:
        return self._for_status("missing")

    @property
    def corrupt(self) -> tuple[VerificationFinding, ...]:
        return self._for_status("corrupt")

    @property
    def orphaned(self) -> tuple[VerificationFinding, ...]:
        return self._for_status("orphaned")

    @property
    def unsafe(self) -> tuple[VerificationFinding, ...]:
        return self._for_status("unsafe")

    @property
    def stale_staging(self) -> tuple[VerificationFinding, ...]:
        return self._for_status("stale_staging")

    @property
    def counts(self) -> dict[str, int]:
        return {
            status: len(self._for_status(status))
            for status in ("valid", "missing", "corrupt", "orphaned", "unsafe", "stale_staging")
        }

    @property
    def ok(self) -> bool:
        return not any(self.counts[status] for status in ("missing", "corrupt", "unsafe"))

    @property
    def status(self) -> str:
        return "ok" if self.ok else "issues"

    def _for_status(self, status: str) -> tuple[VerificationFinding, ...]:
        return tuple(finding for finding in self.findings if finding.status == status)

    def as_dict(self) -> dict[str, Any]:
        """Return output suitable for stable JSON serialization.

        Only the caller-supplied relative paths are exposed.  The absolute
        catalog and managed-root paths are deliberately not retained here.
        """

        return {
            "status": self.status,
            "managed_root_id": self.managed_root_id,
            "managed_root_label": self.managed_root_label,
            "entries_examined": self.entries_examined,
            "counts": self.counts,
            "findings": [finding.as_dict() for finding in self.findings],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class _Location:
    location_id: int
    asset_id: int
    relative_path: str
    expected_sha256: str | None
    expected_size: int | None


def _bounded_detail(value: object, fallback: str) -> str:
    """Avoid leaking absolute paths or unbounded OS diagnostics."""

    detail = str(value).replace("\n", " ").replace("\r", " ")
    if len(detail) > 240:
        return fallback
    if "/" in detail and (detail.startswith("/") or ":\\" in detail):
        return fallback
    return detail or fallback


def _scan_names(fd: int, limit: int) -> tuple[list[str], bool]:
    """Read at most ``limit`` names from an opened directory descriptor."""

    if limit <= 0:
        return [], True
    names: list[str] = []
    with os.scandir(fd) as entries:
        for entry in entries:
            if len(names) >= limit:
                return names, True
            names.append(entry.name)
    names.sort()
    return names, False


def _is_hex(value: str, length: int) -> bool:
    return len(value) == length and all(char in "0123456789abcdef" for char in value)


def _public_path(value: object) -> str:
    """Keep user-visible paths bounded and redact absolute private paths."""

    text = str(value)
    if text.startswith("/") or (len(text) >= 3 and text[1] == ":" and text[2] in {"/", "\\"}):
        return "<absolute path redacted>"
    return text[:240]


class AssetStorageVerifier:
    """Verify one catalog's managed CAS without mutating either side.

    ``managed_root_id`` is recommended when a catalog has more than one
    managed root.  The verifier opens the root using :class:`RootHandle` and
    never calls ``AssetStorage(..., initialize_layout=True)``; missing layout
    directories are therefore observed, not created.
    """

    def __init__(
        self,
        catalog: CatalogDatabase | str | os.PathLike[str],
        managed_root: str | os.PathLike[str],
        *,
        managed_root_id: int | None = None,
        max_bytes: int = 128 * 1024 * 1024,
        max_entries: int = 100_000,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.catalog = catalog
        self.managed_root = managed_root
        self.managed_root_id = managed_root_id
        self.max_bytes = max_bytes
        self.max_entries = max_entries

    def verify(self) -> VerificationReport:
        database, owns_database = self._open_catalog()
        try:
            root_row = self._managed_root_row(database)
            if root_row is None:
                return VerificationReport(
                    self.managed_root_id,
                    None,
                    (
                        VerificationFinding(
                            "unsafe",
                            "",
                            detail="managed root is not registered in the catalog",
                        ),
                    ),
                )

            root_id = int(root_row["managed_root_id"])
            label = str(root_row["display_label"])
            locations = self._locations(database, root_id)
            findings: list[VerificationFinding] = []
            referenced: set[str] = set()
            examined = 0
            try:
                root = RootHandle.open(self.managed_root, label=label)
            except BaseException as error:
                return VerificationReport(
                    root_id,
                    label,
                    (
                        VerificationFinding(
                            "unsafe",
                            "",
                            detail=self._root_error(error),
                        ),
                    ),
                )
            try:
                root_identity = f"{root.identity[0]}:{root.identity[1]}"
                if root_identity != str(root_row["root_identity"]):
                    return VerificationReport(
                        root_id,
                        label,
                        (
                            VerificationFinding(
                                "unsafe",
                                "",
                                detail="managed root identity does not match the catalog",
                            ),
                        ),
                    )
                for location in locations:
                    finding, canonical = self._verify_location(root, location)
                    findings.append(finding)
                    if canonical is not None:
                        referenced.add(canonical)
                    examined += 1
                    if examined >= self.max_entries:
                        findings.append(
                            VerificationFinding(
                                "unsafe",
                                "",
                                detail="verification entry limit exceeded",
                            )
                        )
                        return VerificationReport(root_id, label, tuple(findings), examined)

                self._verify_cas_tree(root, referenced, findings, examined)
                examined += self._last_examined
                self._last_examined = 0
                self._verify_staging(root, findings, examined + self._last_examined)
                examined += self._last_examined
            finally:
                root.close()
            return VerificationReport(root_id, label, tuple(findings), examined)
        finally:
            if owns_database:
                database.close()

    # Common spelling used by callers that treat verification as a service.
    run = verify

    def _open_catalog(self) -> tuple[CatalogDatabase, bool]:
        if isinstance(self.catalog, CatalogDatabase):
            return self.catalog, False
        try:
            return CatalogDatabase.open_read_only(Path(self.catalog)), True
        except OSError as error:
            raise VerificationError("catalog could not be opened read-only") from error

    def _managed_root_row(self, database: CatalogDatabase) -> Any:
        if self.managed_root_id is not None:
            return database.connection.execute(
                "SELECT managed_root_id, display_label, root_identity "
                "FROM managed_roots WHERE managed_root_id = ? AND root_kind = 'managed'",
                (self.managed_root_id,),
            ).fetchone()
        rows = list(
            database.connection.execute(
                "SELECT managed_root_id, display_label, root_identity "
                "FROM managed_roots WHERE root_kind = 'managed' ORDER BY managed_root_id"
            )
        )
        if len(rows) == 1:
            return rows[0]
        if not rows:
            return None
        raise VerificationError("managed_root_id is required when the catalog has multiple roots")

    @staticmethod
    def _locations(database: CatalogDatabase, root_id: int) -> tuple[_Location, ...]:
        rows = database.connection.execute(
            """SELECT al.asset_location_id, al.asset_id, al.relative_path,
                      al.recorded_sha256, al.byte_size,
                      a.verified_sha256, a.byte_size AS asset_byte_size
                 FROM asset_locations AS al
                 LEFT JOIN assets AS a ON a.asset_id = al.asset_id
                WHERE al.managed_root_id = ? AND al.location_kind = 'managed'
                ORDER BY al.relative_path, al.asset_location_id""",
            (root_id,),
        )
        return tuple(
            _Location(
                int(row["asset_location_id"]),
                int(row["asset_id"]),
                str(row["relative_path"]),
                row["recorded_sha256"] or row["verified_sha256"],
                row["byte_size"] if row["byte_size"] is not None else row["asset_byte_size"],
            )
            for row in rows
        )

    def _verify_location(
        self, root: RootHandle, location: _Location
    ) -> tuple[VerificationFinding, str | None]:
        try:
            components = _safe_components(location.relative_path)
        except UnsafePathError as error:
            return (
                VerificationFinding(
                    "unsafe",
                    _public_path(location.relative_path),
                    location.asset_id,
                    location.location_id,
                    detail=self._safe_error(error),
                ),
                None,
            )
        expected: str | None
        try:
            expected = _normal_hash(location.expected_sha256, 64, "SHA-256")
        except ValueError:
            return (
                VerificationFinding(
                    "unsafe",
                    _public_path(location.relative_path),
                    location.asset_id,
                    location.location_id,
                    detail="catalog contains an invalid SHA-256",
                ),
                None,
            )
        if expected is None:
            return (
                VerificationFinding(
                    "unsafe",
                    _public_path(location.relative_path),
                    location.asset_id,
                    location.location_id,
                    detail="managed location has no verified SHA-256",
                ),
                None,
            )
        canonical = AssetStorage.cas_path(expected)
        if components != canonical.split("/"):
            return (
                VerificationFinding(
                    "unsafe",
                    _public_path(location.relative_path),
                    location.asset_id,
                    location.location_id,
                    expected_sha256=expected,
                    detail="managed location is not the deterministic SHA-256 path",
                ),
                None,
            )
        finding = self._verify_target(
            root,
            components,
            expected,
            location.expected_size,
            asset_id=location.asset_id,
            location_id=location.location_id,
        )
        return finding, canonical

    def _verify_target(
        self,
        root: RootHandle,
        components: list[str],
        expected: str,
        expected_size: int | None,
        *,
        asset_id: int | None = None,
        location_id: int | None = None,
    ) -> VerificationFinding:
        parent_fd = -1
        fd = -1
        relative = "/".join(components)
        try:
            parent_fd = _open_relative_directory(root.fd, components[:-1])
            try:
                fd = os.open(
                    components[-1],
                    _flags("O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"),
                    dir_fd=parent_fd,
                )
            except FileNotFoundError:
                return VerificationFinding(
                    "missing",
                    relative,
                    asset_id,
                    location_id,
                    expected_sha256=expected,
                    expected_size=expected_size,
                    detail="managed file is missing",
                )
            except OSError as error:
                if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                    return VerificationFinding(
                        "unsafe",
                        relative,
                        asset_id,
                        location_id,
                        expected_sha256=expected,
                        detail="managed path contains a symlink or non-directory",
                    )
                return VerificationFinding(
                    "missing",
                    relative,
                    asset_id,
                    location_id,
                    expected_sha256=expected,
                    expected_size=expected_size,
                    detail="managed file could not be opened",
                )
            info = os.fstat(fd)
            if not _regular(info):
                return VerificationFinding(
                    "unsafe",
                    relative,
                    asset_id,
                    location_id,
                    expected_sha256=expected,
                    detail="managed target is not a regular file",
                )
            before = info
            try:
                size, actual, _md5 = _stream_hash(fd, max_bytes=self.max_bytes)
            except BaseException:
                return VerificationFinding(
                    "corrupt",
                    relative,
                    asset_id,
                    location_id,
                    expected_sha256=expected,
                    detail="managed file exceeds verification limit",
                )
            after = os.fstat(fd)
            if not _same_source(before, after, size):
                return VerificationFinding(
                    "corrupt",
                    relative,
                    asset_id,
                    location_id,
                    expected_sha256=expected,
                    actual_sha256=actual,
                    expected_size=expected_size,
                    actual_size=size,
                    detail="managed file changed while being read",
                )
            if actual != expected or (expected_size is not None and size != expected_size):
                return VerificationFinding(
                    "corrupt",
                    relative,
                    asset_id,
                    location_id,
                    expected_sha256=expected,
                    actual_sha256=actual,
                    expected_size=expected_size,
                    actual_size=size,
                    detail="managed bytes do not match catalog metadata",
                )
            return VerificationFinding(
                "valid",
                relative,
                asset_id,
                location_id,
                expected_sha256=expected,
                actual_sha256=actual,
                expected_size=expected_size,
                actual_size=size,
            )
        except FileNotFoundError:
            return VerificationFinding(
                "missing",
                relative,
                asset_id,
                location_id,
                expected_sha256=expected,
                expected_size=expected_size,
                detail="managed path is missing",
            )
        except OSError:
            return VerificationFinding(
                "unsafe",
                relative,
                asset_id,
                location_id,
                expected_sha256=expected,
                detail="managed path could not be safely opened",
            )
        finally:
            if fd >= 0:
                os.close(fd)
            if parent_fd >= 0:
                os.close(parent_fd)

    _last_examined = 0

    def _verify_cas_tree(
        self,
        root: RootHandle,
        referenced: set[str],
        findings: list[VerificationFinding],
        examined: int,
    ) -> None:
        self._last_examined = 0
        try:
            cas_fd = _open_relative_directory(root.fd, ["sha256"])
        except FileNotFoundError:
            return
        except (UnsafePathError, OSError):
            findings.append(
                VerificationFinding("unsafe", "sha256", detail="CAS directory is unsafe")
            )
            return
        try:
            first_names, overflow = _scan_names(cas_fd, self.max_entries - examined)
            if overflow:
                findings.append(
                    VerificationFinding(
                        "unsafe", "sha256", detail="verification entry limit exceeded"
                    )
                )
                return
            for first in first_names:
                if not self._seen(examined, findings, f"sha256/{first}"):
                    return
                if not _is_hex(first, 2):
                    findings.append(
                        VerificationFinding(
                            "unsafe", f"sha256/{first}"[:240], detail="invalid CAS prefix"
                        )
                    )
                    continue
                try:
                    first_fd = _open_child_directory(cas_fd, first)
                except (UnsafePathError, OSError):
                    findings.append(
                        VerificationFinding(
                            "unsafe", f"sha256/{first}"[:240], detail="CAS prefix is unsafe"
                        )
                    )
                    continue
                try:
                    second_names, overflow = _scan_names(
                        first_fd, self.max_entries - examined - self._last_examined
                    )
                    if overflow:
                        findings.append(
                            VerificationFinding(
                                "unsafe", "sha256", detail="verification entry limit exceeded"
                            )
                        )
                        return
                    for second in second_names:
                        if not self._seen(examined, findings, f"sha256/{first}/{second}"):
                            return
                        if not _is_hex(second, 2):
                            findings.append(
                                VerificationFinding(
                                    "unsafe",
                                    f"sha256/{first}/{second}"[:240],
                                    detail="invalid CAS prefix",
                                )
                            )
                            continue
                        try:
                            second_fd = _open_child_directory(first_fd, second)
                        except (UnsafePathError, OSError):
                            findings.append(
                                VerificationFinding(
                                    "unsafe",
                                    f"sha256/{first}/{second}"[:240],
                                    detail="CAS prefix is unsafe",
                                )
                            )
                            continue
                        try:
                            names, overflow = _scan_names(
                                second_fd,
                                self.max_entries - examined - self._last_examined,
                            )
                            if overflow:
                                findings.append(
                                    VerificationFinding(
                                        "unsafe",
                                        "sha256",
                                        detail="verification entry limit exceeded",
                                    )
                                )
                                return
                            for name in names:
                                relative = f"sha256/{first}/{second}/{name}"
                                if not self._seen(examined, findings, relative):
                                    return
                                if not _is_hex(name, 64):
                                    findings.append(
                                        VerificationFinding(
                                            "unsafe",
                                            _public_path(relative),
                                            detail="invalid CAS filename",
                                        )
                                    )
                                    continue
                                if relative in referenced:
                                    continue
                                finding = self._verify_orphan(second_fd, name, relative)
                                findings.append(finding)
                        finally:
                            os.close(second_fd)
                finally:
                    os.close(first_fd)
        finally:
            os.close(cas_fd)

    def _verify_orphan(self, parent_fd: int, name: str, relative: str) -> VerificationFinding:
        fd = -1
        try:
            try:
                fd = os.open(name, _flags("O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"), dir_fd=parent_fd)
            except OSError as error:
                if error.errno == errno.ELOOP:
                    return VerificationFinding(
                        "unsafe", _public_path(relative), detail="orphan is a symbolic link"
                    )
                return VerificationFinding(
                    "unsafe", _public_path(relative), detail="orphan could not be safely opened"
                )
            info = os.fstat(fd)
            if not _regular(info):
                return VerificationFinding(
                    "unsafe", _public_path(relative), detail="orphan is not a regular file"
                )
            before = info
            try:
                size, actual, _md5 = _stream_hash(fd, max_bytes=self.max_bytes)
            except BaseException:
                return VerificationFinding(
                    "orphaned",
                    _public_path(relative),
                    actual_size=int(info.st_size),
                    detail="orphan exceeds verification limit",
                )
            if not _same_source(before, os.fstat(fd), size):
                return VerificationFinding(
                    "orphaned",
                    _public_path(relative),
                    actual_sha256=actual,
                    actual_size=size,
                    detail="orphan changed while being read",
                )
            detail = None if actual == name else "orphan filename does not match its bytes"
            return VerificationFinding(
                "orphaned",
                _public_path(relative),
                actual_sha256=actual,
                actual_size=size,
                detail=detail,
            )
        finally:
            if fd >= 0:
                os.close(fd)

    def _verify_staging(
        self, root: RootHandle, findings: list[VerificationFinding], examined: int
    ) -> None:
        try:
            staging_fd = _open_relative_directory(root.fd, ["staging"])
        except FileNotFoundError:
            return
        except (UnsafePathError, OSError):
            findings.append(
                VerificationFinding("unsafe", "staging", detail="staging directory is unsafe")
            )
            return
        try:
            names, overflow = _scan_names(staging_fd, self.max_entries - examined)
            if overflow:
                findings.append(
                    VerificationFinding(
                        "unsafe", "staging", detail="verification entry limit exceeded"
                    )
                )
                return
            for name in names:
                relative = f"staging/{name}"
                if not self._seen(examined, findings, relative):
                    return
                fd = -1
                try:
                    try:
                        fd = os.open(
                            name, _flags("O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"), dir_fd=staging_fd
                        )
                    except OSError as error:
                        if error.errno == errno.ELOOP:
                            findings.append(
                                VerificationFinding(
                                    "unsafe",
                                    _public_path(relative),
                                    detail="staging entry is a symbolic link",
                                )
                            )
                        else:
                            findings.append(
                                VerificationFinding(
                                    "unsafe",
                                    _public_path(relative),
                                    detail="staging entry could not be safely opened",
                                )
                            )
                        continue
                    info = os.fstat(fd)
                    if not _regular(info):
                        findings.append(
                            VerificationFinding(
                                "unsafe",
                                _public_path(relative),
                                detail="staging entry is not a regular file",
                            )
                        )
                    else:
                        findings.append(
                            VerificationFinding(
                                "stale_staging",
                                _public_path(relative),
                                actual_size=int(info.st_size),
                                detail="staging entry left by an earlier run",
                            )
                        )
                finally:
                    if fd >= 0:
                        os.close(fd)
        finally:
            os.close(staging_fd)

    def _seen(self, examined: int, findings: list[VerificationFinding], path: str) -> bool:
        self._last_examined += 1
        if examined + self._last_examined > self.max_entries:
            findings.append(
                VerificationFinding(
                    "unsafe", _public_path(path), detail="verification entry limit exceeded"
                )
            )
            return False
        return True

    @staticmethod
    def _root_error(error: BaseException) -> str:
        if isinstance(error, UnsafePathError):
            return "managed root is unsafe"
        if isinstance(error, OSError) and getattr(error, "errno", None) == errno.ENOENT:
            return "managed root is missing"
        return "managed root could not be opened safely"

    @staticmethod
    def _safe_error(error: BaseException) -> str:
        return _bounded_detail(error, "managed path is unsafe")


# Public aliases make the service discoverable without tying callers to one
# naming convention while retaining one implementation and one result shape.
ManagedAssetVerifier = AssetStorageVerifier
ManagedStorageVerifier = AssetStorageVerifier
AssetVerifier = AssetStorageVerifier


def verify_managed_storage(
    catalog: CatalogDatabase | str | os.PathLike[str],
    managed_root: str | os.PathLike[str],
    *,
    managed_root_id: int | None = None,
    max_bytes: int = 128 * 1024 * 1024,
    max_entries: int = 100_000,
) -> VerificationReport:
    """Verify managed CAS entries using a read-only catalog connection."""

    return AssetStorageVerifier(
        catalog,
        managed_root,
        managed_root_id=managed_root_id,
        max_bytes=max_bytes,
        max_entries=max_entries,
    ).verify()


verify = verify_managed_storage

__all__ = [
    "AssetStorageVerifier",
    "AssetVerifier",
    "ManagedAssetVerifier",
    "ManagedStorageVerifier",
    "VerificationError",
    "VerificationFinding",
    "VerificationReport",
    "verify",
    "verify_managed_storage",
]
