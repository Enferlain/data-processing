from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts import LookupCapabilities, LookupCapability, LookupStrategy


@dataclass(frozen=True, slots=True)
class DanbooruInstance:
    platform_key: str
    base_url: str
    schema_version: str
    login_env: str
    api_key_env: str
    user_agent: str = "data-processing-tools/0.1 (metadata-only catalog)"
    minimum_interval_seconds: float = 1.0
    page_size: int = 200
    lookup_capabilities: LookupCapabilities = field(default_factory=lambda: LookupCapabilities(()))

    def __post_init__(self) -> None:
        if not self.platform_key or not self.base_url.startswith("https://"):
            raise ValueError("Danbooru instance requires a platform key and HTTPS base URL")
        if not self.schema_version or not self.login_env or not self.api_key_env:
            raise ValueError("Danbooru instance requires schema and credential references")
        if self.minimum_interval_seconds <= 0 or self.page_size <= 0:
            raise ValueError("Danbooru request policy must be positive")

    @property
    def lookup_strategies(self) -> frozenset[LookupStrategy]:
        return self.lookup_capabilities.strategies


DANBOORU = DanbooruInstance(
    platform_key="danbooru",
    base_url="https://danbooru.donmai.us",
    schema_version="danbooru-json-v1",
    login_env="DANBOORU_LOGIN",
    api_key_env="DANBOORU_API_KEY",
    lookup_capabilities=LookupCapabilities(
        tuple(
            LookupCapability(
                strategy,
                "attribution" if strategy.value.startswith("artist_") else "post",
                "keyset",
            )
            for strategy in LookupStrategy
        )
    ),
)

AIBOORU = DanbooruInstance(
    platform_key="aibooru",
    base_url="https://aibooru.online",
    schema_version="aibooru-json-v1",
    login_env="AIBOORU_LOGIN",
    api_key_env="AIBOORU_API_KEY",
    lookup_capabilities=LookupCapabilities(
        tuple(
            LookupCapability(
                strategy,
                "attribution" if strategy.value.startswith("artist_") else "post",
                "keyset",
            )
            for strategy in (
                LookupStrategy.SOURCE_POST_URL,
                LookupStrategy.EXTERNAL_POST_ID,
                LookupStrategy.DECLARED_MD5,
                LookupStrategy.VERIFIED_MD5,
                LookupStrategy.ARTIST_EXACT_NAME,
                LookupStrategy.ARTIST_ALIAS,
            )
        )
    ),
)
