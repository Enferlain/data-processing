"""Safe local-media inspection and immutable content-addressed storage.

This module deliberately has no catalog/database dependency.  It provides the
filesystem primitives used by the later adoption service: roots are opened
once, path components are walked relative to directory descriptors, sources
are copied into private staging files while being hashed, and staged bytes are
published through an atomic, no-overwrite hard-link operation.

The implementation is intentionally POSIX-only.  The operations used here do
not have a safe equivalent on every platform; refusing to run is safer than
falling back to a pathname ``resolve`` check.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import mimetypes
import os
import secrets
import stat
import warnings
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from ctypes import CDLL, c_char_p, c_int
from ctypes import get_errno as ctypes_get_errno
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from PIL import Image, UnidentifiedImageError

try:
    import imagehash as _imagehash
except ImportError:  # pragma: no cover - declared runtime dependency
    _imagehash: Any = None


class AnyHash(Protocol):
    def update(self, data: bytes) -> None: ...

    def hexdigest(self) -> str: ...


class AssetStorageError(Exception):
    """Base class for bounded, stable storage failures."""

    category = "storage_error"


class CapabilityError(AssetStorageError):
    category = "capability_unavailable"


class UnsafePathError(AssetStorageError):
    category = "unsafe_path"


class RootOverlapError(AssetStorageError):
    category = "overlapping_roots"


class SourceChangedError(AssetStorageError):
    category = "source_changed"


class LimitExceededError(AssetStorageError):
    category = "limit_exceeded"


class HashMismatchError(AssetStorageError):
    category = "hash_mismatch"


class InspectionError(AssetStorageError):
    category = "inspection_failed"


class StorageIntegrityError(AssetStorageError):
    category = "storage_integrity_failed"


class LockError(AssetStorageError):
    category = "storage_locked"


_AT_EMPTY_PATH = 0x1000
_LINKAT = None
try:  # pragma: no cover - platform-dependent capability discovery
    _LIBC = CDLL(None, use_errno=True)
    _LINKAT = _LIBC.linkat
    _LINKAT.argtypes = [c_int, c_char_p, c_int, c_char_p, c_int]
    _LINKAT.restype = c_int
except (AttributeError, OSError):
    _LINKAT = None


def _require_capabilities() -> None:
    """Fail closed unless all descriptor-relative primitives are available."""

    if os.name != "posix":
        raise CapabilityError("descriptor-relative no-follow storage requires POSIX")
    required = ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC")
    missing = [name for name in required if not hasattr(os, name)]
    if missing:
        raise CapabilityError(f"missing required POSIX flags: {', '.join(missing)}")
    if os.open not in getattr(os, "supports_dir_fd", set()):
        raise CapabilityError("os.open does not support directory descriptors")
    for function in (os.mkdir, os.unlink):
        if function not in getattr(os, "supports_dir_fd", set()):
            raise CapabilityError(f"{function.__name__} lacks directory-descriptor support")
    if _LINKAT is None:
        raise CapabilityError("descriptor-bound hard-link publication is unavailable")


def _flags(*names: str) -> int:
    return sum(getattr(os, name) for name in names)


def _identity(info: os.stat_result) -> tuple[int, int]:
    return int(info.st_dev), int(info.st_ino)


def _regular(info: os.stat_result) -> bool:
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def _directory(info: os.stat_result) -> bool:
    return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def _safe_components(value: str | os.PathLike[str], *, allow_dot: bool = False) -> list[str]:
    """Validate and split a relative POSIX path without normalizing it."""

    try:
        text = os.fspath(value)
    except TypeError as error:
        raise UnsafePathError("path must be a string or path-like value") from error
    if isinstance(text, bytes):
        try:
            text = os.fsdecode(text)
        except UnicodeDecodeError as error:
            raise UnsafePathError("path is not valid filesystem text") from error
    if "\x00" in text:
        raise UnsafePathError("path contains a NUL byte")
    if text.startswith("/"):
        raise UnsafePathError("absolute paths are not allowed")
    pieces = text.split("/")
    if not text or any(not piece for piece in pieces):
        raise UnsafePathError("empty path components are not allowed")
    if any(piece == ".." for piece in pieces):
        raise UnsafePathError("parent traversal is not allowed")
    if allow_dot:
        pieces = [piece for piece in pieces if piece != "."]
    elif any(piece == "." for piece in pieces):
        raise UnsafePathError("dot path components are not allowed")
    if not pieces:
        raise UnsafePathError("path must name a component")
    return pieces


def _open_directory_path(path: str | os.PathLike[str]) -> int:
    """Open a directory by walking every component with ``O_NOFOLLOW``."""

    _require_capabilities()
    try:
        text = os.fspath(path)
    except TypeError as error:
        raise UnsafePathError("root must be a path") from error
    if isinstance(text, bytes):
        text = os.fsdecode(text)
    if not text or "\x00" in text:
        raise UnsafePathError("root path is empty or contains a NUL byte")
    absolute = text.startswith("/")
    raw = text.split("/")
    if absolute:
        pieces = [piece for piece in raw if piece]
        fd = os.open(
            "/",
            _flags("O_RDONLY", "O_DIRECTORY", "O_CLOEXEC", "O_NOFOLLOW"),
        )
    else:
        pieces = [piece for piece in raw if piece]
        fd = os.open(
            ".",
            _flags("O_RDONLY", "O_DIRECTORY", "O_CLOEXEC", "O_NOFOLLOW"),
        )
    try:
        for piece in pieces:
            if piece in {".", ".."}:
                if piece == "..":
                    raise UnsafePathError("parent traversal is not allowed for roots")
                continue
            try:
                next_fd = os.open(
                    piece,
                    _flags("O_RDONLY", "O_DIRECTORY", "O_CLOEXEC", "O_NOFOLLOW"),
                    dir_fd=fd,
                )
            except OSError as error:
                if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise UnsafePathError(
                        "root contains a symlink or non-directory component"
                    ) from error
                raise
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if not _directory(info):
            raise UnsafePathError("root is not a directory")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_child_directory(parent_fd: int, name: str, *, create: bool = False) -> int:
    """Open a child directory, creating it safely when requested."""

    created = False
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            created = True
        except FileExistsError:
            pass
    try:
        fd = os.open(
            name,
            _flags("O_RDONLY", "O_DIRECTORY", "O_CLOEXEC", "O_NOFOLLOW"),
            dir_fd=parent_fd,
        )
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise UnsafePathError(f"managed directory component is a symlink: {name}") from error
        raise
    try:
        if not _directory(os.fstat(fd)):
            raise UnsafePathError(f"managed component is not a directory: {name}")
        if created:
            # A directory entry is not durable until both the new directory
            # and its parent have been flushed.  The caller keeps walking
            # from this descriptor, so every newly-created ancestor is
            # covered before any file can be published beneath it.
            os.fsync(fd)
            os.fsync(parent_fd)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_relative_directory(root_fd: int, components: list[str], *, create: bool = False) -> int:
    current = os.dup(root_fd)
    try:
        for component in components:
            if component in {".", ".."} or "/" in component or "\x00" in component:
                raise UnsafePathError("invalid managed path component")
            next_fd = _open_child_directory(current, component, create=create)
            os.close(current)
            current = next_fd
        return current
    except BaseException:
        os.close(current)
        raise


def _is_ancestor(candidate_fd: int, child_identity: tuple[int, int]) -> bool:
    """Determine ancestry using only opened directory descriptors."""

    current = os.dup(candidate_fd)
    try:
        for _ in range(1024):
            if _identity(os.fstat(current)) == child_identity:
                return True
            parent = os.open(
                "..",
                _flags("O_RDONLY", "O_DIRECTORY", "O_CLOEXEC", "O_NOFOLLOW"),
                dir_fd=current,
            )
            parent_identity = _identity(os.fstat(parent))
            current_identity = _identity(os.fstat(current))
            os.close(current)
            current = parent
            if parent_identity == current_identity:
                return False
        raise CapabilityError("directory ancestry exceeds safe traversal bound")
    finally:
        os.close(current)


@dataclass(slots=True)
class RootHandle:
    """An opened explicit root and its stable filesystem identity."""

    fd: int
    label: str
    identity: tuple[int, int]

    @classmethod
    def open(cls, path: str | os.PathLike[str], *, label: str | None = None) -> RootHandle:
        fd = _open_directory_path(path)
        try:
            info = os.fstat(fd)
            root_label = label or Path(os.fsdecode(os.fspath(path))).name or "root"
            return cls(fd, root_label, _identity(info))
        except BaseException:
            os.close(fd)
            raise

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> RootHandle:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


def _ensure_disjoint(source: RootHandle, managed: RootHandle) -> None:
    if source.identity == managed.identity:
        raise RootOverlapError("source and managed roots must be disjoint")
    if _is_ancestor(source.fd, managed.identity) or _is_ancestor(managed.fd, source.identity):
        raise RootOverlapError("source and managed roots must not contain one another")


@dataclass(frozen=True, slots=True)
class InspectionLimits:
    """Hard resource ceilings applied before expensive image operations."""

    max_bytes: int = 128 * 1024 * 1024
    max_pixels: int = 100_000_000
    max_frames: int = 100

    def __post_init__(self) -> None:
        if self.max_bytes <= 0 or self.max_pixels <= 0 or self.max_frames <= 0:
            raise ValueError("inspection limits must be positive")


Limits = InspectionLimits


@dataclass(slots=True)
class OpenedSource:
    fd: int
    relative_path: str
    before: os.stat_result

    def fileno(self) -> int:
        return self.fd

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> OpenedSource:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class StagedAsset:
    staging_name: str
    source_path: str
    size: int
    sha256: str
    md5: str
    # Keep the descriptor that was written and hashed.  Publication uses this
    # descriptor directly, never reopening the mutable staging pathname.
    fd: int = field(default=-1, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class RemotePartialState:
    """Path-free durable identity for reopening one owned remote partial."""

    staging_name: str
    request_identity: str
    managed_root_identity: tuple[int, int]
    staging_identity: tuple[int, int]
    byte_count: int
    prefix_sha256: str
    prefix_md5: str


@dataclass(frozen=True, slots=True)
class QuarantinedAsset:
    quarantine_name: str
    reason: str
    size: int
    sha256: str
    md5: str


class RemoteStagingSession:
    """An append-only, descriptor-bound staging writer for remote bytes."""

    def __init__(
        self,
        storage: AssetStorage,
        staging_name: str,
        request_identity: str,
        fd: int,
        max_bytes: int,
        size: int,
        sha256: AnyHash,
        md5: AnyHash,
        staging_identity: tuple[int, int],
    ) -> None:
        self.storage = storage
        self.staging_name = staging_name
        self.request_identity = request_identity
        self.fd = fd
        self.max_bytes = max_bytes
        self.size = size
        self._sha256 = sha256
        self._md5 = md5
        self.staging_identity = staging_identity
        self._finished = False

    def _require_open(self) -> int:
        if self.fd < 0 or self._finished:
            raise StorageIntegrityError("remote staging session is closed")
        if self.storage._staged_fds.get(self.staging_name) != self.fd:
            raise StorageIntegrityError("remote staging descriptor is no longer owned")
        info = os.fstat(self.fd)
        if not _regular(info) or _identity(info) != self.staging_identity:
            raise StorageIntegrityError("remote staging inode changed")
        return self.fd

    def write(self, data: bytes | bytearray | memoryview) -> int:
        fd = self._require_open()
        view = memoryview(data)
        if self.size + len(view) > self.max_bytes:
            raise LimitExceededError("remote response exceeds the configured byte limit")
        payload = bytes(view)
        written_total = 0
        while written_total < len(payload):
            written = os.write(fd, payload[written_total:])
            if written <= 0:
                raise OSError(errno.EIO, "short write while staging remote response")
            written_total += written
        self._sha256.update(payload)
        self._md5.update(payload)
        self.size += written_total
        return written_total

    def checkpoint(self) -> RemotePartialState:
        fd = self._require_open()
        os.fsync(fd)
        info = os.fstat(fd)
        if info.st_size != self.size or _identity(info) != self.staging_identity:
            raise StorageIntegrityError("remote staging file changed before checkpoint")
        staging_fd = self.storage._staging_fd()
        try:
            staged = StagedAsset(
                self.staging_name,
                "remote.partial",
                self.size,
                self._sha256.hexdigest(),
                self._md5.hexdigest(),
                fd,
            )
            self.storage._verify_staging_name(staged, staging_fd)
            os.fsync(staging_fd)
        finally:
            os.close(staging_fd)
        return RemotePartialState(
            self.staging_name,
            self.request_identity,
            self.storage.media.identity,
            self.staging_identity,
            self.size,
            self._sha256.hexdigest(),
            self._md5.hexdigest(),
        )

    def detach(self) -> RemotePartialState:
        state = self.checkpoint()
        fd = self.fd
        self.fd = -1
        self._finished = True
        self.storage._staged_fds.pop(self.staging_name, None)
        os.close(fd)
        return state

    def finalize(self, *, source_label: str = "remote") -> StagedAsset:
        state = self.checkpoint()
        staged = StagedAsset(
            state.staging_name,
            source_label,
            state.byte_count,
            state.prefix_sha256,
            state.prefix_md5,
            self.fd,
        )
        self.fd = -1
        self._finished = True
        return staged

    def close(self) -> None:
        if self.fd >= 0:
            fd = self.fd
            self.fd = -1
            self._finished = True
            self.storage._staged_fds.pop(self.staging_name, None)
            with suppress(OSError):
                os.close(fd)

    def __enter__(self) -> RemoteStagingSession:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class ExactEvidence:
    """Bounded exact-byte evidence retained when a staged item fails later."""

    size: int
    sha256: str
    md5: str


@dataclass(frozen=True, slots=True)
class InspectionResult:
    size: int
    sha256: str
    md5: str
    mime_type: str
    width: int | None = None
    height: int | None = None
    frame_count: int | None = None
    phash: str | None = None
    phash_algorithm: str | None = None
    phash_version: str | None = None
    exact_only: bool = False


@dataclass(frozen=True, slots=True)
class AdoptionResult:
    status: str
    source_path: str
    staging_name: str | None
    relative_path: str | None
    inspection: InspectionResult | None
    created: bool = False


_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "AVIF": "image/avif",
}
_RASTER_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
_PHASH_ALGORITHM = "imagehash.phash"
_PHASH_VERSION = "1"


def _attach_staged_evidence(error: BaseException, staged: StagedAsset) -> None:
    """Expose exact staged values before a controlled cleanup closes the fd."""

    if isinstance(error, AssetStorageError):
        evidence = ExactEvidence(staged.size, staged.sha256, staged.md5)
        # ``staged`` retains the original shape for callers that need the
        # staging identity; ``exact_evidence`` is the persistence-friendly,
        # path-free payload.
        error.staged = staged
        error.exact_evidence = evidence


def _is_raster_magic(prefix: bytes) -> bool:
    return (
        prefix.startswith(b"\xff\xd8\xff")
        or prefix.startswith(b"\x89PNG\r\n\x1a\n")
        or prefix.startswith((b"GIF87a", b"GIF89a"))
        or (prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP")
        or (len(prefix) >= 12 and prefix[4:8] == b"ftyp" and b"avif" in prefix[8:16])
    )


def _normal_hash(value: str | None, length: int, name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if len(normalized) != length or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"invalid legacy {name}")
    return normalized


def _stream_hash(fd: int, *, max_bytes: int | None = None) -> tuple[int, str, str]:
    os.lseek(fd, 0, os.SEEK_SET)
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    size = 0
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if max_bytes is not None and size > max_bytes:
            raise LimitExceededError("source exceeds the configured byte limit")
        sha256.update(chunk)
        md5.update(chunk)
    return size, sha256.hexdigest(), md5.hexdigest()


def _same_source(before: os.stat_result, after: os.stat_result, size: int) -> bool:
    return (
        _identity(before) == _identity(after)
        and _regular(after)
        and before.st_size == after.st_size == size
        and before.st_mtime_ns == after.st_mtime_ns
        and before.st_ctime_ns == after.st_ctime_ns
    )


class ManagedRootLock:
    """An OS-released exclusive lock owned by one adopter process."""

    def __init__(self, root: RootHandle, name: str = ".adoption.lock") -> None:
        _require_capabilities()
        if not name or "/" in name or name in {".", ".."}:
            raise UnsafePathError("invalid managed lock name")
        self._root = root
        self._name = name
        self._fd = -1

    def acquire(self) -> ManagedRootLock:
        if self._fd >= 0:
            return self
        try:
            fd = os.open(
                self._name,
                _flags("O_RDWR", "O_CREAT", "O_CLOEXEC", "O_NOFOLLOW"),
                0o600,
                dir_fd=self._root.fd,
            )
            if not _regular(os.fstat(fd)):
                os.close(fd)
                raise UnsafePathError("managed lock is not a regular file")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                os.close(fd)
                raise LockError("managed root is already locked") from error
            self._fd = fd
            return self
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise UnsafePathError("managed lock is a symbolic link") from error
            raise

    def release(self) -> None:
        if self._fd >= 0:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = -1

    def __enter__(self) -> ManagedRootLock:
        return self.acquire()

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.release()


class AssetStorage:
    """Descriptor-relative source inspection and managed CAS operations."""

    def __init__(
        self,
        source_root: str | os.PathLike[str] | RootHandle | None,
        media_root: str | os.PathLike[str] | RootHandle,
        *,
        limits: InspectionLimits | None = None,
        chunk_size: int = 1024 * 1024,
        initialize_layout: bool = True,
    ) -> None:
        _require_capabilities()
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self.limits = limits or InspectionLimits()
        self.chunk_size = chunk_size
        self._owns_source = source_root is not None and not isinstance(source_root, RootHandle)
        self._owns_media = not isinstance(media_root, RootHandle)
        self._owned_staging: set[str] = set()
        self._staged_fds: dict[str, int] = {}
        self.source = (
            RootHandle.open(source_root, label="source") if self._owns_source else source_root
        )
        try:
            self.media = (
                RootHandle.open(media_root, label="managed") if self._owns_media else media_root
            )
            if self.source is not None:
                _ensure_disjoint(self.source, self.media)
            if initialize_layout:
                self._ensure_layout()
        except BaseException:
            if self._owns_media and hasattr(self, "media"):
                self.media.close()
            if self._owns_source and self.source is not None:
                self.source.close()
            raise

    def close(self) -> None:
        for fd in self._staged_fds.values():
            with suppress(OSError):
                os.close(fd)
        self._staged_fds.clear()
        if self._owns_source and self.source is not None:
            self.source.close()
            self._owns_source = False
        if self._owns_media:
            self.media.close()
            self._owns_media = False

    def __enter__(self) -> AssetStorage:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def _ensure_layout(self) -> None:
        for name in ("sha256", "staging", "quarantine"):
            fd = _open_child_directory(self.media.fd, name, create=True)
            os.close(fd)

    @classmethod
    def for_remote(
        cls,
        media_root: str | os.PathLike[str] | RootHandle,
        *,
        limits: InspectionLimits | None = None,
        chunk_size: int = 1024 * 1024,
        initialize_layout: bool = True,
    ) -> AssetStorage:
        return cls(
            None,
            media_root,
            limits=limits,
            chunk_size=chunk_size,
            initialize_layout=initialize_layout,
        )

    def lock(self) -> ManagedRootLock:
        return ManagedRootLock(self.media)

    def open_source(self, relative_path: str | os.PathLike[str]) -> OpenedSource:
        if self.source is None:
            raise CapabilityError("remote-only storage has no local source root")
        components = _safe_components(relative_path)
        parent_fd = os.dup(self.source.fd)
        try:
            for component in components[:-1]:
                next_fd = _open_child_directory(parent_fd, component)
                os.close(parent_fd)
                parent_fd = next_fd
            try:
                fd = os.open(
                    components[-1],
                    _flags("O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"),
                    dir_fd=parent_fd,
                )
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise UnsafePathError("source path contains a symbolic link") from error
                raise
            info = os.fstat(fd)
            if not _regular(info):
                os.close(fd)
                raise UnsafePathError("source path is not a regular file")
            return OpenedSource(fd, "/".join(components), info)
        finally:
            os.close(parent_fd)

    def _open_staging(self, name: str, *, writable: bool = False) -> int:
        if not name or "/" in name or name in {".", ".."} or "\x00" in name:
            raise UnsafePathError("invalid staging name")
        flags = _flags("O_CLOEXEC", "O_NOFOLLOW") | (os.O_RDWR if writable else os.O_RDONLY)
        staging_fd = self._staging_fd()
        try:
            try:
                fd = os.open(name, flags, dir_fd=staging_fd)
            except OSError as error:
                if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise UnsafePathError("staging file is a symbolic link") from error
                raise
        finally:
            os.close(staging_fd)
        if not _regular(os.fstat(fd)):
            os.close(fd)
            raise UnsafePathError("staging entry is not a regular file")
        return fd

    def _staging_fd(self) -> int:
        return _open_relative_directory(self.media.fd, ["staging"])

    def begin_remote_staging(
        self,
        request_identity: str,
        *,
        max_bytes: int | None = None,
    ) -> RemoteStagingSession:
        """Allocate one private append-only staging file for remote bytes."""

        normalized = _normal_hash(request_identity, 64, "request identity")
        assert normalized is not None
        effective_limit = self.limits.max_bytes if max_bytes is None else max_bytes
        if effective_limit <= 0:
            raise ValueError("remote staging byte limit must be positive")
        effective_limit = min(effective_limit, self.limits.max_bytes)
        staging_fd = self._staging_fd()
        fd = -1
        name = ""
        try:
            for _ in range(16):
                candidate = f"remote-{secrets.token_hex(16)}"
                try:
                    fd = os.open(
                        candidate,
                        _flags("O_RDWR", "O_CREAT", "O_EXCL", "O_CLOEXEC", "O_NOFOLLOW"),
                        0o600,
                        dir_fd=staging_fd,
                    )
                    name = candidate
                    break
                except FileExistsError:
                    continue
            if fd < 0:
                raise AssetStorageError("could not allocate a unique remote staging file")
            info = os.fstat(fd)
            if not _regular(info) or info.st_size != 0:
                raise StorageIntegrityError("new remote staging entry is not an empty file")
            self._owned_staging.add(name)
            self._staged_fds[name] = fd
            os.fsync(staging_fd)
            return RemoteStagingSession(
                self,
                name,
                normalized,
                fd,
                effective_limit,
                0,
                hashlib.sha256(),
                hashlib.md5(usedforsecurity=False),
                _identity(info),
            )
        except BaseException:
            if name:
                self._cleanup_staging_name(
                    name,
                    staging_fd=staging_fd,
                    expected_fd=fd if fd >= 0 else None,
                )
            if fd >= 0:
                self._staged_fds.pop(name, None)
                os.close(fd)
            raise
        finally:
            os.close(staging_fd)

    def reopen_remote_staging(
        self,
        state: RemotePartialState,
        *,
        expected_request_identity: str,
        max_bytes: int | None = None,
    ) -> RemoteStagingSession:
        """Reopen a durable partial only after identity and prefix verification."""

        expected = _normal_hash(expected_request_identity, 64, "request identity")
        assert expected is not None
        if state.request_identity != expected:
            raise SourceChangedError("remote partial belongs to a different request")
        if state.managed_root_identity != self.media.identity:
            raise StorageIntegrityError("remote partial belongs to a different managed root")
        effective_limit = self.limits.max_bytes if max_bytes is None else max_bytes
        if effective_limit <= 0:
            raise ValueError("remote staging byte limit must be positive")
        effective_limit = min(effective_limit, self.limits.max_bytes)
        if state.byte_count > effective_limit:
            raise LimitExceededError("remote partial exceeds the configured byte limit")
        fd = self._open_staging(state.staging_name, writable=True)
        try:
            before = os.fstat(fd)
            if _identity(before) != state.staging_identity:
                raise StorageIntegrityError("remote partial staging inode changed")
            if before.st_size != state.byte_count:
                raise StorageIntegrityError("remote partial size changed")
            sha256 = hashlib.sha256()
            md5 = hashlib.md5(usedforsecurity=False)
            size = 0
            os.lseek(fd, 0, os.SEEK_SET)
            while True:
                chunk = os.read(fd, self.chunk_size)
                if not chunk:
                    break
                size += len(chunk)
                if size > effective_limit:
                    raise LimitExceededError("remote partial exceeds the configured byte limit")
                sha256.update(chunk)
                md5.update(chunk)
            after = os.fstat(fd)
            if not _same_source(before, after, size):
                raise StorageIntegrityError("remote partial changed while it was verified")
            if (size, sha256.hexdigest(), md5.hexdigest()) != (
                state.byte_count,
                state.prefix_sha256,
                state.prefix_md5,
            ):
                raise StorageIntegrityError("remote partial does not match its recorded hashes")
            os.lseek(fd, 0, os.SEEK_END)
            self._owned_staging.add(state.staging_name)
            self._staged_fds[state.staging_name] = fd
            return RemoteStagingSession(
                self,
                state.staging_name,
                state.request_identity,
                fd,
                effective_limit,
                size,
                sha256,
                md5,
                state.staging_identity,
            )
        except BaseException:
            os.close(fd)
            raise

    def stage_source(self, relative_path: str | os.PathLike[str]) -> StagedAsset:
        """Copy one source into a unique private staging file and hash it."""

        source = self.open_source(relative_path)
        staging_fd = self._staging_fd()
        name = ""
        output_fd = -1
        size = 0
        hashed = False
        sha256 = hashlib.sha256()
        md5 = hashlib.md5(usedforsecurity=False)
        try:
            if source.before.st_size > self.limits.max_bytes:
                raise LimitExceededError("source exceeds the configured byte limit")
            for _ in range(16):
                candidate = f"stage-{secrets.token_hex(16)}"
                try:
                    output_fd = os.open(
                        candidate,
                        _flags("O_RDWR", "O_CREAT", "O_EXCL", "O_CLOEXEC", "O_NOFOLLOW"),
                        0o600,
                        dir_fd=staging_fd,
                    )
                    name = candidate
                    self._owned_staging.add(name)
                    break
                except FileExistsError:
                    continue
            if output_fd < 0:
                raise AssetStorageError("could not allocate a unique staging file")
            os.lseek(source.fd, 0, os.SEEK_SET)
            while True:
                chunk = os.read(source.fd, self.chunk_size)
                if not chunk:
                    break
                size += len(chunk)
                if size > self.limits.max_bytes:
                    raise LimitExceededError("source exceeds the configured byte limit")
                sha256.update(chunk)
                md5.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(output_fd, view)
                    if written <= 0:
                        raise OSError(errno.EIO, "short write while staging source")
                    view = view[written:]
            hashed = True
            os.fsync(output_fd)
            after = os.fstat(source.fd)
            if not _same_source(source.before, after, size):
                raise SourceChangedError("source metadata changed while it was read")
            os.fsync(staging_fd)
            staged = StagedAsset(
                name,
                source.relative_path,
                size,
                sha256.hexdigest(),
                md5.hexdigest(),
                output_fd,
            )
            self._staged_fds[name] = output_fd
            output_fd = -1
            return staged
        except BaseException as error:
            if name and hashed:
                _attach_staged_evidence(
                    error,
                    StagedAsset(
                        name,
                        source.relative_path,
                        size,
                        sha256.hexdigest(),
                        md5.hexdigest(),
                        output_fd,
                    ),
                )
            if name:
                self._cleanup_staging_name(
                    name,
                    staging_fd=staging_fd,
                    expected_fd=output_fd if output_fd >= 0 else None,
                )
            raise
        finally:
            if output_fd >= 0:
                os.close(output_fd)
            os.close(staging_fd)
            source.close()

    # Short aliases are useful to callers building a later adoption service.
    stage = stage_source

    def _cleanup_staging_name(
        self,
        name: str,
        *,
        staging_fd: int | None = None,
        expected_fd: int | None = None,
    ) -> bool:
        if name not in self._owned_staging:
            return False
        owns_fd = staging_fd is None
        fd = staging_fd if staging_fd is not None else self._staging_fd()
        removed = False
        try:
            if expected_fd is not None:
                # Do not remove a pathname that has been substituted since we
                # created the staging inode.  Leaving residue is safer than
                # unlinking another run's file under a raced name.
                try:
                    current_fd = os.open(
                        name,
                        _flags("O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"),
                        dir_fd=fd,
                    )
                except (FileNotFoundError, OSError):
                    current_fd = -1
                if current_fd < 0:
                    return False
                try:
                    try:
                        expected_identity = _identity(os.fstat(expected_fd))
                    except OSError:
                        return False
                    if _identity(os.fstat(current_fd)) != expected_identity:
                        return False
                finally:
                    os.close(current_fd)
                # POSIX has no conditional unlink-by-inode primitive.  An
                # identity check followed by pathname unlink has an unavoidable
                # race that could delete a same-user replacement.  Retain the
                # verified hard-link residue for explicit reconciliation rather
                # than performing a destructive pathname cleanup.
                return False
            with suppress(FileNotFoundError):
                os.unlink(name, dir_fd=fd)
                os.fsync(fd)
                removed = True
            return removed
        finally:
            if owns_fd:
                os.close(fd)
            self._owned_staging.discard(name)

    def cleanup_staging(self, staged: StagedAsset) -> None:
        """Best-effort cleanup limited to a staging file owned by this run."""

        self._cleanup_staging_name(staged.staging_name, expected_fd=staged.fd)
        self._close_staged_fd(staged)

    def quarantine_staged(
        self,
        staged: StagedAsset,
        *,
        reason: str,
        max_bytes: int,
    ) -> QuarantinedAsset:
        """Durably link verified staged bytes under an opaque quarantine name."""

        if not reason or not reason.strip() or len(reason) > 200:
            raise ValueError("quarantine reason must be between 1 and 200 characters")
        if max_bytes < 0:
            raise ValueError("quarantine byte limit must not be negative")
        if staged.size > max_bytes:
            raise LimitExceededError("staged bytes exceed the quarantine budget")
        quarantine_fd = -1
        staging_fd = -1
        target_fd = -1
        name = ""
        try:
            self._verify_staging(staged)
            staged_fd = self._staged_fd(staged)
            staging_fd = self._staging_fd()
            self._verify_staging_name(staged, staging_fd)
            quarantine_fd = _open_relative_directory(self.media.fd, ["quarantine"])
            visible = _open_relative_directory(self.media.fd, ["quarantine"])
            try:
                if _identity(os.fstat(visible)) != _identity(os.fstat(quarantine_fd)):
                    raise StorageIntegrityError("managed quarantine directory path changed")
            finally:
                os.close(visible)
            for _ in range(16):
                candidate = f"quarantine-{secrets.token_hex(16)}"
                try:
                    self._link_staged_fd(staged_fd, quarantine_fd, candidate)
                    name = candidate
                    break
                except FileExistsError:
                    continue
            if not name:
                raise AssetStorageError("could not allocate a unique quarantine entry")
            self._verify_staging_name(staged, staging_fd)
            visible = _open_relative_directory(self.media.fd, ["quarantine"])
            try:
                if _identity(os.fstat(visible)) != _identity(os.fstat(quarantine_fd)):
                    raise StorageIntegrityError("managed quarantine directory path changed")
            finally:
                os.close(visible)
            target_fd = os.open(
                name,
                _flags("O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"),
                dir_fd=quarantine_fd,
            )
            self._verify_target(
                target_fd,
                staged,
                expected_identity=_identity(os.fstat(staged_fd)),
            )
            os.fsync(quarantine_fd)
            return QuarantinedAsset(name, reason, staged.size, staged.sha256, staged.md5)
        except BaseException as error:
            _attach_staged_evidence(error, staged)
            raise
        finally:
            if target_fd >= 0:
                os.close(target_fd)
            if staging_fd >= 0:
                os.close(staging_fd)
            if quarantine_fd >= 0:
                os.close(quarantine_fd)

    def _close_staged_fd(self, staged: StagedAsset) -> None:
        fd = self._staged_fds.pop(staged.staging_name, None)
        if fd is None:
            fd = staged.fd
        if fd >= 0:
            with suppress(OSError):
                os.close(fd)

    def _staged_fd(self, staged: StagedAsset) -> int:
        fd = staged.fd
        if fd < 0 or self._staged_fds.get(staged.staging_name) != fd:
            raise StorageIntegrityError("staged descriptor is unavailable")
        try:
            info = os.fstat(fd)
        except OSError as error:
            raise StorageIntegrityError("staged descriptor is unavailable") from error
        if not _regular(info):
            raise StorageIntegrityError("staged descriptor is not a regular file")
        return fd

    def _verify_staging_name(self, staged: StagedAsset, staging_fd: int) -> None:
        """Ensure the owned name still denotes the inode being published."""

        staged_fd = self._staged_fd(staged)
        try:
            current_fd = os.open(
                staged.staging_name,
                _flags("O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"),
                dir_fd=staging_fd,
            )
        except OSError as error:
            raise StorageIntegrityError("staging pathname is unavailable or unsafe") from error
        try:
            current_info = os.fstat(current_fd)
            if not _regular(current_info) or _identity(current_info) != _identity(
                os.fstat(staged_fd)
            ):
                raise StorageIntegrityError("staging pathname no longer denotes its inode")
        finally:
            os.close(current_fd)

    def _verify_staging(self, staged: StagedAsset) -> None:
        fd = self._staged_fd(staged)
        before = os.fstat(fd)
        size, sha256, md5 = _stream_hash(fd, max_bytes=self.limits.max_bytes)
        after = os.fstat(fd)
        if not _same_source(before, after, size):
            raise StorageIntegrityError("staging file changed during verification")
        if (size, sha256, md5) != (staged.size, staged.sha256, staged.md5):
            raise StorageIntegrityError("staging file does not match its recorded hashes")

    def inspect_staged(self, staged: StagedAsset) -> InspectionResult:
        """Inspect staged bytes after exact hashes have already been calculated."""

        try:
            self._verify_staging(staged)
            fd = self._staged_fd(staged)
            info = os.fstat(fd)
            prefix = os.pread(fd, 32, 0)
            suffix = Path(staged.source_path).suffix.lower()
            fileobj: BinaryIO = os.fdopen(os.dup(fd), "rb", closefd=True)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    try:
                        image = Image.open(fileobj)
                    except (UnidentifiedImageError, OSError, ValueError) as error:
                        if _is_raster_magic(prefix) or suffix in _RASTER_SUFFIXES:
                            raise InspectionError("raster image could not be decoded") from error
                        guessed, _encoding = mimetypes.guess_type(staged.source_path)
                        return InspectionResult(
                            staged.size,
                            staged.sha256,
                            staged.md5,
                            guessed or "application/octet-stream",
                            exact_only=True,
                        )
                    try:
                        with image:
                            image_format = (image.format or "").upper()
                            mime_type = _MIME_BY_FORMAT.get(image_format)
                            if mime_type is None:
                                mime_type = mimetypes.types_map.get(
                                    suffix, "application/octet-stream"
                                )
                            width, height = image.size
                            if width <= 0 or height <= 0 or width * height > self.limits.max_pixels:
                                raise LimitExceededError("decoded image exceeds the pixel limit")
                            frame_count = self._bounded_frame_count(image)
                            image.seek(0)
                            image.load()
                            if image_format not in _MIME_BY_FORMAT or _imagehash is None:
                                result = InspectionResult(
                                    staged.size,
                                    staged.sha256,
                                    staged.md5,
                                    mime_type,
                                    width,
                                    height,
                                    frame_count,
                                    exact_only=True,
                                )
                            else:
                                digest = str(_imagehash.phash(image))
                                result = InspectionResult(
                                    staged.size,
                                    staged.sha256,
                                    staged.md5,
                                    mime_type,
                                    width,
                                    height,
                                    frame_count,
                                    digest,
                                    _PHASH_ALGORITHM,
                                    _PHASH_VERSION,
                                )
                    except LimitExceededError:
                        raise
                    except (Image.DecompressionBombError, OSError, ValueError) as error:
                        raise InspectionError("raster image inspection failed") from error
            finally:
                fileobj.close()
            after = os.fstat(fd)
            if not _same_source(info, after, staged.size):
                raise SourceChangedError("staged bytes changed during inspection")
            return result
        except BaseException as error:
            _attach_staged_evidence(error, staged)
            raise

    def _bounded_frame_count(self, image: Image.Image) -> int:
        """Count at most ``max_frames + 1`` frames without trusting metadata."""

        count = 0
        for frame_index in range(self.limits.max_frames + 1):
            try:
                image.seek(frame_index)
            except EOFError:
                break
            except (OSError, ValueError) as error:
                raise InspectionError("raster frame inspection failed") from error
            count += 1
        if count > self.limits.max_frames:
            raise LimitExceededError("image exceeds the frame limit")
        if count == 0:
            raise InspectionError("raster image has no decodable frames")
        return count

    inspect = inspect_staged

    @staticmethod
    def cas_relative_path(sha256: str) -> str:
        normalized = _normal_hash(sha256, 64, "SHA-256")
        assert normalized is not None
        return f"sha256/{normalized[:2]}/{normalized[2:4]}/{normalized}"

    cas_path = cas_relative_path

    def stage_existing_cas(
        self,
        sha256: str,
        *,
        expected_size: int | None = None,
        expected_md5: str | None = None,
    ) -> StagedAsset | None:
        """Safely reopen verified CAS bytes as staging for reconciliation."""

        normalized = _normal_hash(sha256, 64, "SHA-256")
        normalized_md5 = _normal_hash(expected_md5, 32, "MD5")
        assert normalized is not None
        target_dir_fd = staging_fd = target_fd = -1
        name = ""
        try:
            try:
                target_dir_fd = _open_relative_directory(
                    self.media.fd,
                    ["sha256", normalized[:2], normalized[2:4]],
                    create=False,
                )
            except FileNotFoundError:
                return None
            self._verify_cas_directory_binding(target_dir_fd, normalized)
            try:
                target_fd = os.open(
                    normalized,
                    _flags("O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"),
                    dir_fd=target_dir_fd,
                )
            except FileNotFoundError:
                return None
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise StorageIntegrityError("CAS target is a symbolic link") from error
                raise
            before = os.fstat(target_fd)
            if not _regular(before):
                raise StorageIntegrityError("CAS target is not a regular file")
            try:
                size, calculated_sha256, calculated_md5 = _stream_hash(
                    target_fd, max_bytes=self.limits.max_bytes
                )
            except LimitExceededError as error:
                raise StorageIntegrityError(
                    "existing CAS target exceeds the configured byte limit"
                ) from error
            after = os.fstat(target_fd)
            if (
                not _same_source(before, after, size)
                or calculated_sha256 != normalized
                or (expected_size is not None and size != expected_size)
                or (normalized_md5 is not None and calculated_md5 != normalized_md5)
            ):
                raise StorageIntegrityError("existing CAS target has corrupt bytes")
            staging_fd = self._staging_fd()
            for _ in range(16):
                candidate = f"reconcile-{secrets.token_hex(16)}"
                try:
                    self._link_staged_fd(target_fd, staging_fd, candidate)
                    name = candidate
                    break
                except FileExistsError:
                    continue
            if not name:
                raise AssetStorageError("could not allocate reconciliation staging")
            self._owned_staging.add(name)
            self._staged_fds[name] = target_fd
            staged = StagedAsset(
                name,
                "remote:reconciled.cas",
                size,
                calculated_sha256,
                calculated_md5,
                target_fd,
            )
            self._verify_staging_name(staged, staging_fd)
            os.fsync(staging_fd)
            target_fd = -1
            return staged
        except BaseException:
            if name and target_fd >= 0:
                self._cleanup_staging_name(
                    name,
                    staging_fd=staging_fd if staging_fd >= 0 else None,
                    expected_fd=target_fd,
                )
                self._staged_fds.pop(name, None)
            raise
        finally:
            if target_fd >= 0:
                os.close(target_fd)
            if staging_fd >= 0:
                os.close(staging_fd)
            if target_dir_fd >= 0:
                os.close(target_dir_fd)

    def _open_cas_directory(self, sha256: str) -> tuple[int, str]:
        normalized = _normal_hash(sha256, 64, "SHA-256")
        assert normalized is not None
        prefix_fd = _open_relative_directory(
            self.media.fd, ["sha256", normalized[:2], normalized[2:4]], create=True
        )
        return prefix_fd, normalized

    def _verify_cas_directory_binding(self, target_dir_fd: int, normalized: str) -> None:
        """Confirm the visible CAS components still resolve to the opened inode."""

        try:
            visible_fd = _open_relative_directory(
                self.media.fd,
                ["sha256", normalized[:2], normalized[2:4]],
                create=False,
            )
        except OSError as error:
            raise StorageIntegrityError("managed CAS directory path changed") from error
        try:
            if _identity(os.fstat(visible_fd)) != _identity(os.fstat(target_dir_fd)):
                raise StorageIntegrityError("managed CAS directory path changed")
        finally:
            os.close(visible_fd)

    def _verify_target(
        self,
        target_fd: int,
        expected: StagedAsset,
        *,
        expected_identity: tuple[int, int] | None = None,
    ) -> None:
        info = os.fstat(target_fd)
        if not _regular(info):
            raise StorageIntegrityError("CAS target is not a regular file")
        if expected_identity is not None and _identity(info) != expected_identity:
            raise StorageIntegrityError("CAS target is not the published staging inode")
        before = info
        try:
            size, sha256, _md5 = _stream_hash(target_fd, max_bytes=self.limits.max_bytes)
        except LimitExceededError as error:
            raise StorageIntegrityError(
                "existing CAS target exceeds the configured byte limit"
            ) from error
        after = os.fstat(target_fd)
        if not _same_source(before, after, size) or (size, sha256) != (
            expected.size,
            expected.sha256,
        ):
            raise StorageIntegrityError("existing CAS target has corrupt or conflicting bytes")

    @staticmethod
    def _link_staged_fd(staged_fd: int, target_dir_fd: int, target_name: str) -> None:
        """Hard-link an already-open staging inode without resolving its name."""

        if _LINKAT is None:  # pragma: no cover - guarded by _require_capabilities
            raise CapabilityError("descriptor-bound hard-link publication is unavailable")
        result = _LINKAT(
            staged_fd,
            b"",
            target_dir_fd,
            os.fsencode(target_name),
            _AT_EMPTY_PATH,
        )
        if result == 0:
            return
        error_number = ctypes_get_errno()
        error = OSError(error_number, os.strerror(error_number))
        if error_number in {errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EINVAL}:
            raise CapabilityError(
                "descriptor-bound hard-link publication is unavailable"
            ) from error
        raise error

    def publish_staged(self, staged: StagedAsset) -> tuple[str, bool]:
        """Publish/reuse staged bytes and return ``(CAS path, was_new)``."""

        target_dir_fd = -1
        staging_fd = -1
        staged_fd = staged.fd
        try:
            staged_fd = self._staged_fd(staged)
            self._verify_staging(staged)
            staging_fd = self._staging_fd()
            self._verify_staging_name(staged, staging_fd)
            target_dir_fd, normalized = self._open_cas_directory(staged.sha256)
            target_name = normalized
            self._verify_cas_directory_binding(target_dir_fd, normalized)
            try:
                target_fd = os.open(
                    target_name,
                    _flags("O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"),
                    dir_fd=target_dir_fd,
                )
            except FileNotFoundError:
                target_fd = -1
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise StorageIntegrityError("CAS target is a symbolic link") from error
                raise
            if target_fd >= 0:
                try:
                    self._verify_target(target_fd, staged)
                finally:
                    os.close(target_fd)
                self._cleanup_staging_name(
                    staged.staging_name, staging_fd=staging_fd, expected_fd=staged_fd
                )
                self._close_staged_fd(staged)
                return self.cas_relative_path(normalized), False
            try:
                self._link_staged_fd(staged_fd, target_dir_fd, target_name)
            except FileExistsError:
                try:
                    target_fd = os.open(
                        target_name,
                        _flags("O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"),
                        dir_fd=target_dir_fd,
                    )
                    try:
                        self._verify_target(target_fd, staged)
                    finally:
                        os.close(target_fd)
                except OSError as error:
                    if error.errno == errno.ELOOP:
                        raise StorageIntegrityError("CAS target is a symbolic link") from error
                    raise StorageIntegrityError(
                        "CAS target appeared with conflicting bytes"
                    ) from error
                self._cleanup_staging_name(
                    staged.staging_name, staging_fd=staging_fd, expected_fd=staged_fd
                )
                self._close_staged_fd(staged)
                return self.cas_relative_path(normalized), False
            # The descriptor-bound link above cannot be redirected by a race,
            # but a replacement staging name still invalidates this run.  Do
            # not report success when the owned pathname was substituted.
            self._verify_staging_name(staged, staging_fd)
            self._verify_cas_directory_binding(target_dir_fd, normalized)
            try:
                target_fd = os.open(
                    target_name,
                    _flags("O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"),
                    dir_fd=target_dir_fd,
                )
            except OSError as error:
                raise StorageIntegrityError(
                    "published CAS target could not be reopened safely"
                ) from error
            try:
                self._verify_target(
                    target_fd,
                    staged,
                    expected_identity=_identity(os.fstat(staged_fd)),
                )
            finally:
                os.close(target_fd)
            os.fsync(target_dir_fd)
            self._cleanup_staging_name(
                staged.staging_name, staging_fd=staging_fd, expected_fd=staged_fd
            )
            self._close_staged_fd(staged)
            return self.cas_relative_path(normalized), True
        except BaseException as error:
            # This only ever touches a staging name that this service generated.
            _attach_staged_evidence(error, staged)
            if staging_fd >= 0:
                self._cleanup_staging_name(
                    staged.staging_name,
                    staging_fd=staging_fd,
                    expected_fd=staged_fd,
                )
            self._close_staged_fd(staged)
            raise
        finally:
            if staging_fd >= 0:
                os.close(staging_fd)
            if target_dir_fd >= 0:
                os.close(target_dir_fd)

    publish = publish_staged

    def adopt(
        self,
        relative_path: str | os.PathLike[str],
        *,
        legacy_sha256: str | None = None,
        legacy_md5: str | None = None,
    ) -> AdoptionResult:
        """Stage, verify, inspect, and publish one source file."""

        source_text = "/".join(_safe_components(relative_path))
        staged: StagedAsset | None = None
        try:
            staged = self.stage_source(source_text)
            expected_sha = _normal_hash(legacy_sha256, 64, "SHA-256")
            expected_md5 = _normal_hash(legacy_md5, 32, "MD5")
            if expected_sha is not None and expected_sha != staged.sha256:
                raise HashMismatchError("recalculated SHA-256 disagrees with the legacy value")
            if expected_md5 is not None and expected_md5 != staged.md5:
                raise HashMismatchError("recalculated MD5 disagrees with the legacy value")
            inspection = self.inspect_staged(staged)
            cas_path, created = self.publish_staged(staged)
            return AdoptionResult(
                "adopted_exact_only"
                if inspection.exact_only
                else ("adopted" if created else "existing"),
                source_text,
                None,
                cas_path,
                inspection,
                created,
            )
        except BaseException as error:
            if staged is not None:
                _attach_staged_evidence(error, staged)
                self.cleanup_staging(staged)
            raise


@contextmanager
def opened_storage(
    source_root: str | os.PathLike[str],
    media_root: str | os.PathLike[str],
    *,
    limits: InspectionLimits | None = None,
) -> Iterator[AssetStorage]:
    """Convenience context manager for callers that do not need a service object."""

    storage = AssetStorage(source_root, media_root, limits=limits)
    try:
        yield storage
    finally:
        storage.close()


__all__ = [
    "AdoptionResult",
    "AssetStorage",
    "AssetStorageError",
    "CapabilityError",
    "ExactEvidence",
    "HashMismatchError",
    "InspectionError",
    "InspectionLimits",
    "LimitExceededError",
    "Limits",
    "LockError",
    "ManagedRootLock",
    "OpenedSource",
    "RootHandle",
    "RootOverlapError",
    "SourceChangedError",
    "StagedAsset",
    "StorageIntegrityError",
    "UnsafePathError",
    "opened_storage",
]
