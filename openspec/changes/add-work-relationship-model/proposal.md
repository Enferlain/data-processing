## Why

The evidence backbone is complete and the export-projection layer has landed, so the remaining
distance to the plan's five-version functioning is the work/relationship model: same bytes,
re-encodes, crops, censored variants, and edits are separately observed objects that need to be
joined by evidence-backed relationships with epistemic status (kernel Phase D, Bead
`data-processing-t08`). The maintainer's design inputs (GitHub issues #2 and #3, 2026-10-07)
require the semantic boundaries to be settled before the first migration hardens them: a
decision table for what belongs to one artifact versus separate artifacts linked by
relationships, and a relationship evidence/review lifecycle that is a durable conclusion object
rather than a repackaged match candidate.

## What Changes

- Add **work entities**: minimal, deterministic, content-neutral anchors — one work per post
  that has media occurrences, linked to its representations (`media_occurrences`). A work
  carries no media vocabulary; the human-level "same work across platforms" emerges from
  reviewed `same_work` relationships plus projections, never from destructive merges.
- Add **one uniform typed-relationship table** with polymorphic endpoints
  (`work` / `media_occurrence` / `post` / `asset`), a closed relationship-kind vocabulary
  (`same_bytes`, `thumbnail_of`, `reposted_from`, `parent_of`, `page_of`, `same_work`,
  `variant_of`, `derived_from`, `reencoded_from`, `resized_from`, `cropped_from`,
  `censored_variant_of`, `edited_from`, `transcoded_from`, `extracted_from`), epistemic status
  (`observed` / `verified` / `derived` / `inferred` / `reviewed`), canonical orientation for
  symmetric kinds, and a deterministic relationship key for idempotency.
- Add the **relationship evidence and review lifecycle** (gh#3): relationships are conclusion
  rows; evidence attaches through the existing `match_evidence` ledger via a join table;
  deterministic kinds materialize without human review but always with evidence; human review
  is append-only and reversible through a decisions ledger; epistemic-status transitions are
  append-only history. Storage-level immutability ships from the first migration per the
  kernel spec.
- Add an **offline deterministic seeder** (`catalog relationships seed`) materializing the
  three already-deterministic kinds from retained evidence: `same_bytes` from SHA-256
  content-deduplicated assets, `thumbnail_of` from provider-declared occurrence variant roles
  (sample/preview → original), and `reposted_from` from provider-declared post source-URL
  references. Idempotent, zero network.
- Add a **`works` export projection kind**: variant-family grouping per work with a stated
  policy — thumbnails/previews excluded from preferred selection, upstream original preferred —
  riding the existing export-projections framework and manifest recipe.
- Leave fuzzy matchers out: they arrive later as `inferred` proposals through the existing
  candidate machinery (matching research tracked separately); this change only guarantees they
  have somewhere to land.
- Grouping concepts (Pixiv series, Danbooru pools, e621 sets) are explicitly **not**
  relationship kinds — they are membership primitives for a future object; the boundary is
  named in the design, no tables for them here.

## Capabilities

### New Capabilities

- `work-relationships`: work entities, the typed relationship model with epistemic status, its
  evidence attachment and append-only review lifecycle, deterministic seeding, and storage
  immutability guarantees.

### Modified Capabilities

- `export-projections`: adds the `works` projection kind (variant-family grouping with
  thumbnail exclusion and upstream-original preference) to the bounded, reproducible export
  surface.

## Impact

- One new migration (works, work representations, relationships, relationship evidence join,
  review decisions, status history) with trigger-enforced immutability tiers; no changes to
  existing tables, no data migration.
- New `src/media_catalog/relationships/` package (records, seeding, review, queries) and a
  `works` kind in `src/media_catalog/projections/`; `catalog` CLI gains `works materialize`,
  `relationships seed|list|review` commands.
- Tests: migration immutability tiers, seeder determinism/idempotency, orientation
  canonicalization, review lifecycle (confirm, reverse, evidence survival), works projection
  policies, export manifest integration.
- Docs: guide sections for works/relationships; changelog entry; roadmap milestone update.
