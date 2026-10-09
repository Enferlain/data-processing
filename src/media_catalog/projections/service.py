"""Export projection orchestration: read-only planning and file-writing runs.

``plan`` previews a projection (policy echo, would-be counts, exclusion
reasons) without writing anything; ``run`` writes JSONL/CSV data files plus
a manifest sidecar into an operator-chosen directory.  Both open the
catalog through the no-write read-only snapshot, and neither ever contacts
a network service.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.projections import assets, output, posts
from media_catalog.projections.spec import (
    PROJECTION_SCHEMA_VERSION,
    ProjectionSpec,
    canonical_json,
    tool_version,
)

DEFAULT_LIMIT = 10_000
MAX_LIMIT = 100_000
FORMATS = ("jsonl", "csv")

_KINDS: dict[str, Any] = {assets.KIND: assets, posts.KIND: posts}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _validate(kind: str, limit: int, platform: str | None, formats: tuple[str, ...]) -> None:
    if kind not in _KINDS:
        raise ValueError(f"unknown projection kind {kind!r}; choose one of {sorted(_KINDS)}")
    if not 0 < limit <= MAX_LIMIT:
        raise ValueError(f"export limit must be between 1 and {MAX_LIMIT}")
    if kind == assets.KIND and platform is not None:
        raise ValueError("the assets projection does not support a platform filter")
    for form in formats:
        if form not in FORMATS:
            raise ValueError(f"unknown export format {form!r}; choose from {FORMATS}")


def _spec(database: CatalogDatabase, kind: str, platform: str | None) -> ProjectionSpec:
    module = _KINDS[kind]
    policies = dict(module.POLICIES)
    if platform is not None:
        policies["selection"] = f"{policies['selection']} (platform={platform})"
    return ProjectionSpec(
        kind=kind,
        projection_schema_version=PROJECTION_SCHEMA_VERSION,
        policies=policies,
        tool_version=tool_version(),
        source_schema_version=str(database.schema_version),
    )


def _counts(result: Any) -> dict[str, Any]:
    return {"included": result.included, "excluded": result.exclusions}


def plan_export(
    catalog: Path,
    *,
    kind: str,
    limit: int = DEFAULT_LIMIT,
    platform: str | None = None,
) -> dict[str, Any]:
    """Preview a projection: policy echo and would-be counts, nothing written."""

    _validate(kind, limit, platform, FORMATS)
    with CatalogDatabase.open_read_only(catalog) as database:
        module = _KINDS[kind]
        spec = _spec(database, kind, platform)
        result = module.build(database.connection, limit=limit, platform=platform)
    return {
        "catalog": str(catalog),
        **spec.as_dict(),
        "spec_digest": spec.digest(),
        "identifiers": dict(module.IDENTIFIERS),
        "counts": _counts(result),
        "preview": True,
    }


def run_export(
    catalog: Path,
    *,
    kind: str,
    out_dir: Path,
    formats: tuple[str, ...] = FORMATS,
    limit: int = DEFAULT_LIMIT,
    platform: str | None = None,
    clock: Any = _utc_now,
) -> dict[str, Any]:
    """Write the projection's data files and manifest sidecar; read-only on the catalog."""

    _validate(kind, limit, platform, formats)
    with CatalogDatabase.open_read_only(catalog) as database:
        module = _KINDS[kind]
        spec = _spec(database, kind, platform)
        result = module.build(database.connection, limit=limit, platform=platform)
    out_dir.mkdir(parents=True, exist_ok=True)
    writers = {"jsonl": output.write_jsonl, "csv": output.write_csv}
    files: list[dict[str, Any]] = []
    for form in formats:
        path = out_dir / f"{kind}-projection.{form}"
        row_count, content_digest = writers[form](result.rows, path)
        files.append(
            {
                "name": path.name,
                "format": form,
                "row_count": row_count,
                "content_digest": content_digest,
            }
        )
    manifest = {
        **spec.as_dict(),
        "generated_at": str(clock()),
        "files": files,
        "counts": _counts(result),
        "identifiers": dict(module.IDENTIFIERS),
        "spec_digest": spec.digest(),
        "selection_digest": output.selection_digest(result.selection_keys),
    }
    manifest_path = out_dir / f"{kind}-projection.manifest.json"
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8", newline="")
    return {
        "catalog": str(catalog),
        "out_dir": str(out_dir),
        "manifest": str(manifest_path),
        **manifest,
    }
