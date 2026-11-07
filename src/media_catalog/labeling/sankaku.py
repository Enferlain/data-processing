"""Ephemeral renewal of signed Sankaku delivery URLs; never changes catalog facts."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlsplit

import httpx

from media_catalog.adapters import AdapterFailure, AdapterOperation, AdapterRequest
from media_catalog.adapters.sankaku import SANKAKU, SankakuAdapter, SankakuCredentials


class SankakuDisplayError(ValueError):
    pass


def signed_url_expired(url: str) -> bool:
    query = parse_qs(urlsplit(url).query)
    for name in ("e", "expires"):
        if name in query:
            value = query[name][0]
            if not value.isascii() or not value.isdecimal() or len(value) > 20:
                return True
            if int(value) <= time.time() + 30:
                return True
    return False


class SankakuDisplayResolver:
    """Small in-memory URL cache; credentials and auth tokens stay in the adapter."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str | None, str], tuple[str, float]] = {}
        self._last_refresh = float("-inf")

    def cached(self, post_id: str, source_key: str, md5: str | None, variant: str) -> str | None:
        entry = self._cache.get((post_id, source_key, md5, variant))
        if entry and entry[1] > time.monotonic() and not signed_url_expired(entry[0]):
            return entry[0]
        return None

    def refresh(
        self,
        post_id: str,
        source_key: str,
        md5: str | None,
        variant: str,
        *,
        client: httpx.Client,
        deadline: float,
    ) -> str:
        wait = max(0, SANKAKU.minimum_interval_seconds - (time.monotonic() - self._last_refresh))
        if time.monotonic() + wait >= deadline:
            raise SankakuDisplayError("Sankaku media renewal timed out")
        if wait:
            time.sleep(wait)
        self._last_refresh = time.monotonic()
        try:
            adapter = SankakuAdapter(
                client=client, credentials=SankakuCredentials.from_environment(SANKAKU)
            )
            page = adapter.normalize(
                adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, post_id))
            )
        except (ValueError, AdapterFailure, httpx.HTTPError):
            raise SankakuDisplayError(
                "Sankaku media renewal failed; check provider access"
            ) from None
        if time.monotonic() >= deadline:
            raise SankakuDisplayError("Sankaku media renewal timed out")
        for item in page.items:
            if (
                item.object_kind != "media_occurrence"
                or item.native_id != post_id
                or item.data.get("source_key") != source_key
            ):
                continue
            fresh_md5 = item.data.get("declared_md5")
            if md5 and (not isinstance(fresh_md5, str) or fresh_md5.lower() != md5.lower()):
                raise SankakuDisplayError("Sankaku media changed; refresh catalog metadata")
            urls = {"primary": item.data.get("remote_url"), "preview": item.data.get("preview_url")}
            selected = urls[variant]
            if not isinstance(selected, str) or not selected or signed_url_expired(selected):
                raise SankakuDisplayError("Sankaku did not provide a fresh media URL")
            while len(self._cache) > 126:
                self._cache.pop(next(iter(self._cache)))
            for kind, url in urls.items():
                if isinstance(url, str) and url:
                    self._cache[post_id, source_key, md5, kind] = (url, time.monotonic() + 300)
            return selected
        raise SankakuDisplayError("Sankaku media is no longer available")
