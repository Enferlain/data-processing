"""Sankaku instance policy, limits, and external secret references."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

ADAPTER_VERSION = "sankaku-native-v1"
API_SCHEMA_VERSION = "sankaku-api-v2-v1"
CONTINUATION_VERSION = "sankaku-keyset-v1"
TRANSPORT_KEY = "sankaku_api"

SANKAKU_BASE_URL = "https://sankakuapi.com"
SANKAKU_HOST = "sankakuapi.com"
SANKAKU_USER_AGENT = "data-processing-tools/0.1 (metadata-only Sankaku catalog)"

# The provider documents no numeric rate limit; two seconds is the family
# floor this repo already enforces.  Callers may tighten but not weaken it.
MAX_PAGE_SIZE = 100
MINIMUM_INTERVAL_SECONDS = 2.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 15.0

# Captured tag `type` ids (live capture 2026-10-29; reference-corroborated by
# gallery-dl's Sankaku TAG_TYPES).  Types without a kernel tag category
# (studio, genre, medium) land as "unknown" rather than approximated.
TAG_CATEGORY_BY_TYPE: dict[int, str] = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    9: "meta",
}


@dataclass(frozen=True, slots=True)
class SankakuInstance:
    """Validated Sankaku instance policy and external secret references."""

    platform_key: str = "sankaku"
    base_url: str = SANKAKU_BASE_URL
    host: str = SANKAKU_HOST
    login_env: str = "SANKAKU_LOGIN"
    password_env: str = "SANKAKU_PASSWORD"
    user_agent: str = SANKAKU_USER_AGENT
    minimum_interval_seconds: float = MINIMUM_INTERVAL_SECONDS
    page_size: int = MAX_PAGE_SIZE
    max_response_bytes: int = MAX_RESPONSE_BYTES
    request_timeout_seconds: float = REQUEST_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.platform_key != "sankaku":
            raise ValueError("Sankaku platform key must be 'sankaku'")
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
            raise ValueError("Sankaku instance requires its canonical HTTPS base URL")
        if not self.login_env.strip() or not self.password_env.strip():
            raise ValueError("Sankaku instance requires external credential references")
        if not self.user_agent.strip() or self.user_agent.lstrip().lower().startswith("mozilla/"):
            raise ValueError("Sankaku instance requires a descriptive non-browser User-Agent")
        if self.minimum_interval_seconds < MINIMUM_INTERVAL_SECONDS:
            raise ValueError(
                f"Sankaku minimum interval must be at least {MINIMUM_INTERVAL_SECONDS}s"
            )
        if isinstance(self.page_size, bool) or not 1 <= self.page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"Sankaku page size must be between 1 and {MAX_PAGE_SIZE}")
        if (
            isinstance(self.max_response_bytes, bool)
            or self.max_response_bytes < 1
            or self.request_timeout_seconds <= 0
        ):
            raise ValueError("Sankaku response and time limits must be positive")

    @property
    def instance_key(self) -> str:
        return self.platform_key


SANKAKU = SankakuInstance()

SANKAKU_INSTANCES: dict[str, SankakuInstance] = {SANKAKU.platform_key: SANKAKU}
