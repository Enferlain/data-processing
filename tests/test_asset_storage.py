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
    ExactEvidence,
    HashMismatchError,
    InspectionError,
    InspectionLimits,
    LimitExceededError,
    LockError,
    RootOverlapError,
    SourceChangedError,
    StorageIntegrityError,
    UnsafePathError,
)


def _png(size: tuple[int, int] = (12, 8), *, color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color=color).save(output, format="PNG")
    return output.getvalue()


def _storage(tmp_path: Path, *, limits: InspectionLimits | None = None) -> AssetStorage:
    source = tmp_path / "source"
    managed = tmp_path / "managed"
    source.mkdir()
    managed.mkdir()
    return AssetStorage(source, managed, limits=limits)


@pytest.mark.parametrize(
    ("image_format", "mime_type"),
    (("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp"), ("GIF", "image/gif")),
)
def test_supported_raster_formats_record_detected_mime_and_algorithm(
    tmp_path: Path, image_format: str, mime_type: str
) -> None:
    storage = _storage(tmp_path)
    try:
        output = io.BytesIO()
        Image.new("RGB", (5, 4), color=(10, 20, 30)).save(output, format=image_format)
        (tmp_path / "source" / "image.data").write_bytes(output.getvalue())
        result = storage.adopt("image.data")
        assert result.inspection is not None
        assert result.inspection.mime_type == mime_type
        assert result.inspection.phash_algorithm == "imagehash.phash"
        assert result.inspection.phash_version == "1"
    finally:
        storage.close()


def test_raster_is_detected_from_bytes_and_published_without_extension(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    try:
        source = tmp_path / "source" / "photo.dat"
        source.write_bytes(_png())
        result = storage.adopt("photo.dat")

        assert result.status == "adopted"
        assert result.inspection is not None
        assert result.inspection.mime_type == "image/png"
        assert result.inspection.width == 12
        assert result.inspection.height == 8
        assert result.inspection.phash_algorithm == "imagehash.phash"
        assert result.inspection.phash_version == "1"
        assert result.relative_path is not None
        assert (tmp_path / "managed" / result.relative_path).read_bytes() == source.read_bytes()
    finally:
        storage.close()


def test_valid_non_raster_is_exact_only(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    try:
        payload = b"not a raster format\x00\x01"
        (tmp_path / "source" / "data.bin").write_bytes(payload)
        result = storage.adopt("data.bin")
        assert result.status == "adopted_exact_only"
        assert result.inspection is not None and result.inspection.exact_only
        assert result.inspection.mime_type == "application/octet-stream"
        assert result.inspection.phash is None
    finally:
        storage.close()


def test_hash_mismatch_happens_before_inspection_and_retains_safe_residue(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    try:
        (tmp_path / "source" / "image.png").write_bytes(_png())
        with pytest.raises(HashMismatchError):
            storage.adopt("image.png", legacy_sha256="0" * 64)
        assert len(list((tmp_path / "managed" / "staging").iterdir())) == 1
        assert not list((tmp_path / "managed" / "sha256").rglob("*"))
    finally:
        storage.close()


def test_hash_mismatch_exposes_bounded_staged_exact_evidence(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    payload = _png()
    source = tmp_path / "source" / "image.png"
    source.write_bytes(payload)
    try:
        with pytest.raises(HashMismatchError) as raised:
            storage.adopt("image.png", legacy_sha256="0" * 64)
        error = raised.value
        assert error.staged is not None
        assert error.staged.size == len(payload)
        assert error.staged.sha256 == hashlib.sha256(payload).hexdigest()
        assert error.staged.md5 == hashlib.md5(payload, usedforsecurity=False).hexdigest()
        assert error.exact_evidence == ExactEvidence(
            len(payload), error.staged.sha256, error.staged.md5
        )
        assert len(list((tmp_path / "managed" / "staging").iterdir())) == 1
    finally:
        storage.close()


def test_malformed_raster_and_hard_limits_are_rejected(tmp_path: Path) -> None:
    storage = _storage(tmp_path, limits=InspectionLimits(max_bytes=32, max_pixels=20, max_frames=1))
    try:
        (tmp_path / "source" / "too-big.bin").write_bytes(b"x" * 33)
        with pytest.raises(LimitExceededError):
            storage.adopt("too-big.bin")

        (tmp_path / "source" / "bad.png").write_bytes(b"not png")
        with pytest.raises(InspectionError):
            storage.adopt("bad.png")

        (tmp_path / "source" / "large.png").write_bytes(_png((8, 8)))
        with pytest.raises(LimitExceededError):
            storage.adopt("large.png")
    finally:
        storage.close()


def test_animated_raster_frame_limit_is_enforced(tmp_path: Path) -> None:
    storage = _storage(tmp_path, limits=InspectionLimits(max_frames=1))
    try:
        output = io.BytesIO()
        frames = [Image.new("RGB", (2, 2), color=color) for color in ("red", "blue")]
        frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:])
        (tmp_path / "source" / "animated.gif").write_bytes(output.getvalue())
        with pytest.raises(LimitExceededError):
            storage.adopt("animated.gif")
    finally:
        storage.close()


def test_frame_probe_does_not_read_unbounded_frame_metadata(tmp_path: Path) -> None:
    storage = _storage(tmp_path, limits=InspectionLimits(max_frames=2))
    try:
        seen_frames: list[int] = []

        class BoundedFrames:
            def seek(self, frame: int) -> None:
                seen_frames.append(frame)
                if frame >= 2:
                    raise EOFError

        result = storage._bounded_frame_count(BoundedFrames())  # type: ignore[arg-type]
        assert result == 2
        assert max(seen_frames) <= 2
        assert 2 in seen_frames
    finally:
        storage.close()


def test_publication_rejects_staging_name_substitution(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    payload = _png()
    source = tmp_path / "source" / "image.png"
    source.write_bytes(payload)
    try:
        staged = storage.stage_source("image.png")
        staging = tmp_path / "managed" / "staging"
        original = staging / staged.staging_name
        moved = staging / f"{staged.staging_name}.moved"
        original.rename(moved)
        original.write_bytes(b"substituted bytes")

        with pytest.raises(StorageIntegrityError):
            storage.publish_staged(staged)
        assert not list((tmp_path / "managed" / "sha256").rglob("*"))
        assert original.read_bytes() == b"substituted bytes"
        assert moved.exists()
    finally:
        with storage_module.suppress(FileNotFoundError):
            (tmp_path / "managed" / "staging" / staged.staging_name).unlink()
            (tmp_path / "managed" / "staging" / f"{staged.staging_name}.moved").unlink()
        storage.close()


def test_cleanup_never_unlinks_through_a_raced_staging_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = _storage(tmp_path)
    payload = _png()
    (tmp_path / "source" / "image.png").write_bytes(payload)
    staged = storage.stage_source("image.png")
    staging_path = tmp_path / "managed" / "staging" / staged.staging_name
    unlink_called = False
    original_unlink = storage_module.os.unlink

    def replace_inside_unlink(path: str, *, dir_fd: int | None = None) -> None:
        nonlocal unlink_called
        unlink_called = True
        original_unlink(path, dir_fd=dir_fd)
        replacement_fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=dir_fd,
        )
        os.write(replacement_fd, b"replacement")
        os.close(replacement_fd)
        original_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(storage_module.os, "unlink", replace_inside_unlink)
    try:
        storage.cleanup_staging(staged)
        assert unlink_called is False
        assert staging_path.read_bytes() == payload
    finally:
        monkeypatch.setattr(storage_module.os, "unlink", original_unlink)
        staging_path.unlink()
        storage.close()


def test_new_directory_durability_flushes_child_before_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    managed = tmp_path / "managed"
    source.mkdir()
    managed.mkdir()
    source_file = source / "payload.bin"
    source_file.write_bytes(b"durable")
    fsync_order: list[tuple[int, int]] = []
    original_fsync = storage_module.os.fsync

    def record_fsync(fd: int) -> None:
        info = os.fstat(fd)
        fsync_order.append((info.st_dev, info.st_ino))
        original_fsync(fd)

    monkeypatch.setattr(storage_module.os, "fsync", record_fsync)
    storage = AssetStorage(source, managed)
    try:
        before_publish = len(fsync_order)
        result = storage.adopt("payload.bin")
        assert result.relative_path is not None
        assert len(fsync_order) > before_publish
        target_dir = managed / Path(result.relative_path).parent
        target_identity = (target_dir.stat().st_dev, target_dir.stat().st_ino)
        # The target directory flush is the durability barrier immediately
        # before staging cleanup; it must be observed for the newly-created
        # hash-prefix directory.
        assert target_identity in fsync_order[before_publish:]
    finally:
        storage.close()


def test_source_paths_reject_traversal_symlink_and_non_regular(tmp_path: Path) -> None:
    source = tmp_path / "source"
    managed = tmp_path / "managed"
    source.mkdir()
    managed.mkdir()
    (source / "good.bin").write_bytes(b"ok")
    (source / "link.bin").symlink_to(source / "good.bin")
    (source / "folder").mkdir()
    storage = AssetStorage(source, managed)
    try:
        for path in ("../outside", "/etc/passwd", "link.bin", "folder"):
            with pytest.raises(UnsafePathError):
                storage.open_source(path)
    finally:
        storage.close()


def test_source_change_during_streaming_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = _storage(tmp_path)
    source = tmp_path / "source" / "changing.bin"
    source.write_bytes(b"original bytes")
    original_read = os.read
    changed = False

    def changing_read(fd: int, size: int) -> bytes:
        nonlocal changed
        chunk = original_read(fd, size)
        if not changed:
            changed = True
            source.write_bytes(b"changed bytes with a different size")
        return chunk

    monkeypatch.setattr(os, "read", changing_read)
    try:
        with pytest.raises(SourceChangedError):
            storage.stage_source("changing.bin")
        assert len(list((tmp_path / "managed" / "staging").iterdir())) == 1
    finally:
        storage.close()


def test_substituted_source_component_is_not_followed(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.bin").write_bytes(b"secret")
    (source / "nested").mkdir()
    (source / "nested" / "secret.bin").write_bytes(b"original")
    (source / "nested").rename(source / "old-nested")
    (source / "nested").symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(UnsafePathError):
            storage.open_source("nested/secret.bin")
    finally:
        storage.close()


def test_overlapping_roots_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "managed").mkdir()
    with pytest.raises(RootOverlapError):
        AssetStorage(source, source / "managed")


def test_duplicate_bytes_reuse_target_and_corrupt_target_is_never_overwritten(
    tmp_path: Path,
) -> None:
    storage = _storage(tmp_path)
    try:
        payload = _png()
        (tmp_path / "source" / "a.bin").write_bytes(payload)
        (tmp_path / "source" / "b.bin").write_bytes(payload)
        first = storage.adopt("a.bin")
        second = storage.adopt("b.bin")
        assert first.relative_path == second.relative_path
        assert second.status == "existing"

        assert first.relative_path is not None
        target = tmp_path / "managed" / first.relative_path
        target.write_bytes(b"corrupt")
        with pytest.raises(StorageIntegrityError):
            storage.adopt("a.bin")
        assert target.read_bytes() == b"corrupt"
    finally:
        storage.close()


def test_destination_symlink_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    managed = tmp_path / "managed"
    source.mkdir()
    managed.mkdir()
    (source / "a.bin").write_bytes(b"bytes")
    (managed / "sha256").symlink_to(source, target_is_directory=True)
    with pytest.raises(UnsafePathError):
        AssetStorage(source, managed)


def test_managed_lock_is_exclusive_and_os_released(tmp_path: Path) -> None:
    first = _storage(tmp_path)
    second = AssetStorage(tmp_path / "source", tmp_path / "managed")
    try:
        with first.lock(), pytest.raises(LockError), second.lock():
            pass
        with second.lock():
            pass
    finally:
        first.close()
        second.close()


def test_cas_path_uses_only_sha256() -> None:
    digest = hashlib.sha256(b"bytes").hexdigest()
    assert AssetStorage.cas_path(digest) == f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"
