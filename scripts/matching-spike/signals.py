"""Perceptual and exact-hash signal helpers for matching research.

Research-only module living beside the harness, deliberately outside the
media_catalog package: catalog hashes are identification metadata, and no
similarity mechanism belongs in product surfaces unless a generic,
evidence-backed one is proven. Perceptual hashes of different sizes are
different coordinate systems and are never compared against each other.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PIL import Image

try:
    import imagehash as _imagehash
except ImportError:  # pragma: no cover - declared runtime dependency
    _imagehash: Any = None


_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


class SimilarityError(ValueError):
    """Invalid digest or fingerprint input to a similarity helper."""


def is_valid_hex_digest(value: object) -> bool:
    """Return True when value is a non-empty, even-length hexadecimal string."""
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    if not normalized or len(normalized) % 2 != 0:
        return False
    return all(character in _HEX_DIGITS for character in normalized)


def normalize_hex_digest(value: str) -> str:
    """Return the lowercased, whitespace-stripped hex digest.

    Raises SimilarityError for empty, odd-length, or non-hexadecimal input.
    """

    if not is_valid_hex_digest(value):
        raise SimilarityError(f"invalid hex digest: {value!r}")
    return value.strip().lower()


def hamming_distance(left: str, right: str) -> int:
    """Return the Hamming distance between two equal-length hex digests.

    Comparison is case-insensitive; digests of different lengths are never
    comparable and raise SimilarityError, as are empty or non-hex inputs.
    """

    first = normalize_hex_digest(left)
    second = normalize_hex_digest(right)
    if len(first) != len(second):
        raise SimilarityError("cannot compare hex digests of different lengths")
    return bin(int(first, 16) ^ int(second, 16)).count("1")


def phash_from_image(image: Image.Image, *, size: int = 8) -> str:
    """Return the perceptual hash of a loaded image as lowercase hex.

    The caller passes a loaded single-frame (or first-frame) image, mirroring
    the inspection pipeline. size is the imagehash hash_size: 8 yields a
    64-bit digest (16 hex characters), 16 yields 256 bits (64 characters).
    Raises RuntimeError when imagehash is unavailable — a report function
    must not silently degrade to exact-only.
    """

    if _imagehash is None:  # pragma: no cover - declared runtime dependency
        raise RuntimeError("imagehash is unavailable; perceptual hashing is disabled")
    if size < 1:
        raise ValueError("perceptual hash size must be positive")
    return str(_imagehash.phash(image, hash_size=size)).lower()


def phashes_from_image(image: Image.Image, sizes: Sequence[int] = (8, 16)) -> dict[int, str]:
    """Return perceptual hashes at several sizes keyed by size.

    Hashes of different sizes are never comparable to each other; callers
    must keep them keyed, as this mapping does.
    """

    return {size: phash_from_image(image, size=size) for size in sizes}


def hashes_equal(left: str | None, right: str | None) -> bool:
    """Return True when two exact hashes are equal, case-insensitively.

    None on either side means the value is unknown and the hashes are not
    equal; invalid digests likewise compare unequal instead of raising, so a
    read-only report never fails on unexpected stored values.
    """

    if left is None or right is None:
        return False
    try:
        return normalize_hex_digest(left) == normalize_hex_digest(right)
    except SimilarityError:
        return False


def aspect_ratio(width: int | None, height: int | None) -> float | None:
    """Return width divided by height, or None when either value is missing or non-positive."""

    if width is None or height is None or width <= 0 or height <= 0:
        return None
    return width / height


def aspect_ratio_close(left: float | None, right: float | None, *, tolerance: float = 0.05) -> bool:
    """Return True when two aspect ratios differ by at most a relative tolerance.

    Two unknown ratios (None on either side) are not close: missing evidence
    is never affirmative.
    """

    if left is None or right is None or left <= 0 or right <= 0:
        return False
    return abs(left - right) / min(left, right) <= tolerance


def same_dimensions(
    width_a: int | None,
    height_a: int | None,
    width_b: int | None,
    height_b: int | None,
) -> bool:
    """Return True when both dimensions are present and identical."""

    if width_a is None or height_a is None or width_b is None or height_b is None:
        return False
    return width_a == width_b and height_a == height_b
