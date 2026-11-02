"""Real adapter construction per platform, shared by every entry point.

One factory so link-driven fetch, discovery, and the metadata commands can
never drift in credentials, instances, or pacing floors.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from media_catalog.adapters.danbooru import (
    AIBOORU,
    DANBOORU,
    DanbooruAdapter,
    DanbooruCredentials,
)
from media_catalog.adapters.e621 import E621_INSTANCES, E621Adapter, E621Credentials
from media_catalog.adapters.gelbooru import (
    GELBOORU_INSTANCES,
    GelbooruAdapter,
    GelbooruCredentials,
)
from media_catalog.adapters.pawchive import PAWCHIVE_INSTANCES, PawchiveAdapter
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.adapters.sankaku import SANKAKU, SankakuAdapter, SankakuCredentials


def adapter_construction(platform: str) -> tuple[Callable[[httpx.Client], Any], float]:
    """Bind a platform key to its real adapter construction path."""

    if platform in GELBOORU_INSTANCES:
        gelbooru_instance = GELBOORU_INSTANCES[platform]

        def build_gelbooru(client: httpx.Client) -> GelbooruAdapter:
            return GelbooruAdapter(
                gelbooru_instance,
                client=client,
                credentials=(
                    GelbooruCredentials.from_environment(gelbooru_instance)
                    if gelbooru_instance.dapi_credentials_required
                    else GelbooruCredentials.optional_from_environment(gelbooru_instance)
                ),
            )

        return build_gelbooru, gelbooru_instance.minimum_interval_seconds
    if platform in E621_INSTANCES:
        e621_instance = E621_INSTANCES[platform]

        def build_e621(client: httpx.Client) -> E621Adapter:
            return E621Adapter(
                e621_instance,
                client=client,
                credentials=E621Credentials.from_environment(e621_instance),
            )

        return build_e621, e621_instance.minimum_interval_seconds
    if platform in PAWCHIVE_INSTANCES:
        pawchive_instance = PAWCHIVE_INSTANCES[platform]

        def build_pawchive(client: httpx.Client) -> PawchiveAdapter:
            return PawchiveAdapter(pawchive_instance, client=client)

        return build_pawchive, pawchive_instance.minimum_interval_seconds
    if platform in {"danbooru", "aibooru"}:
        danbooru_instance = AIBOORU if platform == "aibooru" else DANBOORU

        def build_danbooru(client: httpx.Client) -> DanbooruAdapter:
            return DanbooruAdapter(
                danbooru_instance,
                client=client,
                credentials=DanbooruCredentials.from_environment(danbooru_instance),
            )

        return build_danbooru, danbooru_instance.minimum_interval_seconds
    if platform == "sankaku":

        def build_sankaku(client: httpx.Client) -> SankakuAdapter:
            return SankakuAdapter(
                client=client, credentials=SankakuCredentials.from_environment(SANKAKU)
            )

        return build_sankaku, SANKAKU.minimum_interval_seconds
    if platform == "pixiv":

        def build_pixiv(client: httpx.Client) -> PixivAdapter:
            return PixivAdapter(require_auth=True, client=client)

        return build_pixiv, 1.0
    raise ValueError(f"unsupported fetch platform: {platform}")
