## Context

The evidence layer (migrations 0001-0014) already retains everything a projection needs:
`assets` carries locally verified byte/image facts, `posts`/`media_occurrences` carry
current-value columns guarded by newer-observation-wins UPSERTs with `raw_observation_id`
evidence pointers, and `post_participants` carries roles with review states. The catalog CLI
(`cli.py`, argparse subcommands) has query/inspection surfaces (`assets list`, `stats`,
`search`, `media list`) but no export. The storage query layer already establishes the
privacy idiom (`_redact_row_paths`, deny-by-default column omission in `list_assets`).
Maintainer input (gh#6) requires reproducible, auditable exports; the Phase D relationship
model does not exist yet, so variant-family grouping stays out (kept on the bead).

## Goals / Non-Goals

**Goals:**

- A projection framework whose outputs are self-describing enough to rebuild and audit.
- Two useful first kinds (`assets`, `posts`) that exercise the whole framework end to end.
- JSONL and CSV from one row pipeline so the formats cannot drift logically.
- Plan/run CLI split mirroring the established `reprocess plan|run` idiom.

**Non-Goals:**

- No attribution-disagreement report or per-field source/dissenting-value export (later slice
  on the bead; benefits from gh#9 evidence-dependence modeling).
- No variant-family grouping, thumbnail exclusion, or preferred-original selection — these
  need Phase D typed relationships; the manifest still carries the policy fields as
  explicit `not_applicable_pending_phase_d` markers so the recipe shape is stable.
- No streaming/incremental exports, no parquet, no scheduling; bounded single-shot files only.
- No writes to the catalog, no new tables, no migrations.

## Decisions

### 1. Manifest sidecar, not provenance embedded per row

Rows carry only stable evidence-layer identifiers; the full recipe (policies, versions,
counts, digests) lives in `<name>.manifest.json` written next to the data files. This follows
gh#6's own suggestion ("a manifest/sidecar plus stable evidence-layer references may be
better") and keeps CSV rows clean. Alternative — embedding a recipe digest in every row —
rejected: redundant, noisy in CSV, and the manifest already binds files by content digest.

### 2. Three digest layers with exact stability contracts

- `spec_digest`: sha256 over canonical JSON (sorted keys, no whitespace) of the spec object
  (kind, projection schema version, all policy inputs, tool version, source schema version).
  Deliberately excludes the generation timestamp and file digests, so identical policy on the
  same tool/schema versions reproduces it.
- `selection_digest`: sha256 over the newline-joined ordered stable identifier tuples of
  included rows (`assets`: `asset_id:verified_sha256`; `posts`: `post_id:platform:native_id`).
  Stable across re-runs on unchanged evidence; moves when rows enter/leave the selection.
- per-file `content_digest`: sha256 of the file bytes, binding the manifest to exact output.

Manifest itself is not digested (it contains its own file digests); `spec_digest` +
`selection_digest` + per-file digests give the audit chain gh#6 asks for.

### 3. One row pipeline, two serializers

Each projection kind yields typed dataclass rows in the stated order; JSONL serializes the
row dict directly; CSV flattens the same dict with a deterministic column order (nested
summaries serialized as canonical JSON strings). Logical-equivalence tests compare parsed
JSONL rows against CSV rows. Alternative — separate queries per format — rejected: drift risk.

### 4. Deny-by-default allowlist per kind, shared privacy guard

Each kind declares its emitted columns; a shared guard strips URL query components
(`urlsplit` → origin+path) and rejects/filters any field not on the allowlist at row-build
time. Storage paths never enter row construction (same stance as `list_assets`, which
deliberately omits `storage_path`). This is test-enforced, not convention-enforced.

### 5. Policies are data, stated even when not applicable

The spec object always carries all six policy slots (`selection`, `ordering`, `dedup`,
`preferred_representation`, `field_source`, `url_handling`). For `assets`/`posts`,
`preferred_representation` is `not_applicable_pending_phase_d` and `dedup` is
`content_identity_by_sha256` (assets) / `none_post_identity` (posts). The recipe shape is
therefore stable when later kinds add real policies, and the manifest never has hidden
defaults.

### 6. New `projections` package, read-only queries

`src/media_catalog/projections/` with `spec.py` (spec + digests), `manifest.py`,
`assets_projection.py`, `posts_projection.py`, and `service.py` (plan/run orchestration).
Queries read via `CatalogDatabase` connections like the storage query layer; no writer is
imported. CLI adds `export plan|run`. This keeps the framework replaceable without touching
persistence.

## Risks / Trade-offs

- [Large catalogs produce big single-shot files] → the row limit is mandatory (default 10_000,
  max 100_000) and the manifest reports `excluded_by_limit` with the stated ordering, so a
  bounded export is always honest about what it left out.
- [CSV flattening of nested summaries is clunkier than native JSON] → nested fields use
  canonical JSON strings; JSONL remains the canonical format and CSV the tabular convenience.
- [Selection digest changes on re-export after benign evidence growth] → that is the desired
  semantics (evidence moved), and the manifest makes the diff auditable; no attempt to mask it.
- [Posts current-value pointer is row-level, not per-field] → accepted for this slice; the
  manifest's field-source policy states `current_row_pointer` explicitly, and per-field source
  export remains a tracked later slice rather than an unstated approximation.

## Migration Plan

None: read-only feature, no schema changes. Rollback is deleting the command surface.

## Open Questions

None blocking; the not-yet-built projections (disagreement report, per-field source,
variant families) inherit the framework and only add kinds/policies.
