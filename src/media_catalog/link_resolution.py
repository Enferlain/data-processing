"""Resolve supported-site URLs into adapter operations and targets.

Pure parsing, no network: every grammar below mirrors the canonical URL a
normalizer already produces for its platform, so a URL the catalog itself
would write is always a URL the catalog can read back.  The resolution maps
a pasted link to ``(platform, operation, target)`` for the existing metadata
sync surfaces; media bytes stay on the managed-asset pipeline that the
synced occurrences feed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NoReturn
from urllib.parse import parse_qs, urlsplit

from media_catalog.adapters.contracts import AdapterOperation

_DIGITS = re.compile(r"^[1-9][0-9]*$")
_SANKAKU_ID = re.compile(r"^[A-Za-z0-9]{4,32}$")


class LinkResolutionError(ValueError):
    """A URL no supported platform claims, with an actionable message."""


_DIGITS = re.compile(r"^[1-9][0-9]*$")
_SERVICE = re.compile(r"^[a-z][a-z0-9_-]*$")
_SANKAKU_ID = re.compile(r"^[A-Za-z0-9]{4,32}$")


@dataclass(frozen=True, slots=True)
class ResolvedLink:
    platform: str
    operation: AdapterOperation
    target: str
    canonical_url: str
    instance_note: str | None = None


def _fail(url: str, detail: str) -> NoReturn:
    raise LinkResolutionError(f"unsupported url ({detail}): {url}")


def _post_id(value: str) -> str:
    if not _DIGITS.match(value):
        raise LinkResolutionError(f"not a numeric post id: {value!r}")
    return value


def _split(url: str) -> tuple[str, list[str], dict[str, list[str]]]:
    try:
        parts = urlsplit(url.strip())
    except ValueError as error:
        raise LinkResolutionError(f"unparseable url: {url}") from error
    if parts.scheme != "https":
        _fail(url, "https url required")
    hostname = parts.hostname
    if not hostname:
        _fail(url, "https url required")
    host = hostname.lower()
    path = [segment for segment in parts.path.split("/") if segment]
    return host, path, parse_qs(parts.query)


def _query_post_id(query: dict[str, list[str]], url: str) -> str:
    page = query.get("page", [""])[-1]
    view = query.get("s", [""])[-1]
    post_id = query.get("id", [""])[-1]
    if (page, view) != ("post", "view") or not post_id:
        _fail(url, "not a gelbooru-family post url")
    return _post_id(post_id)


# ── Per-platform resolvers ───────────────────────────────────────────────


_DANBOORU_HOST_PLATFORMS = {
    "danbooru.donmai.us": "danbooru",
    "aibooru.online": "aibooru",
    "www.aibooru.online": "aibooru",
}


def _danbooru_family(
    url: str, host: str, path: list[str], query: dict[str, list[str]]
) -> ResolvedLink:
    del query
    platform = _DANBOORU_HOST_PLATFORMS[host]
    segments = [segment for segment in path if segment not in {"en", "ja"}]
    kind = segments[0] if segments else ""
    if kind != "posts" or len(segments) != 2:
        _fail(url, f"expected /posts/<id> on {host}")
    post_id = _post_id(segments[1].removesuffix(".json"))
    return ResolvedLink(
        platform=platform,
        operation=AdapterOperation.FETCH_POST,
        target=post_id,
        canonical_url=f"https://{host}/posts/{post_id}",
    )


_E621_HOST_PLATFORMS = {"e621.net": "e621", "e926.net": "e926"}


def _e621_family(url: str, host: str, path: list[str], query: dict[str, list[str]]) -> ResolvedLink:
    del query
    platform = _E621_HOST_PLATFORMS[host]
    segments = [segment for segment in path if segment not in {"en"}]
    if len(segments) != 2 or segments[0] != "posts":
        _fail(url, f"expected /posts/<id> on {host}")
    post_id = _post_id(segments[1].removesuffix(".json"))
    return ResolvedLink(
        platform=platform,
        operation=AdapterOperation.FETCH_POST,
        target=post_id,
        canonical_url=f"https://{host}/posts/{post_id}",
    )


_GELBOORU_HOSTS = {
    "gelbooru.com": "gelbooru",
    "safebooru.org": "safebooru",
    "rule34.xxx": "rule34",
    "www.rule34.xxx": "rule34",
    "api.rule34.xxx": "rule34",
}


def _gelbooru_family(
    url: str, host: str, path: list[str], query: dict[str, list[str]]
) -> ResolvedLink:
    del path
    platform = _GELBOORU_HOSTS[host]
    post_id = _query_post_id(query, url)
    canonical_host = "rule34.xxx" if platform == "rule34" else host
    return ResolvedLink(
        platform=platform,
        operation=AdapterOperation.FETCH_POST,
        target=post_id,
        canonical_url=(f"https://{canonical_host}/index.php?page=post&s=view&id={post_id}"),
    )


def _pixiv(url: str, host: str, path: list[str], query: dict[str, list[str]]) -> ResolvedLink:
    del host
    segments = [segment for segment in path if segment != "en"]
    if len(segments) == 2 and segments[0] == "artworks":
        post_id = _post_id(segments[1])
    elif segments == ["member_illust.php"] and query.get("illust_id"):
        post_id = _post_id(query["illust_id"][-1])
    else:
        _fail(url, "expected /artworks/<id> (or member_illust.php?illust_id=)")
    return ResolvedLink(
        platform="pixiv",
        operation=AdapterOperation.FETCH_POST,
        target=post_id,
        canonical_url=f"https://www.pixiv.net/artworks/{post_id}",
    )


def _sankaku(url: str, host: str, path: list[str], query: dict[str, list[str]]) -> ResolvedLink:
    del query
    del host
    segments = [segment for segment in path if not re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", segment)]
    if len(segments) != 2 or segments[0] != "posts":
        _fail(url, "expected /posts/<id> on sankaku")
    post_id = segments[1].removesuffix(".json")
    if not _SANKAKU_ID.match(post_id):
        raise LinkResolutionError(f"not a sankaku post id: {post_id!r}")
    return ResolvedLink(
        platform="sankaku",
        operation=AdapterOperation.FETCH_POST,
        target=post_id,
        canonical_url=f"https://sankaku.app/posts/{post_id}",
    )


def _pawchive(url: str, host: str, path: list[str], query: dict[str, list[str]]) -> ResolvedLink:
    del query
    del host
    if len(path) != 5 or path[1] != "user" or path[3] != "post":
        _fail(url, "expected /<service>/user/<id>/post/<id> on pawchive")
    service, _, user_id, _, post_id = path
    if not _SERVICE.match(service) or not _DIGITS.match(user_id) or not _DIGITS.match(post_id):
        raise LinkResolutionError("pawchive url ids must be a service and numeric ids")
    target = f"{service}:{user_id}:{post_id}"
    return ResolvedLink(
        platform="pawchive",
        operation=AdapterOperation.FETCH_POST,
        target=target,
        canonical_url=f"https://pawchive.pw/{service}/user/{user_id}/post/{post_id}",
    )


_HOST_RESOLVERS = {
    "danbooru.donmai.us": _danbooru_family,
    "aibooru.online": _danbooru_family,
    "www.aibooru.online": _danbooru_family,
    "e621.net": _e621_family,
    "e926.net": _e621_family,
    "www.pixiv.net": _pixiv,
    "pixiv.net": _pixiv,
    "sankaku.app": _sankaku,
    "chan.sankakucomplex.com": _sankaku,
    "www.pawchive.pw": _pawchive,
    "pawchive.pw": _pawchive,
}


def resolve_link(url: str) -> ResolvedLink:
    """Resolve a supported-site URL to its platform, operation, and target."""

    host, path, query = _split(url)
    if host in _GELBOORU_HOSTS:
        return _gelbooru_family(url, host, path, query)
    resolver = _HOST_RESOLVERS.get(host)
    if resolver is None:
        _fail(url, f"no supported platform claims {host}")
    return resolver(url, host, path, query)


RESOLVED_PLATFORMS: frozenset[str] = frozenset(
    {
        "danbooru",
        "aibooru",
        "e621",
        "e926",
        "gelbooru",
        "safebooru",
        "rule34",
        "pixiv",
        "sankaku",
        "pawchive",
    }
)
