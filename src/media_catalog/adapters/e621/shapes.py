"""Shape validation and query-render helpers for the e621 adapter.

Extracted from ``adapter.py`` unchanged (2026-11-20 file-size survey): the
module-level validators that guard e621 wire shapes before persistence and
render lookup query text before transport.  The adapter class imports them;
nothing here knows about the adapter instance.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Mapping
from typing import Any

from media_catalog.adapters.contracts import (
    AdapterFailure,
    AdapterOutcome,
    LookupQueryMaterial,
    LookupStrategy,
)
from media_catalog.links import recognize_url

_MAX_TARGET_LENGTH = 500
_MAX_LOOKUP_TEXT = 200


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, str) and entry]


def _nonempty_target(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"e621 {name} must be non-empty text")
    value = value.strip()
    if len(value) > _MAX_TARGET_LENGTH or any(ord(char) < 32 for char in value):
        raise ValueError(f"e621 {name} must be bounded text without control characters")
    return value


def _source_values(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "lookup post sources are malformed")
    return list(value)


def _proven_external_ids(sources: list[str]) -> dict[str, str]:
    """Extract only stable external IDs explicitly proven by returned source URLs."""

    pixiv_ids: set[str] = set()
    for source in sources:
        reference = recognize_url(source).reference
        if (
            reference is not None
            and reference.platform == "pixiv"
            and reference.object_kind == "post"
            and reference.identifier_kind == "stable_id"
            and reference.native_id.isdecimal()
        ):
            pixiv_ids.add(reference.native_id)
    return {"pixiv_id": next(iter(pixiv_ids))} if len(pixiv_ids) == 1 else {}


def _bounded_lookup_text(value: str, name: str) -> None:
    """Defensive check that lookup query text is bounded and non-control.

    ``LookupQueryMaterial`` already enforces a length ceiling and rejects control
    characters; this guards the render path independently so a future caller that
    constructs material differently still fails closed before transport.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"e621 {name} must be non-empty text")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"e621 {name} must not contain control characters")
    if len(value) > _MAX_LOOKUP_TEXT:
        raise ValueError(f"e621 {name} exceeds {_MAX_LOOKUP_TEXT} characters")


def _exact_source_lookup_text(value: str) -> None:
    _bounded_lookup_text(value, "source post URL")
    if "*" in value or any(char.isspace() for char in value):
        raise ValueError("e621 source post URL must be one exact source token")


def _external_post_sources(material: LookupQueryMaterial, value: str) -> tuple[str, ...]:
    """Render the e621 exact source queries for an external post-id material.

    e621 exposes no per-platform external-id metatag; its only exact match for a
    foreign post is the ``source:`` metatag against the source URL as the
    uploader entered (or e621 normalized) it.  Pixiv artwork sources appear on
    e621 in both the bare and the ``/en/`` localized spelling, and one does not
    substring-match the other, so every known spelling is tried, each as its own
    bounded request.  Any other platform (or a non-numeric id) fails closed
    before any request.
    """

    platform = material.platform
    if platform == "pixiv":
        if not value.isdecimal() or int(value) < 1:
            raise ValueError("external pixiv post id must be a positive numeric id")
        identifier = int(value)
        return (
            f"https://www.pixiv.net/artworks/{identifier}",
            f"https://www.pixiv.net/en/artworks/{identifier}",
        )
    raise ValueError(f"e621 lookup does not support external platform {platform!r}")


def _lookup_query_tokens(material: LookupQueryMaterial) -> tuple[str, ...]:
    """Expand a lookup material into the exact query tokens the adapter tries.

    Most strategies iterate the planner's material values directly (URL aliases
    for ``source_post_url``); an external post-id material is a stable foreign
    id, which e621 can only reach through the ``source:`` metatag, so it expands
    into that id's known pixiv source spellings.  Continuations walk the same
    token sequence, so ``alias_index`` stays a valid cursor for every strategy.
    """

    if material.strategy is LookupStrategy.EXTERNAL_POST_ID:
        return tuple(
            source
            for value in material.values
            for source in _external_post_sources(material, value)
        )
    return material.values


def _mime_type(extension: object) -> str | None:
    if not isinstance(extension, str) or not extension:
        return None
    return mimetypes.guess_type(f"file.{extension}")[0]


def _duration_ms(value: object) -> int | None:
    """Convert e621's top-level seconds float to whole milliseconds."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post duration is malformed")
    return round(float(value) * 1000)


def _variant_availability(url: str | None, deleted: bool) -> str:
    if deleted:
        return "deleted"
    return "available" if url is not None else "unavailable"


def _validate_post_shapes(body: Mapping[str, Any]) -> None:
    description = body.get("description")
    if description is not None and not isinstance(description, str):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post description is malformed")
    locked_tags = body.get("locked_tags")
    if locked_tags is not None and not isinstance(locked_tags, list):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post locked tags are malformed")
    for name in ("fav_count", "comment_count"):
        value = body.get(name)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, f"post {name} is malformed")
    score = body.get("score")
    if score is not None:
        if not isinstance(score, dict):
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post score is malformed")
        for name in ("up", "down", "total"):
            value = score.get(name)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post score is malformed")
            # Live captures (2026-11-02, e621 post 6577789) show the current
            # wire reports negative downvote counts; only ``up`` stays
            # non-negative.
            if name == "up" and value is not None and value < 0:
                raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post score is malformed")
    flags = body.get("flags")
    if flags is not None and (
        not isinstance(flags, dict)
        or any(
            not isinstance(name, str) or not isinstance(value, bool)
            for name, value in flags.items()
        )
    ):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post flags are malformed")
    pools = body.get("pools")
    if pools is not None and (
        not isinstance(pools, list)
        or any(not isinstance(pool, int) or isinstance(pool, bool) or pool < 1 for pool in pools)
    ):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post pools are malformed")
    sources = body.get("sources")
    if sources is not None and (
        not isinstance(sources, list)
        or any(not isinstance(source, str) or not source for source in sources)
    ):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post sources are malformed")
    uploader_id = body.get("uploader_id")
    if uploader_id is not None and (
        not isinstance(uploader_id, int) or isinstance(uploader_id, bool) or uploader_id < 1
    ):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post uploader ID is malformed")
    uploader_name = body.get("uploader_name")
    if uploader_name is not None and (not isinstance(uploader_name, str) or not uploader_name):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post uploader name is malformed")


def _validate_media_shape(value: Mapping[str, Any], role: str) -> None:
    for name in ("width", "height", "size"):
        field = value.get(name)
        if field is not None and (
            not isinstance(field, int) or isinstance(field, bool) or field < 0
        ):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, f"{role} media {name} is malformed"
            )
    extension = value.get("ext")
    if extension is not None and (not isinstance(extension, str) or not extension):
        raise AdapterFailure(
            AdapterOutcome.MALFORMED_RESPONSE, f"{role} media extension is malformed"
        )
    digest = value.get("md5")
    if digest is not None and (
        not isinstance(digest, str)
        or len(digest) != 32
        or any(char not in "0123456789abcdefABCDEF" for char in digest)
    ):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, f"{role} media MD5 is malformed")
