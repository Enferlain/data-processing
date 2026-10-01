"""Credential scrubbing for Gelbooru material that can outlive a request."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[redacted]"
CREDENTIAL_QUERY_PARAMS = frozenset({"user_id", "api_key"})

_URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+")


def sanitize_text(text: str, secrets: Iterable[str]) -> str:
    """Replace every occurrence of a secret value with the redaction placeholder."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


def sanitize_url(url: str) -> str:
    """Drop credential query parameters while preserving the public request shape."""
    try:
        split = urlsplit(url)
    except ValueError:
        return url
    query = [
        (name, value)
        for name, value in parse_qsl(split.query, keep_blank_values=True)
        if name not in CREDENTIAL_QUERY_PARAMS
    ]
    return urlunsplit(split._replace(query=urlencode(query)))


def sanitize_message(text: str, secrets: Iterable[str]) -> str:
    """Scrub credential values and credential-bearing URLs from free-form text."""
    return sanitize_text(_URL_PATTERN.sub(lambda match: sanitize_url(match.group()), text), secrets)


def sanitize_exception(error: BaseException, secrets: Iterable[str]) -> str:
    """Return a secret-free rendering of a transport exception message."""
    return sanitize_message(str(error), secrets)


def sanitize_mapping(value: object, secrets: Iterable[str]) -> object:
    """Recursively scrub credential material from durable record shapes."""
    if isinstance(value, str):
        return sanitize_message(value, secrets)
    if isinstance(value, dict):
        return {key: sanitize_mapping(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(sanitize_mapping(item, secrets) for item in value)
    return value
