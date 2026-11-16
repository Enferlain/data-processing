# Design

## Context

`fetch_pool` (bead cq0) records single pools by id; `post_pool_observations`
is the per-post membership store the labeling family reads. Danbooru post
payloads carry no pool ids, so the online path never fills danbooru pools.
Live capture 2026-11-15 verified `/pools.json?search[name_matches]=X`
returns full pool objects including complete ordered `post_ids`.

## Decisions

- **Discovery and membership in one request.** The search document carries
  ordered membership, so the runner records every returned pool through the
  existing `record_pool_observation` writer (digest over pool id + ordered
  member ids — unchanged pools re-observe idempotently, reorderings land as
  new observations). Per-pool `fetch_pool` remains for targeted refreshes.
- **Request-parts-only adapter change**, the FETCH_POOL precedent: the
  adapter renders the request; the runner owns parsing (`_parse_pool_search`
  requires positive integer ids and member lists, treating any deviation as
  malformed so bad documents fail loudly, never half-recorded).
- **Vocabulary widening needs the three-table rebuild** (0016/0017 idiom):
  `remote_runs`, `remote_checkpoints`, `remote_requests` each carry an
  operation CHECK. Migration 0038 rebuilds all three with `search_pools`
  appended, preserving ids, triggers (including the 0012/0013 immutability
  and no-delete triggers), and indexes.
- **Name source: artist tags by held posts** (`ranked_artist_names`, floor
  of 3 held posts — one-off artists rarely have pools worth a request).
  Resume is run-existence based: a complete `search_pools` run for a target
  marks it searched; failed runs re-run.
- **`object_kind='pool_search'`** for the raw/request rows — distinct from
  `'pool'` so raw scans can distinguish single-pool documents from search
  result arrays.

## Risks

- Artist-name search misses pools named after copyrights/characters rather
  than artists; acceptable for v1 — the corpus is artist-anchored, and
  targeted single-name searches cover the rest.
- Large searches (many pools, long membership lists) make one wide
  transaction; bounded by page size (200) pools per request, each pool
  observation is one row plus members — the same scale `fetch_pool` already
  handles per pool.

0038 rebuilds the three remote tables (vocabulary only, every row and
trigger preserved; validated by the kernel-storage and backup suites).
Rollback is the standard pre-migration backup.
