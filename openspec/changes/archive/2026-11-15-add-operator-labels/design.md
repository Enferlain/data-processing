# Design

## Context

The catalog's tag surfaces are provider-observed facts anchored to raw
observations; relationships pair subjects via decisions. Neither gives the
operator a place to write local knowledge. Bead `data-processing-j7l` (reframed
2026-11-15): no hardcoded vocabulary — free-form labels, searchable, usable as
groupings; identical content shares labels across platforms.

## Decisions

- **Two tables, the provenance-kernel style.** `operator_labels` (unique
  COLLATE NOCASE name 1–100 chars, description, `created_at`, nullable
  `retired_at` — retire marks, never deletes). `operator_label_assertions`
  (label FK, `subject_kind IN ('file_seed','post','asset','work')`,
  `subject_id`, `state IN ('applied','revoked')`, `asserted_by`, `note`,
  `observed_at`): append-only rows; current state = latest `observed_at` per
  (label, subject) with rowid as tiebreak. Index on (label, subject_kind,
  subject_id) serves latest-state lookups and search.
- **Polymorphic subjects without FKs**, exactly the `relationships` precedent
  (`subject_kind`/`subject_id` CHECKs, no cross-table FK). Subject kind for
  bare files is `file_seed` (`discovery_file_seeds`), which relationships
  vocabulary lacks but operator labels needs — the grabber corpus is mostly
  file seeds.
- **Removal semantics.** Label removal = retirement (history intact,
  applications refused while retired). Assertion removal = revoke row. Both
  keep as-of reconstructability.
- **Identity expansion at query time, not write time.** "Identical" =
  byte-identical by hash: (1) file seeds sharing (verified_md5,
  verified_sha256); (2) seed↔post where an occurrence's declared md5 equals the
  seed's verified md5; (3) post↔post sharing a declared md5. That is the same
  standard the identical-md5 auto-confirm family already trusts. Materialized
  copies would go stale when relationships are re-decided; variants
  deliberately do not inherit.
- **CLI family `tag`** (`catalog tag ...`), a new command family module — the
  existing `catalog label` command is the interactive pair-calibration server
  and keeps its name. Subcommands: `create`, `list` (with counts), `remove`
  (retire), `apply`, `revoke`, `show` (labels on a subject, direct and
  identical-content inherited marked), `search`. Attribution `--by` defaults to
  the operator identity; JSON output everywhere like sibling commands.
- **Nature facts later, as labels.** `ai-generated`/`ai-assisted` (already
  observed provider tags on 25/13 posts today) can seed *suggestions* that
  offer to apply operator labels — a follow-up that needs no schema change.
- **Latest-wins determinism.** Current state per (label, subject) is the
  assertion with the greatest `(observed_at, operator_label_assertion_id)` —
  numeric id as tiebreak, both ordered numerically in one ROW_NUMBER window.
  No text key concatenation (text comparison would misorder ids 9 vs 10), and
  no uniqueness constraint is needed: two assertions in the same microsecond
  resolve deterministically by insertion order.
- Search expansion over shared declared md5 can fan out on wildly popular
  bytes (e.g. placeholder images); bounded reporting (limit + exact totals,
  the house style) contains it.

## Migration Plan

One additive migration (0036). No rebuilds; rollback is the standard
pre-migration catalog backup. The running crosscheck loop applies it on its
next pass's catalog open, same as 0035.
