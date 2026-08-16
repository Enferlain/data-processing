"""Ephemeral external credentials for Gelbooru JSON-DAPI requests."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from media_catalog.adapters.gelbooru.config import GelbooruInstance


@dataclass(frozen=True, slots=True)
class GelbooruCredentials:
    """A complete DAPI credential pair whose values are never represented publicly."""

    user_id: str = field(repr=False)
    api_key: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.user_id.strip() or not self.api_key.strip():
            raise ValueError("both Gelbooru user ID and API key are required")
        if any(
            ord(character) < 32 for value in (self.user_id, self.api_key) for character in value
        ):
            raise ValueError("Gelbooru credentials must not contain control characters")

    @classmethod
    def from_environment(
        cls,
        instance: GelbooruInstance,
        environ: Mapping[str, str] | None = None,
    ) -> GelbooruCredentials:
        values = os.environ if environ is None else environ
        user_id = values.get(instance.user_id_env)
        api_key = values.get(instance.api_key_env)
        if not user_id or not api_key:
            raise ValueError(f"configure both {instance.user_id_env} and {instance.api_key_env}")
        return cls(user_id, api_key)
