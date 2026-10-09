"""Projection specification, digests, and the shared privacy guard.

Every export is a stated recipe, not a convenient dump (gh#6): the
projection spec carries the kind, the projection schema version, all six
policy slots, the tool version, and the source database schema version.
Its digest is deterministic across re-runs with identical inputs; the
generation timestamp deliberately stays out of the spec (it lives in the
manifest) so the recipe identity never depends on when it ran.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

PROJECTION_SCHEMA_VERSION = "export-projections-v1"

POLICY_SLOTS = (
    "selection",
    "ordering",
    "dedup",
    "preferred_representation",
    "field_source",
    "url_handling",
)


def canonical_json(value: Any) -> str:
    """Deterministic JSON text: sorted keys, no incidental whitespace."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tool_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("data-processing-tools")
    except PackageNotFoundError:  # pragma: no cover - editable checkouts resolve normally
        return "unknown"


def strip_url_query(url: str | None) -> str | None:
    """Reduce a URL to origin and path: no query, fragment, or credentials."""

    if url is None:
        return None
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return parts.path or None
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return f"{parts.scheme}://{host}{parts.path}"


def enforce_allowlist(row: dict[str, Any], allowlist: tuple[str, ...]) -> dict[str, Any]:
    """Deny-by-default output guard: every emitted field must be declared."""

    allowed = set(allowlist)
    unexpected = sorted(set(row) - allowed)
    if unexpected:
        raise ValueError(
            f"projection row carries fields outside its allowlist: {', '.join(unexpected)}"
        )
    return row


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """Rows plus the audit facts every projection kind must report."""

    rows: list[dict[str, Any]]
    selection_keys: list[str]
    included: int
    exclusions: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ProjectionSpec:
    """The full, stated recipe of one projection execution."""

    kind: str
    projection_schema_version: str
    policies: dict[str, str]
    tool_version: str
    source_schema_version: str

    def __post_init__(self) -> None:
        missing = [slot for slot in POLICY_SLOTS if not self.policies.get(slot)]
        if missing:
            raise ValueError(f"projection spec is missing policies: {', '.join(missing)}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "projection_schema_version": self.projection_schema_version,
            "policies": {slot: self.policies[slot] for slot in POLICY_SLOTS},
            "tool_version": self.tool_version,
            "source_schema_version": self.source_schema_version,
        }

    def digest(self) -> str:
        """Deterministic over identical recipe inputs; no timestamp participates."""

        return sha256_text(canonical_json(self.as_dict()))
