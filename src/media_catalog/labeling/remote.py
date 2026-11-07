"""Transient provider-aware media requests for the local labeling page."""

from __future__ import annotations

import mimetypes
import re
import sqlite3
import time
from dataclasses import dataclass

import httpx

from media_catalog.acquisition.policies import (
    RequestPolicyError,
    media_request_policy_for_platform,
)
from media_catalog.labeling.sankaku import (
    SankakuDisplayError,
    SankakuDisplayResolver,
    signed_url_expired,
)

MAX_REMOTE_BYTES = 128 * 1024 * 1024
MAX_REMOTE_SECONDS = 30
MAX_REDIRECTS = 5
_RANGE = re.compile(r"bytes=(?:[0-9]{1,20}-[0-9]{0,20}|-[0-9]{1,20})")
_CONTENT_RANGE = re.compile(r"bytes ([0-9]{1,20})-([0-9]{1,20})/([0-9]{1,20})")


class RemoteMediaError(ValueError):
    """A public-safe failure; never include upstream URLs or exception text."""

    def __init__(self, message: str, *, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RemoteMedia:
    body: bytes
    content_type: str
    status: int
    content_range: str | None = None


def fetch_remote_media(
    connection: sqlite3.Connection,
    occurrence_id: int,
    variant: str,
    *,
    range_header: str | None = None,
    client: httpx.Client,
    sankaku_resolver: SankakuDisplayResolver | None = None,
) -> RemoteMedia:
    """Fetch only a catalog-selected URL, admitted by its provider's media policy."""
    if variant not in {"primary", "preview"}:
        raise RemoteMediaError("Unknown remote media variant")
    if range_header and not _RANGE.fullmatch(range_header):
        raise RemoteMediaError("Unsupported media range", status=416)
    if range_header:
        first, last = range_header[6:].split("-", 1)
        if (not first and int(last) == 0) or (first and last and int(first) > int(last)):
            raise RemoteMediaError("Unsupported media range", status=416)
    row = connection.execute(
        """SELECT p.platform_key, m.remote_url, m.preview_url, m.mime_type, m.role,
                  po.native_post_id, m.source_key, m.declared_md5
             FROM media_occurrences m JOIN posts po USING(post_id)
             JOIN platforms p ON p.platform_id = po.platform_id
            WHERE m.media_occurrence_id = ? AND m.availability = 'available'
              AND po.availability NOT IN ('unavailable', 'deleted')""",
        (occurrence_id,),
    ).fetchone()
    if row is None:
        raise RemoteMediaError("Remote media is unavailable")
    platform, original, preview, declared_mime, role, native_id, source_key, md5 = row
    policy = media_request_policy_for_platform(platform)
    if policy is None:
        raise RemoteMediaError("No remote media policy for this provider")
    selected_url = preview if variant == "preview" else original
    if not selected_url:
        raise RemoteMediaError("Remote media URL is unavailable")
    policy_variant = (
        "preview"
        if variant == "preview" or role in {"preview", "thumbnail", "thumb"}
        else "sample"
        if role in {"sample", "large", "medium"}
        else "original"
    )
    try:
        deadline = time.monotonic() + MAX_REMOTE_SECONDS
        renewed = False
        recipe = policy.recipe(
            media_occurrence_id=occurrence_id,
            variant_key=policy_variant,
            selected_url=selected_url,
        )
        if platform == "sankaku":
            sankaku_resolver = sankaku_resolver or SankakuDisplayResolver()
            selected_url = (
                sankaku_resolver.cached(native_id, source_key, md5, variant) or selected_url
            )
            if signed_url_expired(selected_url):
                selected_url = sankaku_resolver.refresh(
                    native_id, source_key, md5, variant, client=client, deadline=deadline
                )
                renewed = True
            recipe = policy.recipe(
                media_occurrence_id=occurrence_id,
                variant_key=policy_variant,
                selected_url=selected_url,
            )
        if recipe.credential_reference is not None:
            raise RemoteMediaError("Remote media requires unsupported authentication")
        headers = dict(recipe.headers)
        if range_header:
            headers["Range"] = range_header
        url = recipe.url
        redirect_count = 0
        for _attempt in range(MAX_REDIRECTS + 2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RemoteMediaError("Remote media request timed out")
            with client.stream(
                "GET", url, headers=headers, follow_redirects=False, timeout=min(15, remaining)
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    if redirect_count == MAX_REDIRECTS:
                        raise RemoteMediaError("Too many remote media redirects")
                    url = policy.validate_redirect(url, response.headers.get("Location", ""))
                    redirect_count += 1
                    continue
                if response.status_code == 403 and platform == "sankaku":
                    if renewed:
                        raise RemoteMediaError("Sankaku denied media after renewing its link")
                    assert sankaku_resolver is not None
                    selected_url = sankaku_resolver.refresh(
                        native_id, source_key, md5, variant, client=client, deadline=deadline
                    )
                    recipe = policy.recipe(
                        media_occurrence_id=occurrence_id,
                        variant_key=policy_variant,
                        selected_url=selected_url,
                    )
                    url = recipe.url
                    renewed = True
                    continue
                if response.status_code not in {200, 206}:
                    raise RemoteMediaError("Provider could not serve remote media")
                mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if not recipe.response.accepts(mime):
                    raise RemoteMediaError("Provider returned non-media content")
                if mime in {"", "application/octet-stream"}:
                    hinted = mimetypes.guess_type(selected_url.split("?", 1)[0])[0]
                    mime = (
                        hinted
                        or declared_mime
                        or ("image/jpeg" if policy_variant == "preview" else mime)
                    )
                mime = mime.split(";", 1)[0].strip().lower()
                if (
                    not re.fullmatch(r"(?:image|video|audio)/[a-z0-9][a-z0-9.+-]*", mime)
                    or mime == "image/svg+xml"
                ):
                    raise RemoteMediaError("Unsupported remote media type")
                length = response.headers.get("Content-Length")
                if length and (
                    not length.isdecimal() or len(length) > 20 or int(length) > MAX_REMOTE_BYTES
                ):
                    raise RemoteMediaError("Remote media exceeds display size limit")
                content_range = None
                if response.status_code == 206:
                    content_range = response.headers.get("Content-Range", "")
                    match = _CONTENT_RANGE.fullmatch(content_range)
                    if not range_header or not match:
                        raise RemoteMediaError("Invalid remote media range")
                    start, end, total = map(int, match.groups())
                    if not 0 <= start <= end < total:
                        raise RemoteMediaError("Invalid remote media range")
                    first, last = range_header[6:].split("-", 1)
                    wanted_start = int(first) if first else max(0, total - int(last))
                    wanted_end = min(int(last), total - 1) if first and last else total - 1
                    if not wanted_start <= start <= end <= wanted_end:
                        raise RemoteMediaError("Unexpected remote media range")
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > MAX_REMOTE_BYTES:
                        raise RemoteMediaError("Remote media exceeds display size limit")
                    if time.monotonic() > deadline:
                        raise RemoteMediaError("Remote media request timed out")
                    body.extend(chunk)
                if content_range and len(body) != end - start + 1:
                    raise RemoteMediaError("Incomplete remote media range")
                return RemoteMedia(bytes(body), mime, response.status_code, content_range)
    except SankakuDisplayError as error:
        raise RemoteMediaError(str(error)) from None
    except (httpx.HTTPError, RequestPolicyError):
        raise RemoteMediaError("Provider media request failed") from None
    raise RemoteMediaError("Provider media request failed")
