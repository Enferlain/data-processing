from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from media_catalog.acquisition.policies import PolicyIdentity, policy_identity_for_platform
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    AcquisitionPlanItemRecord,
    AcquisitionPlanRecord,
    normalize_timestamp,
)

PLAN_VERSION = "media-acquisition-plan-v1"
MAX_VARIANTS_JSON_BYTES = 1024 * 1024


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class AcquisitionSelection:
    media_occurrence_id: int
    variant_key: str = "primary"

    def __post_init__(self) -> None:
        if self.media_occurrence_id <= 0:
            raise ValueError("media occurrence id must be positive")
        if not self.variant_key or not self.variant_key.strip() or len(self.variant_key) > 500:
            raise ValueError("variant key must be between 1 and 500 characters")


@dataclass(frozen=True, slots=True)
class PlannedAcquisitionItem:
    item_key: str
    media_occurrence_id: int
    variant_key: str
    selected_url: str | None
    material_digest: str
    request_policy: PolicyIdentity | None
    source_raw_observation_id: int | None
    eligibility: str
    exclusion_reason: str | None
    satisfied_asset_id: int | None
    declared_sha256: str | None
    declared_md5: str | None
    declared_file_size: int | None
    declared_mime_type: str | None
    declared_width: int | None
    declared_height: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_key": self.item_key,
            "media_occurrence_id": self.media_occurrence_id,
            "variant_key": self.variant_key,
            "material_digest": self.material_digest,
            "request_policy_key": self.request_policy.key if self.request_policy else None,
            "request_policy_version": self.request_policy.version if self.request_policy else None,
            "source_raw_observation_id": self.source_raw_observation_id,
            "eligibility": self.eligibility,
            "exclusion_reason": self.exclusion_reason,
            "satisfied_asset_id": self.satisfied_asset_id,
            "declared_sha256": self.declared_sha256,
            "declared_md5": self.declared_md5,
            "declared_file_size": self.declared_file_size,
            "declared_mime_type": self.declared_mime_type,
            "declared_width": self.declared_width,
            "declared_height": self.declared_height,
        }

    def to_record(self, acquisition_plan_id: int, created_at: str) -> AcquisitionPlanItemRecord:
        policy = self.request_policy or PolicyIdentity(
            "unsupported-provider", "unsupported-provider-v1"
        )
        return AcquisitionPlanItemRecord(
            acquisition_plan_id=acquisition_plan_id,
            item_key=self.item_key,
            media_occurrence_id=self.media_occurrence_id,
            variant_key=self.variant_key,
            material_digest=self.material_digest,
            request_policy_key=policy.key,
            request_policy_version=policy.version,
            eligibility=self.eligibility,
            created_at=created_at,
            source_raw_observation_id=self.source_raw_observation_id,
            exclusion_reason=self.exclusion_reason,
            satisfied_asset_id=self.satisfied_asset_id,
            declared_sha256=self.declared_sha256,
            declared_md5=self.declared_md5,
            declared_file_size=self.declared_file_size,
            declared_mime_type=self.declared_mime_type,
            declared_width=self.declared_width,
            declared_height=self.declared_height,
        )


@dataclass(frozen=True, slots=True)
class AcquisitionPlanPreview:
    plan_version: str
    selection_digest: str
    created_at: str
    items: tuple[PlannedAcquisitionItem, ...]
    duplicate_count: int = 0

    @property
    def counts(self) -> dict[str, int]:
        return {
            "requested": len(self.items),
            "eligible": sum(item.eligibility == "eligible" for item in self.items),
            "already_satisfied": sum(
                item.eligibility == "already_satisfied" for item in self.items
            ),
            "excluded": sum(item.eligibility == "excluded" for item in self.items),
            "duplicates": self.duplicate_count,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "selection_digest": self.selection_digest,
            "created_at": self.created_at,
            "counts": self.counts,
            "items": [item.as_dict() for item in self.items],
        }

    def to_record(self) -> AcquisitionPlanRecord:
        counts = self.counts
        return AcquisitionPlanRecord(
            self.plan_version,
            self.selection_digest,
            counts["requested"],
            counts["eligible"],
            counts["already_satisfied"],
            counts["excluded"],
            self.created_at,
        )


def _occurrence(connection: sqlite3.Connection, occurrence_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """SELECT mo.*, post.native_post_id, platform.platform_key
           FROM media_occurrences mo
           JOIN posts post USING(post_id)
           JOIN platforms platform USING(platform_id)
           WHERE mo.media_occurrence_id = ?""",
        (occurrence_id,),
    ).fetchone()


def resolve_occurrence_variants(row: Mapping[str, Any]) -> tuple[dict[str, str], str | None]:
    """Resolve the named acquisition variants for one occurrence.

    The returned URLs are intentionally an internal planning representation.
    Callers that expose this information must project only the variant names;
    the URL is required by the downloader to build its request, but is never a
    safe browsing value.
    """

    variants: dict[str, str] = {}
    remote_url = row["remote_url"]
    preview_url = row["preview_url"]
    if isinstance(remote_url, str) and remote_url:
        variants["primary"] = remote_url
    if isinstance(preview_url, str) and preview_url:
        variants.setdefault("preview", preview_url)
    raw = row["variants_json"]
    if raw is None:
        return variants, None
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_VARIANTS_JSON_BYTES:
        return variants, "invalid_variants"
    try:
        document = json.loads(raw)
    except (TypeError, ValueError):
        return variants, "invalid_variants"
    if not isinstance(document, dict):
        return variants, "invalid_variants"
    entries = document.get("variants")
    if entries is not None:
        if not isinstance(entries, list):
            return variants, "invalid_variants"
        for entry in entries:
            if not isinstance(entry, dict):
                return variants, "invalid_variants"
            role = entry.get("role")
            url = entry.get("url")
            if not isinstance(role, str) or not role or not isinstance(url, str) or not url:
                return variants, "invalid_variants"
            existing = variants.get(role)
            if existing is not None and existing != url:
                return variants, "ambiguous_variant"
            variants[role] = url
    archive = document.get("archive")
    if isinstance(archive, dict) and isinstance(archive.get("url"), str):
        variants.setdefault("archive", archive["url"])
        variants.setdefault("primary", archive["url"])
    return variants, None


# Kept as a compatibility alias for internal callers and older integrations.
_variant_map = resolve_occurrence_variants


def _satisfied_asset(
    connection: sqlite3.Connection,
    row: Mapping[str, Any],
    variant_key: str,
    selected_url: str,
) -> int | None:
    prior = connection.execute(
        """SELECT ari.asset_id
           FROM media_acquisition_run_items ari
           JOIN media_acquisition_plan_items api USING(acquisition_plan_item_id)
           WHERE api.media_occurrence_id = ? AND api.variant_key = ?
             AND ari.state IN ('complete', 'satisfied') AND ari.asset_id IS NOT NULL
           ORDER BY ari.acquisition_run_item_id DESC LIMIT 1""",
        (row["media_occurrence_id"], variant_key),
    ).fetchone()
    if prior is not None:
        return int(prior[0])
    original = selected_url == row["remote_url"] and variant_key in {"primary", "original"}
    if not original:
        return None
    if row["declared_sha256"]:
        match = connection.execute(
            """SELECT a.asset_id FROM occurrence_assets oa
               JOIN assets a USING(asset_id)
               WHERE oa.media_occurrence_id = ? AND a.verified_sha256 = ?
               ORDER BY a.asset_id LIMIT 1""",
            (row["media_occurrence_id"], row["declared_sha256"]),
        ).fetchone()
        if match is not None:
            return int(match[0])
    if row["declared_md5"]:
        match = connection.execute(
            """SELECT a.asset_id FROM occurrence_assets oa
               JOIN assets a USING(asset_id)
               WHERE oa.media_occurrence_id = ? AND a.verified_md5 = ?
               ORDER BY a.asset_id LIMIT 1""",
            (row["media_occurrence_id"], row["declared_md5"]),
        ).fetchone()
        if match is not None:
            return int(match[0])
    return None


def _plan_item(
    connection: sqlite3.Connection,
    selection: AcquisitionSelection,
    policy_resolver: Callable[[str], PolicyIdentity | None],
) -> PlannedAcquisitionItem:
    row = _occurrence(connection, selection.media_occurrence_id)
    item_key = _digest([selection.media_occurrence_id, selection.variant_key])
    if row is None:
        return PlannedAcquisitionItem(
            item_key,
            selection.media_occurrence_id,
            selection.variant_key,
            None,
            _digest(["missing", selection.media_occurrence_id, selection.variant_key]),
            None,
            None,
            "excluded",
            "missing_occurrence",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
    policy = policy_resolver(row["platform_key"])
    variants, variants_error = _variant_map(row)
    selected_url = variants.get(selection.variant_key)
    exclusion_reason = None
    if policy is None:
        exclusion_reason = "unsupported_provider"
    elif row["availability"] != "available":
        exclusion_reason = "unavailable_occurrence"
    elif variants_error is not None:
        exclusion_reason = variants_error
    elif selected_url is None:
        exclusion_reason = "missing_variant"
    original = (
        selected_url is not None
        and selected_url == row["remote_url"]
        and selection.variant_key in {"primary", "original"}
    )
    declared = {
        "sha256": row["declared_sha256"] if original else None,
        "md5": row["declared_md5"] if original else None,
        "file_size": row["declared_file_size"] if original else None,
        "mime_type": row["mime_type"],
        "width": row["width"] if original else None,
        "height": row["height"] if original else None,
    }
    material = {
        "occurrence_id": row["media_occurrence_id"],
        "source_key": row["source_key"],
        "variant_key": selection.variant_key,
        "selected_url": selected_url,
        "availability": row["availability"],
        "raw_observation_id": row["raw_observation_id"],
        "policy": [policy.key, policy.version] if policy else None,
        "declared": declared,
    }
    satisfied_asset_id = (
        _satisfied_asset(connection, row, selection.variant_key, selected_url)
        if selected_url is not None and exclusion_reason is None
        else None
    )
    eligibility = (
        "excluded"
        if exclusion_reason is not None
        else "already_satisfied"
        if satisfied_asset_id is not None
        else "eligible"
    )
    return PlannedAcquisitionItem(
        item_key,
        selection.media_occurrence_id,
        selection.variant_key,
        selected_url,
        _digest(material),
        policy,
        row["raw_observation_id"],
        eligibility,
        exclusion_reason,
        satisfied_asset_id,
        declared["sha256"],
        declared["md5"],
        declared["file_size"],
        declared["mime_type"],
        declared["width"],
        declared["height"],
    )


def evaluate_occurrence_variant(
    connection: sqlite3.Connection,
    selection: AcquisitionSelection,
    *,
    policy_resolver: Callable[[str], PolicyIdentity | None] = policy_identity_for_platform,
) -> PlannedAcquisitionItem:
    """Evaluate one occurrence/variant using the acquisition planner rules.

    This pure, read-only evaluator is shared by media browsing and explicit
    acquisition planning.  It retains the planner's URL-bearing internal
    result so the execution path remains unchanged; browsing must project the
    result without serializing ``selected_url``.
    """

    return _plan_item(connection, selection, policy_resolver)


def plan_acquisition(
    database: CatalogDatabase | Path | str,
    selections: Iterable[AcquisitionSelection],
    *,
    max_items: int,
    clock: Callable[[], str] = _now,
    policy_resolver: Callable[[str], PolicyIdentity | None] = policy_identity_for_platform,
) -> AcquisitionPlanPreview:
    if max_items <= 0:
        raise ValueError("max items must be positive")
    unique: list[AcquisitionSelection] = []
    seen: set[tuple[int, str]] = set()
    duplicate_count = 0
    for selection in selections:
        key = (selection.media_occurrence_id, selection.variant_key)
        if key in seen:
            duplicate_count += 1
            continue
        if len(unique) >= max_items:
            raise ValueError("selection exceeds acquisition planning item limit")
        seen.add(key)
        unique.append(selection)
    if not unique:
        raise ValueError("at least one acquisition selection is required")
    if isinstance(database, CatalogDatabase):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        database.connection.backup(connection)
        connection.execute("PRAGMA query_only = ON")
        close = connection.close
    else:
        catalog = CatalogDatabase.open_read_only(Path(database))
        connection = catalog.connection
        close = catalog.close
    try:
        items = tuple(
            evaluate_occurrence_variant(connection, selection, policy_resolver=policy_resolver)
            for selection in unique
        )
    finally:
        close()
    created_at = normalize_timestamp(clock())
    selection_digest = _digest(
        [[item.media_occurrence_id, item.variant_key, item.material_digest] for item in items]
    )
    return AcquisitionPlanPreview(
        PLAN_VERSION,
        selection_digest,
        created_at,
        items,
        duplicate_count,
    )


def check_planned_item_current(
    database: CatalogDatabase | Path | str,
    planned_item: PlannedAcquisitionItem,
    *,
    policy_resolver: Callable[[str], PolicyIdentity | None] = policy_identity_for_platform,
) -> tuple[bool, str | None]:
    preview = plan_acquisition(
        database,
        [AcquisitionSelection(planned_item.media_occurrence_id, planned_item.variant_key)],
        max_items=1,
        clock=lambda: "1970-01-01T00:00:00Z",
        policy_resolver=policy_resolver,
    )
    current = preview.items[0]
    if current.material_digest != planned_item.material_digest:
        return False, "stale_target"
    return True, None
