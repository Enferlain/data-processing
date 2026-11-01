"""Pawchive (kemono API family) instance policy and request floors."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from media_catalog.adapters.contracts import LookupCapabilities

PROVIDER_KEY = "pawchive"
ADAPTER_VERSION = "pawchive-native-v1"
SCHEMA_VERSION = "pawchive-json-v1"
CONTINUATION_VERSION = "pawchive-offset-v1"

PAWCHIVE_BASE_URL = "https://pawchive.pw"
PAWCHIVE_HOST = "pawchive.pw"
API_ROOT = "/api/v1"
# Thumbnails are the only anonymously reachable asset form on a stable,
# non-expiring URL (verified 2026-11-01); originals live behind expiring
# signed temp URLs that the catalog never retains.
THUMBNAIL_BASE_URL = "https://img.pawchive.pw/thumbnail/data"

PAWCHIVE_USER_AGENT = "data-processing-tools/0.1 (metadata-only pawchive catalog)"

MINIMUM_INTERVAL_SECONDS = 1.0
# The API serves fixed 50-entry post pages with no limit parameter; observed
# pages reach 1.5 MB, so the transport ceiling carries headroom above that.
MAX_PAGE_SIZE = 50
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class PawchiveInstance:
    """Immutable pawchive provider configuration and request-policy floors.

    Pawchive is the only maintained instance of the kemono API family
    (maintainer statement 2026-10-31: kemono.su and coomer.su are dead or
    stale by months to a year), so it ships alone; the registry keeps the
    family shape so revived siblings can join behind live captures.
    """

    platform_key: str = PROVIDER_KEY
    base_url: str = PAWCHIVE_BASE_URL
    host: str = PAWCHIVE_HOST
    schema_version: str = SCHEMA_VERSION
    adapter_version: str = ADAPTER_VERSION
    user_agent: str = PAWCHIVE_USER_AGENT
    minimum_interval_seconds: float = MINIMUM_INTERVAL_SECONDS
    page_size: int = MAX_PAGE_SIZE
    max_response_bytes: int = MAX_RESPONSE_BYTES
    request_timeout_seconds: float = REQUEST_TIMEOUT_SECONDS
    lookup_capabilities: LookupCapabilities = field(default_factory=lambda: LookupCapabilities(()))

    def __post_init__(self) -> None:
        if not self.platform_key.strip() or self.platform_key != self.platform_key.lower():
            raise ValueError("pawchive instance requires a lowercase platform key")
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
            raise ValueError("pawchive instance requires its canonical HTTPS base URL")
        if not self.schema_version.strip() or not self.adapter_version.strip():
            raise ValueError("pawchive instance requires schema and adapter versions")
        if not self.user_agent.strip() or self.user_agent.lstrip().lower().startswith("mozilla/"):
            raise ValueError("pawchive instance requires a descriptive non-browser User-Agent")
        if self.minimum_interval_seconds < MINIMUM_INTERVAL_SECONDS:
            raise ValueError(
                f"pawchive minimum interval must be at least {MINIMUM_INTERVAL_SECONDS}s"
            )
        if isinstance(self.page_size, bool) or not 1 <= self.page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"pawchive page size must be between 1 and {MAX_PAGE_SIZE}")
        if (
            isinstance(self.max_response_bytes, bool)
            or self.max_response_bytes < 1
            or self.request_timeout_seconds <= 0
        ):
            raise ValueError("pawchive response and time limits must be positive")

    @property
    def instance_key(self) -> str:
        return self.platform_key


PAWCHIVE = PawchiveInstance()

# The registered kemono-engine family: platform key -> instance.  Kernel
# operation admission (SOURCE_OPERATIONS) and CLI instance selection resolve
# through this registry; instances outside it are not shipped surfaces.
PAWCHIVE_INSTANCES: dict[str, PawchiveInstance] = {
    PAWCHIVE.platform_key: PAWCHIVE,
}
