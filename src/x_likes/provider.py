from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


class ProviderError(RuntimeError):
    """Raised when post metadata cannot be retrieved from a provider."""

    def __init__(self, message: str, *, raw: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.raw = raw


class ProviderUnavailable(ProviderError):
    """Raised for a terminal tombstone such as deleted, private, or blocked."""

    def __init__(self, message: str, *, reason: str, raw: dict[str, Any]) -> None:
        super().__init__(message, raw=raw)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ImageMetadata:
    index: int
    source_url: str
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None


@dataclass(frozen=True, slots=True)
class AccountMetadata:
    account_id: str
    handle: str | None
    display_name: str | None
    bio: str | None
    profile_url: str | None
    avatar_url: str | None
    banner_url: str | None
    location: str | None
    website_url: str | None
    followers: int | None
    following: int | None
    verified: bool | None
    verification_type: str | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PostMetadata:
    post_id: str
    post_url: str
    text: str | None
    account: AccountMetadata | None
    created_at: str | None
    images: tuple[ImageMetadata, ...]
    raw: dict[str, Any]

    @property
    def author_id(self) -> str | None:
        return self.account.account_id if self.account else None

    @property
    def author_handle(self) -> str | None:
        return self.account.handle if self.account else None

    @property
    def author_name(self) -> str | None:
        return self.account.display_name if self.account else None


class FxTwitterClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.fxtwitter.com",
        user_agent: str = "x-likes-archiver/0.1 (personal archive)",
        timeout: float = 30.0,
        attempts: int = 4,
        client: httpx.Client | None = None,
    ) -> None:
        self._attempts = attempts
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url,
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )

    def __enter__(self) -> FxTwitterClient:
        return self

    def __exit__(self, *_: object) -> None:
        if self._owns_client:
            self._client.close()

    def fetch(self, post_id: str) -> PostMetadata:
        response: httpx.Response | None = None
        for attempt in range(self._attempts):
            try:
                response = self._client.get(f"/2/status/{post_id}")
            except httpx.RequestError as error:
                if attempt + 1 == self._attempts:
                    raise ProviderError(f"FxTwitter request failed: {error}") from error
                time.sleep(2**attempt)
                continue

            if response.status_code not in {429, 500, 502, 503, 504}:
                break
            if attempt + 1 < self._attempts:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                time.sleep(delay)

        if response is None:
            raise ProviderError("FxTwitter returned no response")
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderError(
                f"FxTwitter returned HTTP {response.status_code}: {response.text[:200]}"
            ) from error
        if not isinstance(payload, dict):
            raise ProviderError("FxTwitter returned an unexpected response body")
        if response.is_error and not isinstance(payload.get("status"), dict):
            message = payload.get("message") or response.reason_phrase
            raise ProviderError(
                f"FxTwitter returned HTTP {response.status_code}: {message}", raw=payload
            )
        return normalize_fxtwitter(payload, expected_post_id=post_id)


def normalize_fxtwitter(payload: dict[str, Any], *, expected_post_id: str) -> PostMetadata:
    """Normalize FxTwitter v2 while retaining the complete original response."""
    # FxTwitter renamed this object from ``tweet`` to ``status``. Accept both
    # because saved responses from either API generation remain useful input.
    status = payload.get("status")
    if not isinstance(status, dict):
        status = payload.get("tweet")
    if not isinstance(status, dict):
        message = payload.get("message") or payload.get("error") or "missing tweet data"
        raise ProviderError(f"FxTwitter could not resolve the post: {message}", raw=payload)

    status_type = _string(status, "type")
    if status_type == "tombstone":
        reason = _string(status, "reason") or "unavailable"
        message = _string(status, "message") or f"Post is {reason}"
        raise ProviderUnavailable(message, reason=reason, raw=payload)
    if payload.get("code") != 200 or status_type not in {None, "status"}:
        message = payload.get("message") or f"unexpected status type: {status_type}"
        raise ProviderError(f"FxTwitter could not resolve the post: {message}", raw=payload)

    author = status.get("author") if isinstance(status.get("author"), dict) else {}
    account = _normalize_account(author)
    media = status.get("media") if isinstance(status.get("media"), dict) else {}
    photos_value = media.get("photos")
    photos = photos_value if isinstance(photos_value, list) else []
    images: list[ImageMetadata] = []
    for index, photo in enumerate(photos, start=1):
        if not isinstance(photo, dict):
            continue
        source_url = _string(photo, "url", "media_url_https", "media_url")
        if not source_url:
            continue
        images.append(
            ImageMetadata(
                index=index,
                source_url=source_url,
                width=_integer(photo, "width"),
                height=_integer(photo, "height"),
                alt_text=_string(photo, "altText", "alt_text"),
            )
        )

    post_id = _string(status, "id") or expected_post_id
    return PostMetadata(
        post_id=post_id,
        post_url=_string(status, "url") or f"https://x.com/i/web/status/{post_id}",
        text=_string(status, "text"),
        account=account,
        created_at=_string(status, "created_at", "createdAt"),
        images=tuple(images),
        raw=payload,
    )


def _normalize_account(author: dict[str, Any]) -> AccountMetadata | None:
    account_id = _string(author, "id")
    if account_id is None:
        return None

    website = author.get("website")
    if isinstance(website, dict):
        website_url = _string(website, "url", "expanded_url")
    else:
        website_url = str(website).strip() if website is not None else None

    verification = author.get("verification")
    verification_data = verification if isinstance(verification, dict) else {}
    verified_value = verification_data.get("verified", author.get("verified"))

    return AccountMetadata(
        account_id=account_id,
        handle=_string(author, "screen_name", "handle", "username"),
        display_name=_text(author, "name"),
        bio=_text(author, "description", "bio"),
        profile_url=_string(author, "url"),
        avatar_url=_string(author, "avatar_url", "profile_image_url_https"),
        banner_url=_string(author, "banner_url", "profile_banner_url"),
        location=_text(author, "location"),
        website_url=website_url,
        followers=_integer(author, "followers"),
        following=_integer(author, "following"),
        verified=_boolean(verified_value),
        verification_type=_string(verification_data, "type"),
        raw=author,
    )


def _string(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _text(data: dict[str, Any], *keys: str) -> str | None:
    """Return text while preserving the meaningful present-but-empty distinction."""
    for key in keys:
        if key in data and data[key] is not None:
            return str(data[key]).strip()
    return None


def _boolean(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    return None


def _integer(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
