## Why

The 2026-10-04 gap analysis against `docs/plans/raw_future_plan.md` found the projection layer
to be the other half of the distance to the plan's described functioning: all underlying
evidence (raw observations, declared vs verified facts, attribution evidence per source) is
retained, but the `catalog` CLI has no export surface at all, so consumers cannot get a bounded
view over the evidence layer. Maintainer input (GitHub issue #6, 2026-10-07) sets the quality
bar: exports must be reproducible and auditable — a projection recipe, not a convenient dump —
so a downstream dataset row can answer why it was included, which representation was selected,
which source supplied each field, and whether the same projection can be rebuilt later.

## What Changes

- Add a projection framework: every export declares a projection kind, projection schema
  version, selection/filter policy, ordering policy, deduplication/variant policy,
  preferred-representation policy, field-source policy, and URL-handling policy; emits stable
  evidence-layer identifiers in every row; and writes a manifest sidecar carrying the full
  recipe plus source database/schema versions, tool version, generation timestamp,
  inclusion/exclusion counts with bounded reasons, per-file row counts and content digests, and
  deterministic digests over the projection specification and the exported selection.
- Add two bounded, offline, read-only projection kinds as the first consumers of the framework:
  - `assets` — one row per verified asset (content-addressed identity, locally verified byte
    and image facts, representation-link counts, bounded legacy-assertion classification);
  - `posts` — one row per post (stable platform identity, current mutable facts with their
    evidence pointer, occurrence and participant summaries with review states).
- Add a `catalog export` command surface with `plan` (read-only preview: would-be counts,
  exclusions with reasons, no files written) and `run` (writes JSONL and/or CSV data files
  plus the manifest sidecar into an operator-chosen directory).
- Enforce the repository privacy contract in every output: deny-by-default field allowlists
  per projection kind; no private storage paths, credentials, cookies, signed URLs, or raw
  payloads; remote URLs emitted origin+path only (query strings stripped).
- Later slices (kept on Bead `data-processing-1oi`, not in this change): the
  attribution-disagreement report, per-field source exports with dissenting values, and
  variant-family grouping that needs the Phase D relationship model.

## Capabilities

### New Capabilities

- `export-projections`: bounded, reproducible, auditable JSONL/CSV projections over the
  evidence layer, with a complete manifest recipe, deterministic digests, privacy-safe output,
  and offline read-only execution.

### Modified Capabilities

## Impact

- New `src/media_catalog/projections/` package (spec, manifest, and the two projection kinds)
  reading existing tables only; no schema migrations, no writes to the catalog database.
- `src/media_catalog/cli.py` gains the `export` command group.
- `docs/tools/media-catalog.md` gains an export section; `CHANGELOG.md` records the change.
- Tests: new projection tests covering manifest completeness, digest determinism across
  re-runs on unchanged evidence, digest sensitivity to evidence change, privacy invariants,
  plan/run split, and JSONL/CSV logical equivalence.
