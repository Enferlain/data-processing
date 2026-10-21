## Why

The export-projection layer's last named deliverable (Bead `data-processing-1oi`, from the
original gh#6 ask): exports carrying **which source supplied each field** — per-field
provenance with a stated resolution policy while retaining all dissenting values. The
evidence layer already retains exactly this (post metadata observations with values,
observation times, and raw-observation pointers), and the current-projection policy
(newer observation wins a mutable field) is established; nothing projects it per field yet.

## What Changes

- Add a `post-field-sources` export projection kind: one row per post that has any retained
  post metadata observations. Each row lists, per observed field (score up/down/total,
  favorite count, comment count, availability flags), the full retained value history with
  observation time, the raw-observation evidence pointer, and the source platform — plus the
  field's current value selected under the stated newest-observation-wins policy.
- All dissenting values are retained in the row: a field observed four times with three
  distinct values carries all four entries; the current value names which observation won
  and why (policy statement in the manifest).
- The kind is offline, read-only, bounded with counted exclusions (posts without retained
  metadata observations excluded with a reason; limit overflow counted), privacy-allowlisted
  (no URLs, no payloads, stable evidence-layer identifiers only), and rides the existing
  manifest/digest contracts unchanged.
- Scope boundary: post metadata fields only in this slice (the engagement/availability
  family the observation table retains); tag/name/attribution field-source projection stays
  future work on the bead or a successor.

## Capabilities

### New Capabilities

### Modified Capabilities

- `export-projections`: adds the `post-field-sources` projection kind and its stated
  field-source resolution policy.

## Impact

- New `src/media_catalog/projections/field_sources.py` kind module; registry and CLI choices
  gain the kind; no schema changes.
- Tests: value-history completeness with dissent retained, newest-observation-wins current
  selection, exclusion reasons, digest reproduction, privacy conformance.
- Docs: guide export section gains the kind; changelog entry; bead 1oi closes with the
  slice delivered.
