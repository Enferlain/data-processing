## Context

Post sync cannot produce pool facts on danbooru (post payloads carry no pool ids), and the kernel's
Phase D model deliberately separates evidence from conclusions: pool membership ordering is
ordering-bearing work-grouping *evidence* for review-gated conclusions, never an automatic `page_of`
/ `same_work` claim. Storage already has the post-view half (`post_pool_observations`, written by
`record_post_pool`); the pool-view half — one observation per pool with its ordered membership —
does not exist. The bounded-run machinery (`remote_runs`/`remote_requests`/`store_raw`) is proven
for single-object fetches; the operation vocabularies are closed but grow by value.

## Goals / Non-Goals

Goals: one bounded fetch surface for a single danbooru pool by id; ordered membership retained as
immutable observations digest-deduped on (membership, order); post links only for retained posts;
spec delta; fixtures + tests.

Non-Goals: pool *listing*/enumeration (pagination, resumability at pool-set level); pool
description/name normalization beyond identity facts; any work-grouping conclusion or relationship
seeding from pools; other providers (aibooru shares the family adapter but its enabling is a config
step, not new code).

## Decisions

### D1: One pool observation per (pool, digest); members carry the order

`pool_observations(platform_id, pool_native_id, observed_at, raw_observation_id,
observation_digest)` with `UNIQUE (platform_id, pool_native_id, observation_digest)`; the digest
hashes the ordered native-id list (plus pool id), so unchanged re-fetches are idempotent and any
membership *or order* change lands as a new row. `pool_member_observations(pool_observation_id,
position, post_native_id, post_id NULL)` keeps every member by native id at its position;
`post_id` links only already-retained posts (NULL otherwise — the observation stays complete even
when the catalog lags the pool). Both tables storage-immutable from this first migration, per the
kernel audit-history requirement. Ordering lives in rows (queryable), not inside the digest.

### D2: `fetch_pool` joins the closed operation vocabularies by value

`AdapterOperation.FETCH_POOL` and `REMOTE_OPERATIONS += "fetch_pool"` — the media-family pattern
(values are media operations; the closedness is the guard). This is explicitly not the F2
generalization question (bead `data-processing-6y1`), which concerns non-media values.

### D3: A dedicated small sync surface, not the post-page sync loop

`MetadataSyncService.synchronize` is page-of-posts shaped; a pool is one object of a different
kind. `remote_sync/pools.py` owns the flow: begin run (budgets) → adapter `FETCH_POOL` request →
`record_remote_request` → `store_raw` (object_kind `pool`, native id) → normalize into pool +
member + post-view observations → finish run with typed outcome. It reuses the adapter transport
(the adapter gains only a `_request_parts` branch) and the writer facade; no changes to the post
sync service. Post-view membership (`record_post_pool`) is written for retained members so the
existing per-post pool surface sees danbooru pools too.

### D4: Fixture from a real capture

One real `/pools/{id}.json` document captured live (sanitized to identity facts if needed),
committed under `tests/fixtures/metadata_adapters/`, plus a synthetic reordered variant for the
reordering scenario. The fixture is the adapter contract; tests never hit the network.

## Risks / Trade-offs

- [Digest must cover exactly the ordering semantics] → Digest input is the canonical JSON of
  `[pool_native_id, [post ids in order]]`; tested for reorder-sensitivity and stability.
- [Member post links can dangle logically when posts are deleted] → Posts are undeletable in the
  kernel; the link is only written for posts that exist at observation time.
- [Large pools] → One row per member is fine at booru pool sizes (hundreds); no batching needed.
- [Aibooru/e621 enablement] → Same adapter family code path; instance config decides. Out of scope
  here beyond not hard-coding danbooru-only behavior in the sync surface (it takes a platform key).

## Migration Plan

Migration 0016 adds the two tables with immutability triggers; no backfill (no historical pool
data). Rollback: drop tables — nothing else references them.

## Open Questions

None blocking. Whether a future pool *listing* operation shares this surface is deferred until
needed (the requirement's resumable clause names only paginating endpoints).
