"""Native pawchive metadata adapter (kemono API family)."""

from media_catalog.adapters.pawchive.adapter import PawchiveAdapter
from media_catalog.adapters.pawchive.config import (
    ADAPTER_VERSION,
    CONTINUATION_VERSION,
    MAX_PAGE_SIZE,
    MAX_RESPONSE_BYTES,
    MINIMUM_INTERVAL_SECONDS,
    PAWCHIVE,
    PAWCHIVE_INSTANCES,
    PROVIDER_KEY,
    SCHEMA_VERSION,
    PawchiveInstance,
)

__all__ = [
    "ADAPTER_VERSION",
    "CONTINUATION_VERSION",
    "MAX_PAGE_SIZE",
    "MAX_RESPONSE_BYTES",
    "MINIMUM_INTERVAL_SECONDS",
    "PAWCHIVE",
    "PAWCHIVE_INSTANCES",
    "PROVIDER_KEY",
    "SCHEMA_VERSION",
    "PawchiveAdapter",
    "PawchiveInstance",
]
