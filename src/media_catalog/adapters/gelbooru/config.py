"""Immutable provider policy for the native Gelbooru metadata adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlsplit

from media_catalog.adapters.contracts import (
    LookupCapabilities,
    LookupCapability,
    LookupPlanContext,
    LookupStrategy,
)

PROVIDER_KEY = "gelbooru"
ADAPTER_VERSION = "gelbooru-native-v2"
DAPI_SCHEMA_VERSION = "gelbooru-dapi-json-v1"
HTML_SCHEMA_VERSION = "gelbooru-html-v1"
DAPI_TRANSPORT_VERSION = "gelbooru-dapi-v1"
HTML_PARSER_VERSION = "gelbooru-html-parser-v1"
CONTINUATION_VERSION = "gelbooru-pid-v2"

GELBOORU_BASE_URL = "https://gelbooru.com"
GELBOORU_HOST = "gelbooru.com"
GELBOORU_USER_AGENT = "data-processing-tools/0.1 (metadata-only Gelbooru catalog)"

# Gelbooru documents a maximum DAPI page size of 100 but no public numeric rate
# limit.  Two seconds is a deliberately conservative installed floor; callers
# may make it stricter but cannot weaken it.
MAX_PAGE_SIZE = 100
MINIMUM_INTERVAL_SECONDS = 2.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 15.0


class GelbooruTransport(StrEnum):
    """Closed transport vocabulary; selection is explicit and durable."""

    DAPI_JSON = "dapi_json"
    HTML_POST = "html_post"


@dataclass(frozen=True, slots=True)
class GelbooruInstance:
    """Validated single-instance Gelbooru policy and external secret references."""

    platform_key: str = PROVIDER_KEY
    base_url: str = GELBOORU_BASE_URL
    host: str = GELBOORU_HOST
    user_id_env: str = "GELBOORU_USER_ID"
    api_key_env: str = "GELBOORU_API_KEY"
    user_agent: str = GELBOORU_USER_AGENT
    minimum_interval_seconds: float = MINIMUM_INTERVAL_SECONDS
    page_size: int = MAX_PAGE_SIZE
    max_response_bytes: int = MAX_RESPONSE_BYTES
    request_timeout_seconds: float = REQUEST_TIMEOUT_SECONDS
    lookup_capabilities: LookupCapabilities = field(default_factory=lambda: LookupCapabilities(()))

    def __post_init__(self) -> None:
        if self.platform_key != PROVIDER_KEY:
            raise ValueError(f"Gelbooru platform key must be {PROVIDER_KEY!r}")
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.hostname.lower() != self.host.lower()
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Gelbooru instance requires its canonical HTTPS base URL")
        if not self.user_id_env.strip() or not self.api_key_env.strip():
            raise ValueError("Gelbooru instance requires external credential references")
        if not self.user_agent.strip() or self.user_agent.lstrip().lower().startswith("mozilla/"):
            raise ValueError("Gelbooru instance requires a descriptive non-browser User-Agent")
        if self.minimum_interval_seconds < MINIMUM_INTERVAL_SECONDS:
            raise ValueError(
                f"Gelbooru minimum interval must be at least {MINIMUM_INTERVAL_SECONDS}s"
            )
        if isinstance(self.page_size, bool) or not 1 <= self.page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"Gelbooru page size must be between 1 and {MAX_PAGE_SIZE}")
        if (
            isinstance(self.max_response_bytes, bool)
            or self.max_response_bytes < 1
            or self.request_timeout_seconds <= 0
        ):
            raise ValueError("Gelbooru response and time limits must be positive")

    @property
    def instance_key(self) -> str:
        return self.platform_key

    @property
    def lookup_plan_context(self) -> LookupPlanContext:
        """Provider-neutral planning identity for this Gelbooru instance."""

        return LookupPlanContext(
            provider=PROVIDER_KEY,
            instance_key=self.platform_key,
            adapter_version=ADAPTER_VERSION,
            schema_version=DAPI_SCHEMA_VERSION,
            lookup_capabilities=self.lookup_capabilities,
        )

    def schema_version(self, transport: GelbooruTransport) -> str:
        if transport is GelbooruTransport.DAPI_JSON:
            return DAPI_SCHEMA_VERSION
        return HTML_SCHEMA_VERSION

    def transport_version(self, transport: GelbooruTransport) -> str:
        if transport is GelbooruTransport.DAPI_JSON:
            return DAPI_TRANSPORT_VERSION
        return HTML_PARSER_VERSION


GELBOORU = GelbooruInstance(
    # Bounded reverse lookup is limited to the exact server-side operators the
    # DAPI documents for searches: canonical source URL and exact MD5.  Gelbooru
    # exposes no foreign-ID metatag and no artist-record endpoint, so the other
    # neutral strategies stay undeclared rather than approximated.
    lookup_capabilities=LookupCapabilities(
        (
            LookupCapability(
                LookupStrategy.SOURCE_POST_URL, "post", "page", max_page_size=MAX_PAGE_SIZE
            ),
            LookupCapability(
                LookupStrategy.DECLARED_MD5, "post", "page", max_page_size=MAX_PAGE_SIZE
            ),
            LookupCapability(
                LookupStrategy.VERIFIED_MD5, "post", "page", max_page_size=MAX_PAGE_SIZE
            ),
        )
    ),
)
