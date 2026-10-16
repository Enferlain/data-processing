## Context

`post_relations` (migration 0001) is the retained home of provider/import post relations:
the danbooru adapter emits `parent_of` from `parent_id`/`has_children`, and X imports write
`quote`/`reply`. The real catalog holds 65 rows (62 quote, 2 reply, 1 parent_of). The
deterministic seeder currently materializes three kinds and skips this evidence.

## Goals / Non-Goals

**Goals:** seed `parent_of` from retained relations, idempotently, with provider-declaration
evidence.

**Non-Goals:** no `quote`/`reply` Phase D kinds (discourse facts; separate vocabulary
decision), no variant-level (sub-occurrence) thumbnail seeding for danbooru, no unresolved
source-URL resolution.

## Decisions

- Orientation: `parent_of` parent → child matches the adapter's own emission direction
  (`_relation(parent_id, post_id, "parent_of")`), so `source_post_id` is the subject.
- Evidence: `evidence_kind = 'provider_parent_relation'`, detector
  `provider-parent-relation`, `platform_reference_id` unused; the `raw_observation_id` on
  the relation row links the declaration's source report — carried in the evidence
  components so no schema surface changes.
- Relations without a raw observation still materialize (the provider declaration is the
  fact); only unusable endpoints (missing post rows are impossible — FK-enforced) skip.
- The seeding requirement text gains the fourth kind; scenarios unchanged otherwise.

## Risks / Trade-offs

- [X `quote`/`reply` remain unseeded] → deliberate boundary, tracked for a vocabulary
  decision; the audit bead records it.

## Migration Plan

None.

## Open Questions

None.
