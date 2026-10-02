"""Gelbooru anonymous single-post HTML adapter."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from media_catalog.adapters.contracts import (
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    AdapterRequest,
    LookupCapabilities,
    NormalizedItem,
    NormalizedPage,
    ResponseEnvelope,
)
from media_catalog.adapters.gelbooru.config import (
    ADAPTER_VERSION,
    GELBOORU,
    HTML_PARSER_VERSION,
    HTML_SCHEMA_VERSION,
    MAX_RESPONSE_BYTES,
    GelbooruInstance,
)
from media_catalog.adapters.gelbooru.redaction import sanitize_exception


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


#: Fixture-proven mapping from Gelbooru ``tag-type-*`` CSS classes to the
#: neutral tag-category vocabulary (artist/character/copyright/general/meta).
_TAG_CATEGORY_MAP = {
    "artist": "artist",
    "character": "character",
    "copyright": "copyright",
    "general": "general",
    "metadata": "meta",
}


class GelbooruHtmlAdapter:
    """Anonymous single-post HTML parser for Gelbooru-compatible instances."""

    provider_key = "gelbooru"
    adapter_version = ADAPTER_VERSION

    def __init__(
        self,
        instance: GelbooruInstance = GELBOORU,
        *,
        client: httpx.Client,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self.instance = instance
        self.instance_key = instance.platform_key
        self.schema_version = HTML_SCHEMA_VERSION
        self._client = client
        self._clock = clock

    @property
    def transport_key(self) -> str:
        return HTML_PARSER_VERSION

    @property
    def minimum_interval_seconds(self) -> float:
        return self.instance.minimum_interval_seconds

    @property
    def transport_version(self) -> str:
        return HTML_PARSER_VERSION

    @property
    def lookup_capabilities(self) -> LookupCapabilities:
        """Gelbooru HTML adapter declares no bounded reverse-lookup strategies."""
        return LookupCapabilities()

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        """Render an HTML request and return the provider response as an envelope."""
        if request.operation is not AdapterOperation.FETCH_POST:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                f"HTML transport only supports fetch_post, not {request.operation.value}",
            )
        post_id = _stable_id(request.target, "post ID")
        endpoint = f"{self.instance.base_url}/index.php"
        params = {"page": "post", "s": "view", "id": post_id}
        headers = {"User-Agent": self.instance.user_agent, "Accept": "text/html"}
        try:
            response = self._client.get(endpoint, params=params, headers=headers)
        except httpx.HTTPError as error:
            raise AdapterFailure(
                AdapterOutcome.TRANSIENT_PROVIDER,
                f"HTML transport error: {sanitize_exception(error, ())}",
            ) from error
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise AdapterFailure(
                AdapterOutcome.RESPONSE_TOO_LARGE,
                "HTML response exceeded the transport byte limit",
                status_code=response.status_code,
            )
        return ResponseEnvelope(
            provider=self.provider_key,
            instance=self.instance_key,
            operation=request.operation,
            request_identity=f"{self.instance_key}:html_post:post:{post_id}",
            status_code=response.status_code,
            headers=dict(response.headers),
            payload=response.content or b"{}",
            observed_at=self._clock(),
            adapter_version=self.adapter_version,
            schema_version=self.schema_version,
            transport_key=self.transport_key,
            transport_version=self.transport_version,
            request_target=f"post:{post_id}",
        )

    def normalize(self, response: ResponseEnvelope) -> NormalizedPage:
        """Parse HTML response into provider-neutral items, fail-closed on missing markers."""
        self._validate_envelope(response)
        self._raise_for_outcome(response)

        if not response.payload:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "HTML transport response payload is empty",
            )

        try:
            html = response.payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "HTML response is not valid UTF-8",
            ) from error

        return self._parse_html(html, response)

    # ── Outcome classification ─────────────────────────────────────────

    def _raise_for_outcome(self, response: ResponseEnvelope) -> None:
        if response.status_code == 401:
            raise AdapterFailure(
                AdapterOutcome.AUTHENTICATION_REQUIRED,
                "provider authentication is required",
                status_code=401,
            )
        if response.status_code == 403:
            raise AdapterFailure(
                AdapterOutcome.AUTHORIZATION_DENIED,
                "provider access was denied",
                status_code=403,
            )
        if response.status_code == 404:
            raise AdapterFailure(
                AdapterOutcome.UNAVAILABLE,
                "provider record is unavailable",
                status_code=404,
            )
        if response.status_code >= 500:
            raise AdapterFailure(
                AdapterOutcome.TRANSIENT_PROVIDER,
                "provider is temporarily unavailable",
                status_code=response.status_code,
            )
        if not 200 <= response.status_code < 300:
            raise AdapterFailure(
                AdapterOutcome.UNAVAILABLE,
                "provider request was unsuccessful",
                status_code=response.status_code,
            )

    def _validate_envelope(self, response: ResponseEnvelope) -> None:
        if response.provider != self.provider_key or response.instance != self.instance_key:
            raise ValueError("response belongs to another provider instance")
        if response.schema_version != self.schema_version:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "incompatible provider schema version",
            )

    # ── HTML parsing ───────────────────────────────────────────────────

    def _parse_html(self, html: str, response: ResponseEnvelope) -> NormalizedPage:
        """Parse Gelbooru HTML page into normalized items, fail-closed on missing markers."""
        # Detect challenge page first: a well-formed page (it has a <title>)
        # that carries neither the tag-list ul nor the Posted: statistics.  A
        # post page always carries both; a challenge carries neither.  Truncated
        # markup without even a title falls through to the marker checks below.
        if "<title>" in html and 'id="tag-list"' not in html and "Posted:" not in html:
            raise AdapterFailure(
                AdapterOutcome.AUTHORIZATION_DENIED,
                "HTML page appears to be a challenge or login page "
                "(missing tag-list and statistics)",
            )

        # Identity markers: at minimum we need <title> and <img id="image">
        if "<title>" not in html:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "HTML page lacks identity marker <title>",
            )
        if 'id="image"' not in html:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                'HTML page lacks identity marker <img id="image">',
            )

        items: list[NormalizedItem] = []
        post_id = self._extract_post_id(response.request_target)

        # Title: contains tag spellings and "Image View" marker
        self._extract_title(html)  # validate title marker exists

        # og:image meta
        og_image = self._extract_og_image(html)

        # Image element: dimensions + src (sample URL)
        image_el = self._extract_image(html)

        # Statistics: Posted, Uploader, Size, Source, Rating, Score
        stats = self._extract_statistics(html)

        # Tags by category from tag-type-* CSS classes
        tags_by_category = self._extract_tags(html)

        # Build normalized items
        items.append(
            NormalizedItem(
                "post",
                post_id,
                {
                    "platform": self.instance_key,
                    "canonical_url": (
                        f"{self.instance.base_url}/index.php?page=post&s=view&id={post_id}"
                    ),
                    "created_at": stats.get("posted"),
                    "rating": stats.get("rating"),
                    "availability": "available",
                    "status": None,  # the HTML page exposes no post status
                    "source": stats.get("source") or None,
                    # The page writer persists score facts only in mapping form.
                    "score": (
                        {"total": stats["score"]} if isinstance(stats.get("score"), int) else None
                    ),
                },
            )
        )

        # Uploader account and participant
        uploader = stats.get("uploader")
        if uploader:
            items.extend(
                [
                    NormalizedItem(
                        "account",
                        uploader,
                        {
                            "platform": self.instance_key,
                            "availability": "available",
                            "handle": uploader,
                        },
                    ),
                    NormalizedItem(
                        "post_participant",
                        f"{post_id}:uploader:{uploader}",
                        {
                            "platform": self.instance_key,
                            "post_id": post_id,
                            "account_id": uploader,
                            "role": "uploader",
                        },
                    ),
                ]
            )

        # Tags with HTML-proven category mapping
        for category, spellings in tags_by_category.items():
            for position, spelling in enumerate(spellings):
                items.append(
                    NormalizedItem(
                        "post_tag",
                        f"{post_id}:{category}:{spelling}",
                        {
                            "platform": self.instance_key,
                            "post_id": post_id,
                            "category": category,
                            "normalized_name": spelling.casefold(),
                            "spelling": spelling,
                            "position": position,
                        },
                    )
                )

        # Media occurrence: sample URL from <img id="image">, preview from og:image
        if image_el.get("src") or og_image:
            variants: list[dict[str, str]] = []
            if image_el.get("src"):
                variants.append({"role": "sample", "url": image_el["src"]})
            if og_image:
                variants.append({"role": "preview", "url": og_image})

            width = image_el.get("width")
            height = image_el.get("height")
            # Size statistic provides original dimensions
            size = stats.get("size")
            if size:
                width = size.get("width") or width
                height = size.get("height") or height

            items.append(
                NormalizedItem(
                    "media_occurrence",
                    f"{post_id}:primary",
                    {
                        "platform": self.instance_key,
                        "post_id": post_id,
                        "source_key": "primary",
                        "index": 0,
                        "role": "primary",
                        "remote_url": None,  # HTML never reveals the original file_url
                        "preview_url": og_image,
                        "width": width,
                        "height": height,
                        "variants": variants,
                        "availability": "available",
                    },
                )
            )

        # External reference (source URL)
        source = stats.get("source")
        if source:
            items.append(
                NormalizedItem(
                    "external_reference",
                    f"{post_id}:source",
                    {
                        "platform": self.instance_key,
                        "post_id": post_id,
                        "reference_kind": "source_url",
                        "value": source,
                        "evidence_only": True,
                    },
                )
            )

        return NormalizedPage(tuple(items))

    # ── Marker extraction helpers ──────────────────────────────────────

    @staticmethod
    def _extract_post_id(request_target: str | None) -> str:
        """Extract post ID from request_target string."""
        if not request_target or not request_target.startswith("post:"):
            raise ValueError("invalid request target for HTML post")
        return request_target.split(":", 1)[1]

    @staticmethod
    def _extract_title(html: str) -> str:
        """Extract post title from <title> tag."""
        match = re.search(r"<title>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
        if not match:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "HTML page has no <title> element",
            )
        # Strip " - Image View - | Gelbooru - Anime Art & Hentai Gallery - Free to Explore"
        raw = match.group(1).strip()
        return re.sub(
            r"\s*-\s*Image View.*$",
            "",
            raw,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()

    @staticmethod
    def _extract_og_image(html: str) -> str | None:
        """Extract og:image URL from meta tag."""
        match = re.search(
            r'<meta\s+property=["\']og:image["\']\s+content=["\'](.*?)["\']',
            html,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _extract_image(html: str) -> dict[str, Any]:
        """Extract <img id="image"> attributes (width, height, src)."""
        match = re.search(
            r'<img\s[^>]*id=["\']image["\'][^>]*>',
            html,
            re.IGNORECASE,
        )
        if not match:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                'HTML page has no <img id="image"> element',
            )
        tag = match.group(0)
        width = None
        height = None
        src = None
        w_match = re.search(r'width=["\'](\d+)["\']', tag, re.IGNORECASE)
        h_match = re.search(r'height=["\'](\d+)["\']', tag, re.IGNORECASE)
        s_match = re.search(r'src=["\'](.*?)["\']', tag, re.IGNORECASE)
        if w_match:
            width = int(w_match.group(1))
        if h_match:
            height = int(h_match.group(1))
        if s_match:
            src = s_match.group(1).strip()
        return {"width": width, "height": height, "src": src}

    @staticmethod
    def _extract_statistics(html: str) -> dict[str, Any]:
        """Extract Posted, Uploader, Size, Source, Rating, Score from <li> statistics."""
        stats: dict[str, Any] = {}

        # Posted: timestamp
        posted_match = re.search(r"Posted:\s*(.*?)\s*<br", html, re.IGNORECASE)
        if posted_match:
            raw_ts = posted_match.group(1).strip()
            try:
                parsed = parsedate_to_datetime(raw_ts)
                stats["posted"] = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
            except (ValueError, TypeError):
                # Try YYYY-MM-DD HH:MM:SS format
                try:
                    normalized = raw_ts.replace(" ", "T") + "Z"
                    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
                    stats["posted"] = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
                except (ValueError, TypeError):
                    pass

        # Uploader: name from link
        uploader_match = re.search(r"Uploader:\s*<a[^>]*>(.*?)</a>", html, re.IGNORECASE)
        if uploader_match:
            stats["uploader"] = uploader_match.group(1).strip()

        # Size: WxH
        size_match = re.search(r"Size:\s*(\d+)x(\d+)", html, re.IGNORECASE)
        if size_match:
            stats["size"] = {
                "width": int(size_match.group(1)),
                "height": int(size_match.group(2)),
            }

        # Source: URL (line-break: anywhere style)
        source_match = re.search(
            r'Source:\s*<a\s[^>]*href=["\'](.*?)["\'][^>]*>(.*?)</a>',
            html,
            re.IGNORECASE,
        )
        if source_match:
            stats["source"] = source_match.group(1).strip()

        # Rating: text
        rating_match = re.search(r"Rating:\s*(.*?)\s*<br", html, re.IGNORECASE)
        if rating_match:
            stats["rating"] = rating_match.group(1).strip().lower()

        # Score: numeric
        score_match = re.search(r"Score:\s*<span[^>]*>(\d+)</span>", html, re.IGNORECASE)
        if score_match:
            stats["score"] = int(score_match.group(1))

        return stats

    @staticmethod
    def _extract_tags(html: str) -> dict[str, list[str]]:
        """Extract tag spellings by category from tag-type-* CSS classes."""
        tags: dict[str, list[str]] = {}
        # Match <li class="tag-type-<category>">...<a>spelling</a>...</li>
        for match in re.finditer(
            r'<li\s+class=["\']tag-type-(\w+)["\'][^>]*>.*?<a\s[^>]*>(.*?)</a>',
            html,
            re.DOTALL | re.IGNORECASE,
        ):
            css_category = match.group(1).lower()
            category = _TAG_CATEGORY_MAP.get(css_category, "unknown")
            spelling = match.group(2).strip()
            if spelling:
                tags.setdefault(category, []).append(spelling)
        return tags


def _stable_id(value: str, name: str) -> str:
    """Validate and normalize a positive numeric stable ID."""
    if not isinstance(value, str) or not value.isdecimal() or int(value) < 1:
        raise ValueError(f"{name} must be a positive numeric stable ID")
    return str(int(value))
