## Proposal

### What

Danbooru pool discovery: `SEARCH_POOLS` adapter operation
(`GET /pools.json?search[name_matches]=<name>`) plus a bounded runner that
records every matching pool's ordered membership, and a
`catalog metadata danbooru-pool-search` CLI with `--discover` mode driving
the catalog's top artist names.

### Why

The pool_member labeling family consumes `post_pool_observations`, which the
online writer fills only when a post payload happens to carry `pools[]` —
e621 does, danbooru does not. Danbooru matched 81.7% of the grabber corpus,
so danbooru pools are where the co-membership evidence actually lives. The
search response carries complete ordered `post_ids` per pool (verified by
live capture 2026-11-15: pool 11225 returned with ~50 ordered members in one
document), so one request per name delivers discovery *and* membership — no
per-pool fetches needed for the discovery lane.

### Scope

- Adapter `SEARCH_POOLS` request path (request-parts only, the FETCH_POOL
  precedent — the runner parses the payload); operation vocabulary widened in
  `AdapterOperation`, `REMOTE_OPERATIONS`, and the three remote-table CHECKs
  (migration 0038, the 0016/0017 rebuild idiom).
- Runner `remote_sync/pool_discovery.py`: `search_pools` (one run/request/
  raw, every parsed pool recorded via `record_pool_observation` anchored to
  that raw) and `discover_pools` (ranked artist names by held posts with a
  floor, prior-run skipping, request budget).
- CLI, tests, docs.
- Out of scope: e621 `FETCH_POOL`/search (e621 membership already flows from
  post payloads), aibooru (zero corpus relevance), pagination past
  `page_size` per name (re-run with a narrower name if ever needed).
