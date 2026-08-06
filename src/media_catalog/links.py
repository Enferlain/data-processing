from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from media_catalog.records import LinkOccurrence, PlatformReferenceRecord

CANONICALIZER_VERSION = "url-canonicalizer-v1"
EXTRACTOR_VERSION = "catalog-links-v1"
RECOGNIZER_VERSION = "platform-recognizers-v1"
SCORING_VERSION = "link-evidence-v1"

URL_PATTERN = re.compile(r"https?://[^\s<>\]\[(){}\"']+", re.IGNORECASE)
TRACKING_KEYS = frozenset({"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"})
SHORTENER_HOSTS = frozenset({"t.co", "bit.ly", "tinyurl.com", "ow.ly"})
LINK_HUB_HOSTS = frozenset({"linktr.ee", "lit.link", "potofu.me", "carrd.co"})
BOORU_INSTANCES = {
    "danbooru.donmai.us": "danbooru",
    "gelbooru.com": "gelbooru",
    "e621.net": "e621",
}
MASTODON_INSTANCES = frozenset({"baraag.net"})


@dataclass(frozen=True, slots=True)
class CanonicalURL:
    original_url: str
    canonical_url: str
    original_query: str
    original_fragment: str
    state: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RecognizedURL:
    canonical: CanonicalURL
    reference: PlatformReferenceRecord | None


def canonicalize_url(value: str) -> CanonicalURL:
    original = value.strip()
    try:
        parsed = urlsplit(original)
        port = parsed.port
    except ValueError:
        return CanonicalURL(original, original, "", "", "invalid", "malformed_url")
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return CanonicalURL(
            original, original, parsed.query, parsed.fragment, "invalid", "unsupported_url"
        )
    host = parsed.hostname.lower().rstrip(".")
    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    if host in {"twitter.com", "www.twitter.com", "mobile.twitter.com", "www.x.com"}:
        host = "x.com"
    elif host == "pixiv.net":
        host = "www.pixiv.net"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    recognized_host = host in {
        "x.com",
        "www.pixiv.net",
        *BOORU_INSTANCES,
        *MASTODON_INSTANCES,
    }
    if recognized_host:
        query_pairs = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in TRACKING_KEYS
        ]
        query = urlencode(query_pairs, doseq=True)
        canonical = urlunsplit(("https", host, path, query, ""))
    else:
        canonical = urlunsplit(
            (parsed.scheme.lower(), host, parsed.path or "/", parsed.query, parsed.fragment)
        )
    if parsed.hostname.lower().rstrip(".") in SHORTENER_HOSTS:
        return CanonicalURL(
            original,
            canonical,
            parsed.query,
            parsed.fragment,
            "redirect_required",
            "redirect_required",
        )
    return CanonicalURL(original, canonical, parsed.query, parsed.fragment, "unresolved", None)


def recognize_url(
    value: str,
    *,
    booru_instances: Mapping[str, str] | None = None,
    mastodon_instances: frozenset[str] | None = None,
) -> RecognizedURL:
    canonical = canonicalize_url(value)
    if canonical.state in {"invalid", "redirect_required"}:
        return RecognizedURL(canonical, None)
    parsed = urlsplit(canonical.canonical_url)
    host = parsed.hostname or ""
    path = parsed.path.rstrip("/") or "/"
    reference: PlatformReferenceRecord | None = None

    match = re.fullmatch(r"/([^/]+)/status/(\d+)", path)
    if host == "x.com" and match:
        reference = _reference(
            "x", "", "post", match.group(2), f"https://x.com/i/status/{match.group(2)}", "x-post"
        )
    elif (
        host == "x.com"
        and (match := re.fullmatch(r"/([^/]+)", path))
        and match.group(1) not in {"home", "explore", "i"}
    ):
        handle = match.group(1).lstrip("@").lower()
        reference = _reference("x", "", "account", handle, f"https://x.com/{handle}", "x-account")
    elif host == "www.pixiv.net" and (match := re.fullmatch(r"/(?:[a-z]{2}/)?users/(\d+)", path)):
        native_id = match.group(1)
        reference = _reference(
            "pixiv",
            "",
            "account",
            native_id,
            f"https://www.pixiv.net/users/{native_id}",
            "pixiv-user",
        )
    elif host == "www.pixiv.net" and (
        match := re.fullmatch(r"/(?:[a-z]{2}/)?artworks/(\d+)", path)
    ):
        native_id = match.group(1)
        reference = _reference(
            "pixiv",
            "",
            "post",
            native_id,
            f"https://www.pixiv.net/artworks/{native_id}",
            "pixiv-artwork",
        )
    configured_boorus = BOORU_INSTANCES | dict(booru_instances or {})
    booru_platform = configured_boorus.get(host)
    if (
        reference is None
        and booru_platform in {"danbooru", "e621"}
        and (match := re.fullmatch(r"/(?:posts|post/show)/(\d+)", path))
    ):
        native_id = match.group(1)
        reference = _reference(
            booru_platform,
            host,
            "post",
            native_id,
            f"https://{host}/posts/{native_id}",
            f"{booru_platform}-post",
        )
    elif (
        reference is None
        and booru_platform in {"danbooru", "e621"}
        and (match := re.fullmatch(r"/artists/(\d+)", path))
    ):
        native_id = match.group(1)
        reference = _reference(
            booru_platform,
            host,
            "artist",
            native_id,
            f"https://{host}/artists/{native_id}",
            f"{booru_platform}-artist",
        )
    elif (
        reference is None
        and booru_platform in {"danbooru", "e621"}
        and (match := re.fullmatch(r"/data/(?:[^/]+/)*([0-9a-fA-F]{32,64})\.[a-zA-Z0-9]+", path))
    ):
        asset_id = match.group(1).lower()
        reference = _reference(
            booru_platform,
            host,
            "media_asset",
            asset_id,
            canonical.canonical_url,
            f"{booru_platform}-media",
        )
    elif reference is None and booru_platform == "gelbooru":
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if (
            query.get("page") == "post"
            and query.get("s") == "view"
            and query.get("id", "").isdigit()
        ):
            native_id = query["id"]
            target = f"https://gelbooru.com/index.php?page=post&s=view&id={native_id}"
            reference = _reference("gelbooru", host, "post", native_id, target, "gelbooru-post")
        elif (
            query.get("page") == "artist"
            and query.get("s") == "show"
            and query.get("id", "").isdigit()
        ):
            native_id = query["id"]
            target = f"https://{host}/index.php?page=artist&s=show&id={native_id}"
            reference = _reference("gelbooru", host, "artist", native_id, target, "gelbooru-artist")
    configured_mastodon = MASTODON_INSTANCES | (mastodon_instances or frozenset())
    if (
        reference is None
        and host in configured_mastodon
        and (match := re.fullmatch(r"/@([^/]+)/(\d+)", path))
    ):
        native_id = match.group(2)
        reference = _reference(
            "mastodon",
            host,
            "post",
            native_id,
            f"https://{host}/@{match.group(1)}/{native_id}",
            "mastodon-status",
        )
    elif (
        reference is None
        and host in configured_mastodon
        and (match := re.fullmatch(r"/@([^/]+)", path))
    ):
        handle = match.group(1)
        reference = _reference(
            "mastodon", host, "account", handle, f"https://{host}/@{handle}", "mastodon-account"
        )
    if reference is None:
        reason = "link_hub" if host in LINK_HUB_HOSTS else "unsupported_target"
        canonical = CanonicalURL(
            canonical.original_url,
            canonical.canonical_url,
            canonical.original_query,
            canonical.original_fragment,
            "unresolved",
            reason,
        )
    else:
        canonical = CanonicalURL(
            canonical.original_url,
            canonical.canonical_url,
            canonical.original_query,
            canonical.original_fragment,
            "recognized",
        )
    return RecognizedURL(canonical, reference)


def _reference(
    platform: str, instance: str, kind: str, native_id: str, target: str, recognizer: str
) -> PlatformReferenceRecord:
    return PlatformReferenceRecord(
        platform, instance, kind, native_id, target, recognizer, RECOGNIZER_VERSION
    )


def extract_urls(text: str | None) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(match.group(0).rstrip(".,;:!?") for match in URL_PATTERN.finditer(text))


def account_occurrences(row: Mapping[str, Any]) -> tuple[LinkOccurrence, ...]:
    occurrences: list[LinkOccurrence] = []
    fields = (
        ("website_url", "account.website"),
        ("profile_url", "account.profile"),
        ("bio", "account.bio"),
    )
    for field, context in fields:
        for index, url in enumerate(extract_urls(row.get(field))):
            occurrences.append(
                LinkOccurrence(
                    "account",
                    int(row["account_id"]),
                    context,
                    url,
                    str(row["observed_at"]),
                    account_snapshot_id=int(row["account_snapshot_id"]),
                    raw_observation_id=row.get("raw_observation_id"),
                    json_path=f"$.{field}[{index}]" if field == "bio" else f"$.{field}",
                )
            )
    return tuple(occurrences)


def post_occurrences(
    row: Mapping[str, Any], raw_payload: bytes | None
) -> tuple[LinkOccurrence, ...]:
    found: list[tuple[str, str, str]] = []
    for url in extract_urls(row.get("canonical_url")):
        found.append((url, "post.canonical", "$.canonical_url"))
    for index, url in enumerate(extract_urls(row.get("text_content"))):
        found.append((url, "post.text", f"$.text_content[{index}]"))
    if raw_payload:
        try:
            decoded = json.loads(raw_payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("malformed retained JSON") from error
        found.extend(_raw_urls(decoded))
    return tuple(
        LinkOccurrence(
            "post",
            int(row["post_id"]),
            context,
            url,
            str(row["observed_at"]),
            raw_observation_id=row.get("raw_observation_id"),
            json_path=path,
        )
        for url, context, path in found
    )


def _raw_urls(value: Any, path: str = "$") -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    if not isinstance(value, dict):
        return results
    context_keys = {
        "entities": "post.entity",
        "card": "post.card",
        "quoted_tweet": "post.quote",
        "quoted_status": "post.quote",
        "quote": "post.quote",
    }
    wrapper_keys = {"tweet", "legacy", "data", "status", "bookmark"}
    for key, item in value.items():
        key_lower = key.lower()
        child_path = f"{path}.{key}"
        if key_lower in context_keys:
            results.extend(_urls_in_supported_container(item, child_path, context_keys[key_lower]))
        elif key_lower in {"source", "source_url"} and isinstance(item, str):
            results.extend((url, "post.source", child_path) for url in extract_urls(item))
        elif key_lower in wrapper_keys:
            if isinstance(item, list):
                for index, nested in enumerate(item):
                    results.extend(_raw_urls(nested, f"{child_path}[{index}]"))
            else:
                results.extend(_raw_urls(item, child_path))
    return results


def _urls_in_supported_container(value: Any, path: str, context: str) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if isinstance(item, str) and key.lower() in {
                "url",
                "expanded_url",
                "unwound_url",
                "source",
                "source_url",
                "card_url",
            }:
                results.extend((url, context, child_path) for url in extract_urls(item))
            else:
                results.extend(_urls_in_supported_container(item, child_path, context))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            results.extend(_urls_in_supported_container(item, f"{path}[{index}]", context))
    return results
