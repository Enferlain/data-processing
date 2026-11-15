## Proposal

### What

A `pool_member` labeling-queue family over the existing
`post_pool_observations` table: provider-declared pool co-membership pairs
(within one platform namespace, both posts available) enqueue with the
content question, exactly like `provider_parent`.

### Why

Pools tie variants together (operator instinct 2026-11-14). The fact store
already exists and is already populated: the metadata writer records
post→pool membership from payload `pools[]` (145 rows, 62 pools in the live
catalog), and `catalog reprocess` replays retained raws offline through the
same writer. What was missing is consumption — nothing asked the content
question about co-members. A pool can hold re-encodes, variants, and
separate pages, so membership never decides; the verdict stays the
operator's, per the labeling-scope stance.

### Scope

- The queue family (labeling/queue.py A4) + tests + docs.
- Out of scope: any new table or miner (an earlier draft duplicated
  `post_pool_observations` as `pool_membership_hints` — review caught it;
  dropped), danbooru `SEARCH_POOLS` discovery + pool fetch runner (next
  slice), e621 `FETCH_POOL` support, materialization from pool facts.
