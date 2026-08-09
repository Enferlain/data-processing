from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

STRENGTH_SCORES = {"weak": 10, "moderate": 35, "strong": 70, "exact": 100}


def digest(*values: object) -> str:
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def parse_match_ref(value: str) -> tuple[str, int]:
    kind, separator, raw_id = value.partition(":")
    if not separator or kind not in {"account", "post"} or not raw_id.isdigit():
        raise ValueError(f"invalid candidate reference: {value}")
    return kind, int(raw_id)


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def public_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
    except ValueError:
        return "<invalid-url>"
    safe_keys = {"page", "s", "id"}
    query = urlencode(
        [
            (key, item if key.lower() in safe_keys else "<redacted>")
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        ],
        doseq=True,
    )
    return urlunsplit((parsed.scheme, host, parsed.path, query, ""))
