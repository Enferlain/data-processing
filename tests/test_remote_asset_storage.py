from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

import pytest
from PIL import Image

import media_catalog.storage.cas as storage_module
from media_catalog.storage.cas import (
    AssetStorage,
    InspectionLimits,
    LimitExceededError,
    SourceChangedError,
    StorageIntegrityError,
    UnsafePathError,
)


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (9, 7), color=(20, 40, 60)).save(output, format="PNG")
    return output.getvalue()


def _remote_storage(
    tmp_path: Path,
    *,
    name: str = "managed",
    limits: InspectionLimits | None = None,
) -> AssetStorage:
    managed = tmp_path / name
    managed.mkdir()
    return AssetStorage.for_remote(managed, limits=limits)


def test_remote_session_stages_inspects_and_publishes_through_existing_cas(
    tmp_path: Path,
) -> None:
    payload = _png()
    storage = _remote_storage(tmp_path)
    try:
        session = storage.begin_remote_staging("a" * 64)
        session.write(payload[:17])
        session.write(payload[17:])
        state = session.checkpoint()
        assert state.byte_count == len(payload)
        assert state.prefix_sha256 == hashlib.sha256(payload).hexdigest()
        staged = session.finalize(source_label="remote.png")
        inspection = storage.inspect_staged(staged)
        assert inspection.mime_type == "image/png"
        assert inspection.width == 9
        assert inspection.height == 7
        relative_path, created = storage.publish_staged(staged)
        assert created is True
        assert (tmp_path / "managed" / relative_path).read_bytes() == payload
    finally:
        storage.close()


def test_existing_cas_can_be_reconciled_only_after_exact_verification(
    tmp_path: Path,
) -> None:
    payload = _png()
    sha256 = hashlib.sha256(payload).hexdigest()
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    storage = _remote_storage(tmp_path)
    try:
        session = storage.begin_remote_staging("f" * 64)
        session.write(payload)
        relative_path, _created = storage.publish_staged(
            session.finalize(source_label="remote.png")
        )

        reconciled = storage.stage_existing_cas(
            sha256, expected_size=len(payload), expected_md5=md5
        )
        assert reconciled is not None
        inspection = storage.inspect_staged(reconciled)
        assert (inspection.sha256, inspection.width, inspection.height) == (sha256, 9, 7)
        reused_path, created = storage.publish_staged(reconciled)
        assert (reused_path, created) == (relative_path, False)

        assert storage.stage_existing_cas("0" * 64) is None
        target = tmp_path / "managed" / relative_path
        target.write_bytes(b"corrupt")
        with pytest.raises(StorageIntegrityError, match="corrupt"):
            storage.stage_existing_cas(sha256)
    finally:
        storage.close()


def test_remote_partial_detaches_and_reopens_only_after_prefix_verification(
    tmp_path: Path,
) -> None:
    first = _remote_storage(tmp_path)
    session = first.begin_remote_staging("b" * 64, max_bytes=100)
    session.write(b"first-")
    state = session.detach()
    first.close()

    second = AssetStorage.for_remote(tmp_path / "managed")
    try:
        resumed = second.reopen_remote_staging(
            state,
            expected_request_identity="b" * 64,
            max_bytes=100,
        )
        resumed.write(b"second")
        staged = resumed.finalize(source_label="remote.bin")
        assert staged.size == len(b"first-second")
        assert staged.sha256 == hashlib.sha256(b"first-second").hexdigest()
        assert staged.md5 == hashlib.md5(
            b"first-second", usedforsecurity=False
        ).hexdigest()
    finally:
        second.close()


def test_remote_partial_reopen_rejects_root_request_size_and_symlink_changes(
    tmp_path: Path,
) -> None:
    storage = _remote_storage(tmp_path)
    session = storage.begin_remote_staging("c" * 64)
    session.write(b"partial")
    state = session.detach()
    storage.close()

    wrong_root = _remote_storage(tmp_path, name="other-managed")
    try:
        with pytest.raises(StorageIntegrityError, match="different managed root"):
            wrong_root.reopen_remote_staging(state, expected_request_identity="c" * 64)
    finally:
        wrong_root.close()

    storage = AssetStorage.for_remote(tmp_path / "managed")
    try:
        with pytest.raises(SourceChangedError, match="different request"):
            storage.reopen_remote_staging(state, expected_request_identity="d" * 64)
        partial_path = tmp_path / "managed" / "staging" / state.staging_name
        with partial_path.open("ab") as stream:
            stream.write(b"growth")
        with pytest.raises(StorageIntegrityError, match="size changed"):
            storage.reopen_remote_staging(state, expected_request_identity="c" * 64)

        partial_path.write_bytes(b"partial")
        real_path = partial_path.with_name(f"{state.staging_name}.real")
        partial_path.rename(real_path)
        partial_path.symlink_to(real_path)
        with pytest.raises(UnsafePathError, match="symbolic link"):
            storage.reopen_remote_staging(state, expected_request_identity="c" * 64)
    finally:
        storage.close()


def test_remote_checkpoint_fails_closed_on_staging_name_substitution(tmp_path: Path) -> None:
    storage = _remote_storage(tmp_path)
    session = storage.begin_remote_staging("e" * 64)
    session.write(b"owned bytes")
    staging = tmp_path / "managed" / "staging"
    original = staging / session.staging_name
    moved = staging / f"{session.staging_name}.moved"
    original.rename(moved)
    original.write_bytes(b"replacement")
    try:
        with pytest.raises(StorageIntegrityError, match="pathname"):
            session.checkpoint()
        session.close()
        assert original.read_bytes() == b"replacement"
        assert moved.read_bytes() == b"owned bytes"
    finally:
        original.unlink(missing_ok=True)
        moved.unlink(missing_ok=True)
        storage.close()


def test_remote_limits_and_injected_short_write_leave_bounded_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = _remote_storage(
        tmp_path,
        limits=InspectionLimits(max_bytes=8, max_pixels=100, max_frames=1),
    )
    session = storage.begin_remote_staging("f" * 64, max_bytes=8)
    try:
        with pytest.raises(LimitExceededError):
            session.write(b"123456789")
        assert session.checkpoint().byte_count == 0

        monkeypatch.setattr(storage_module.os, "write", lambda _fd, _data: 0)
        with pytest.raises(OSError, match="short write"):
            session.write(b"1234")
        assert session.checkpoint().byte_count == 0
    finally:
        session.close()
        storage.close()


def test_quarantine_is_descriptor_bound_bounded_and_directory_durable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"quarantine evidence"
    fsynced: list[tuple[int, int]] = []
    original_fsync = storage_module.os.fsync

    def record_fsync(fd: int) -> None:
        info = os.fstat(fd)
        fsynced.append((info.st_dev, info.st_ino))
        original_fsync(fd)

    monkeypatch.setattr(storage_module.os, "fsync", record_fsync)
    storage = _remote_storage(tmp_path)
    session = storage.begin_remote_staging("1" * 64)
    session.write(payload)
    staged = session.finalize(source_label="remote.bin")
    try:
        with pytest.raises(LimitExceededError):
            storage.quarantine_staged(staged, reason="hash_mismatch", max_bytes=1)
        result = storage.quarantine_staged(
            staged,
            reason="hash_mismatch",
            max_bytes=len(payload),
        )
        quarantine_path = tmp_path / "managed" / "quarantine" / result.quarantine_name
        assert result.size == len(payload)
        assert quarantine_path.read_bytes() == payload
        quarantine_stat = quarantine_path.parent.stat()
        quarantine_info = (quarantine_stat.st_dev, quarantine_stat.st_ino)
        assert quarantine_info in fsynced
    finally:
        storage.cleanup_staging(staged)
        storage.close()


def test_quarantine_directory_substitution_is_never_followed(tmp_path: Path) -> None:
    storage = _remote_storage(tmp_path)
    session = storage.begin_remote_staging("2" * 64)
    session.write(b"evidence")
    staged = session.finalize(source_label="remote.bin")
    managed = tmp_path / "managed"
    outside = tmp_path / "outside"
    outside.mkdir()
    (managed / "quarantine").rename(managed / "old-quarantine")
    (managed / "quarantine").symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(UnsafePathError):
            storage.quarantine_staged(staged, reason="invalid_content", max_bytes=100)
        assert not list(outside.iterdir())
    finally:
        storage.cleanup_staging(staged)
        storage.close()
