# Design

## Context

`post_pool_observations` (migration 0009) is the append-only store of
provider-declared post→pool membership: written online by the metadata
writer when a payload carries `pools[]`, and offline by `catalog reprocess`
replaying retained raws. Ordered, whole-pool evidence lives separately in
`pool_observations`/`pool_member_observations` (bounded pool fetch, bead
cq0). Measured 2026-11-15: 145 membership rows across 62 pools in the live
catalog; danbooru/gelbooru post payloads declare no pools, e621 does.

## Decisions

- **Consume, don't duplicate.** An earlier draft of this change created a
  parallel `pool_membership_hints` table plus a bespoke raw miner; review
  caught the duplication and the draft was dropped. The family reads
  `post_pool_observations` directly; backfill of older raws is
  `catalog reprocess`, the sanctioned replay path — no new tooling.
- **Family `pool_member`** sits after `provider_parent` (both are
  provider-declared relatedness that never proves a content verdict). Pair
  SQL: co-membership join on `pool_native_id` with `post_a < post_b`, both
  posts available, deduped by the queue's existing labeled/seen machinery.
- **Platform-scoped join.** Pool ids are per-platform-namespace (e621 and
  e926 share one; danbooru ids are another), so the join requires
  `p1.platform_id = p2.platform_id` — the same numeric id on two platforms
  must never pair. Same-platform pairs are expected here (a pool belongs to
  one platform), the `provider_parent` precedent.
- **Per the labeling-scope stance**: the family asks only the content
  question; set membership itself is an inherent property the observation
  already records, and the queue detail says so.

## Risks

- Large pools can flood the queue with co-membership pairs; the availability
  filter, the family's position below the A1–A3 families, and the operator's
  verdicts calibrating the family bound it, same as every other family.
- `pair_labels` has no platform scoping of its own; the family's SQL is the
  only guard — tested explicitly (cross-platform same-id never enqueues).

## Migration Plan

None — no schema change. The rollback story is removing the family.
