from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from media_catalog.adapters import NormalizedPage
from media_catalog.records import (
    AccountRecord,
    AttributionRecord,
    MediaOccurrenceRecord,
    PostExternalReferenceRecord,
    PostRecord,
    TagObservationRecord,
)
from media_catalog.writer import CatalogWriter


class NormalizedPageWriter:
    """Persist one normalized provider page without owning its transaction."""

    def __init__(self, writer: CatalogWriter) -> None:
        self.writer = writer

    def write(
        self,
        page: NormalizedPage,
        *,
        observed_at: str,
        raw_observation_id: int,
        adapter_version: str,
    ) -> int:
        accounts: dict[tuple[str, str], int] = {}
        posts: dict[tuple[str, str], int] = {}
        for item in page.items:
            data = item.data
            platform = _required_text(data, "platform")
            native_id = item.native_id or _required_text(data, "native_id")
            if item.object_kind == "account":
                result = self.writer.upsert_account(
                    AccountRecord(
                        platform=platform,
                        native_id=native_id,
                        observed_at=_text(data.get("observation_time")) or observed_at,
                        canonical_url=_text(data.get("canonical_url")),
                        availability=_text(data.get("availability")) or "available",
                        handle=_text(data.get("handle")),
                        display_name=_text(data.get("display_name")),
                        bio=_text(data.get("bio")),
                        avatar_url=_text(data.get("avatar_url")),
                        banner_url=_text(data.get("banner_url")),
                        followers=_integer(data.get("followers")),
                        following=_integer(data.get("following")),
                    ),
                    raw_observation_id=raw_observation_id,
                )
                accounts[(platform, native_id)] = result.id
                links = data.get("external_links")
                if isinstance(links, list):
                    for link in links:
                        if not isinstance(link, Mapping):
                            continue
                        url = _text(link.get("url"))
                        if url is not None:
                            self.writer.add_account_external_link(
                                result.id,
                                url,
                                _text(link.get("source_context")) or "account.profile",
                                _text(data.get("observation_time")) or observed_at,
                                raw_observation_id=raw_observation_id,
                            )
            elif item.object_kind == "post":
                result = self.writer.upsert_post(
                    PostRecord(
                        platform=platform,
                        native_id=native_id,
                        observed_at=_text(data.get("observation_time")) or observed_at,
                        canonical_url=_text(data.get("canonical_url")),
                        text=_text(data.get("text") or data.get("caption")),
                        created_at=_text(data.get("created_at")),
                        updated_at=_text(data.get("updated_at")),
                        availability=_text(data.get("availability")) or "available",
                        status=_text(data.get("status")),
                        title=_text(data.get("title")),
                        rating=_text(data.get("rating")),
                        provider_post_type=_text(
                            data.get("provider_type") or data.get("type")
                        ),
                    ),
                    raw_observation_id=raw_observation_id,
                )
                posts[(platform, native_id)] = result.id
            elif item.object_kind == "attribution":
                self.writer.upsert_attribution(
                    AttributionRecord(
                        platform=platform,
                        native_id=native_id,
                        adapter_version=adapter_version,
                        observed_at=observed_at,
                        availability=(
                            "deleted" if data.get("deleted") is True else "available"
                        ),
                        primary_name=_text(data.get("name")),
                        other_names=tuple(_string_list(data.get("other_names"))),
                        urls=tuple(_string_list(data.get("urls"))),
                        is_deleted=_boolean(data.get("deleted")),
                    ),
                    raw_observation_id=raw_observation_id,
                )

        for item in page.items:
            data = item.data
            platform = _required_text(data, "platform")
            if item.object_kind == "post_participant":
                post_id = self._post_id(
                    posts, platform, data.get("post_id"), observed_at
                )
                account_native = _required_text(data, "account_id")
                account_id = accounts.get((platform, account_native))
                if account_id is None:
                    account_id = self.writer.upsert_account(
                        AccountRecord(platform, account_native, observed_at),
                        raw_observation_id=raw_observation_id,
                    ).id
                self.writer.add_participant(
                    post_id,
                    account_id,
                    _required_text(data, "role"),
                    raw_observation_id=raw_observation_id,
                )
            elif item.object_kind == "post_tag":
                post_id = self._post_id(
                    posts, platform, data.get("post_id"), observed_at
                )
                self.writer.upsert_tag(
                    post_id,
                    TagObservationRecord(
                        platform=platform,
                        category=_text(data.get("category")) or "general",
                        normalized_name=_required_text(data, "normalized_name"),
                        provider_spelling=_required_text(data, "spelling"),
                        observed_at=observed_at,
                        normalization_version="provider-tag-v1",
                        translated_label=_text(data.get("translated_name")),
                        position=_integer(data.get("position")),
                    ),
                    raw_observation_id=raw_observation_id,
                )
            elif item.object_kind == "media_occurrence":
                post_id = self._post_id(
                    posts, platform, data.get("post_id"), observed_at
                )
                self._write_media(post_id, data, observed_at, raw_observation_id)
            elif item.object_kind == "external_reference":
                post_id = self._post_id(
                    posts, platform, data.get("post_id"), observed_at
                )
                target_platform = _text(data.get("target_platform"))
                self.writer.add_post_external_reference(
                    post_id,
                    PostExternalReferenceRecord(
                        reference_kind=_text(data.get("reference_kind"))
                        or "provider_id",
                        observed_at=observed_at,
                        url=_text(data.get("value")),
                        target_platform=target_platform,
                        target_object_kind=(
                            _text(data.get("object_kind")) if target_platform else None
                        ),
                        target_identifier_kind=(
                            _text(data.get("identifier_kind")) if target_platform else None
                        ),
                        target_native_id=(
                            _text(data.get("native_identifier")) if target_platform else None
                        ),
                    ),
                    raw_observation_id=raw_observation_id,
                )
            elif item.object_kind == "post_relation":
                source_id = self._post_id(
                    posts, platform, data.get("source_post_id"), observed_at
                )
                target_id = self._post_id(
                    posts, platform, data.get("target_post_id"), observed_at
                )
                self.writer.add_relation(
                    source_id,
                    target_id,
                    _required_text(data, "relation_type"),
                    raw_observation_id=raw_observation_id,
                )
        return len(page.items)

    def _write_media(
        self,
        post_id: int,
        data: Mapping[str, Any],
        observed_at: str,
        raw_observation_id: int,
    ) -> None:
        variants_json = _text(data.get("variants_json"))
        if variants_json is None and isinstance(data.get("variants"), list):
            variants_json = json.dumps(
                {"version": "provider-variants-v1", "variants": data["variants"]},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        mime_type = _text(data.get("mime_type") or data.get("media_type"))
        self.writer.upsert_media(
            post_id,
            MediaOccurrenceRecord(
                source_key=_required_text(data, "source_key"),
                index=_integer(data.get("index")) or 0,
                media_type=_text(data.get("media_type")) or mime_type or "unknown",
                role=_text(data.get("role")),
                remote_url=_text(data.get("remote_url")),
                preview_url=_text(data.get("preview_url")),
                mime_type=mime_type,
                width=_integer(data.get("width")),
                height=_integer(data.get("height")),
                duration_ms=_integer(data.get("duration_ms")),
                variants_json=variants_json,
                availability=_text(data.get("availability")) or "available",
                declared_md5=_text(data.get("declared_md5")),
                declared_sha256=_text(data.get("declared_sha256")),
                declared_file_size=_integer(data.get("declared_file_size")),
                observed_at=observed_at,
            ),
            raw_observation_id=raw_observation_id,
        )

    def _post_id(
        self,
        posts: Mapping[tuple[str, str], int],
        platform: str,
        native_value: object,
        observed_at: str,
    ) -> int:
        native_id = _required_text({"value": native_value}, "value")
        existing = posts.get((platform, native_id))
        if existing is not None:
            return existing
        return self.writer.upsert_post(
            PostRecord(platform, native_id, observed_at)
        ).id


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _required_text(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not value:
        raise ValueError(f"normalized {name} must be a non-empty string")
    return value


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _boolean(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]
