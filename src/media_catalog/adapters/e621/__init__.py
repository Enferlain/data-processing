"""Native e621 metadata adapter."""

from .adapter import E621Adapter, E621Credentials
from .config import (
    ADAPTER_VERSION,
    CONTINUATION_VERSION,
    E621,
    E621_TAG_CATEGORY_CODES,
    MAX_PAGE_SIZE,
    MINIMUM_INTERVAL_SECONDS,
    SCHEMA_VERSION,
    E621Instance,
    e621_category_label,
    neutral_category,
)

__all__ = [
    "ADAPTER_VERSION",
    "CONTINUATION_VERSION",
    "E621",
    "E621_TAG_CATEGORY_CODES",
    "MAX_PAGE_SIZE",
    "MINIMUM_INTERVAL_SECONDS",
    "SCHEMA_VERSION",
    "E621Adapter",
    "E621Credentials",
    "E621Instance",
    "e621_category_label",
    "neutral_category",
]
