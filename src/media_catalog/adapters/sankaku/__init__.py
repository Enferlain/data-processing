"""Native Sankaku metadata adapter policy, credentials, and client."""

from media_catalog.adapters.sankaku.adapter import SankakuAdapter
from media_catalog.adapters.sankaku.config import (
    ADAPTER_VERSION,
    API_SCHEMA_VERSION,
    CONTINUATION_VERSION,
    MAX_PAGE_SIZE,
    MAX_RESPONSE_BYTES,
    MINIMUM_INTERVAL_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    SANKAKU,
    SANKAKU_INSTANCES,
    TAG_CATEGORY_BY_TYPE,
    TRANSPORT_KEY,
    SankakuInstance,
)
from media_catalog.adapters.sankaku.credentials import SankakuCredentials

__all__ = [
    "ADAPTER_VERSION",
    "API_SCHEMA_VERSION",
    "CONTINUATION_VERSION",
    "MAX_PAGE_SIZE",
    "MAX_RESPONSE_BYTES",
    "MINIMUM_INTERVAL_SECONDS",
    "REQUEST_TIMEOUT_SECONDS",
    "SANKAKU",
    "SANKAKU_INSTANCES",
    "TAG_CATEGORY_BY_TYPE",
    "TRANSPORT_KEY",
    "SankakuAdapter",
    "SankakuCredentials",
    "SankakuInstance",
]
