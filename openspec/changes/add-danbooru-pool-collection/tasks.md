# Tasks: add-danbooru-pool-collection

## 1. Vocabulary and storage

- [ ] 1.1 Add `fetch_pool` to `AdapterOperation` (`src/media_catalog/adapters/contracts.py`) and `REMOTE_OPERATIONS` (`src/media_catalog/records/common.py`)
- [ ] 1.2 Migration `0016_pools.sql`: `pool_observations` (platform, pool native id, observed_at, raw observation, digest over pool id + ordered post ids, UNIQUE dedup) and `pool_member_observations` (pool observation FK, position, post native id, nullable post link), immutability triggers per the kernel audit tier
- [ ] 1.3 Records + persistence + writer facade: `PoolObservationRecord` (+ member shape) and `record_pool_observation` writing pool observation, members, and post-view `post_pool_observations` links for retained posts, idempotently by digest

## 2. Adapter and sync surface

- [ ] 2.1 Danbooru adapter `_request_parts`: `FETCH_POOL` → `GET /pools/{target}.json` with stable identity
- [ ] 2.2 `src/media_catalog/remote_sync/pools.py`: bounded `fetch_pool` flow — begin run with budgets, adapter request, remote request row, `store_raw` (object_kind `pool`), normalize the pool document (id, ordered post_ids) into observations, finish run with typed outcome; offline and testable with a stubbed transport
- [ ] 2.3 CLI `mcat remote pool-fetch --provider danbooru --pool-id N` wiring the surface

## 3. Fixtures, tests, docs

- [ ] 3.1 Capture one real `/pools/{id}.json` document into `tests/fixtures/metadata_adapters/` (plus a reordered synthetic variant)
- [ ] 3.2 Tests: ordered membership retained with positions and native ids; unretained members keep NULL post links; unchanged re-fetch idempotent by digest; reorder lands a new observation; no relationships/works created; run budget/outcome recorded; immutability triggers reject mutation
- [ ] 3.3 Update surface digests in `tests/test_persistence_compatibility.py` (new records/writer surface), `CHANGELOG.md`, and the danbooru docs surface if it enumerates operations

## 4. Validation

- [ ] 4.1 Gates: `uv run ruff check .`, `uv run ruff format --check`, `uv run ty check src`, `uv run pytest`
- [ ] 4.2 `openspec validate add-danbooru-pool-collection` and a subagent review of the slice before committing
