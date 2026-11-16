# Tasks

- [x] 1. Adapter `SEARCH_POOLS` request path + vocabulary (`AdapterOperation`,
  `REMOTE_OPERATIONS`) and migration `0038` widening the three remote-table
  CHECKs (0016 idiom, all triggers preserved); backup pins 37→38.
  Verify: `uv run pytest tests/test_pool_discovery.py tests/test_kernel_storage_enforcement.py`.
- [x] 2. Runner `remote_sync/pool_discovery.py`: `search_pools` recording
  contract; `discover_pools` with ranked artist names, prior-run skipping,
  request budget.
  Verify: `uv run pytest tests/test_pool_discovery.py`.
- [x] 3. CLI `catalog metadata danbooru-pool-search` (single name +
  `--discover`); docs + CHANGELOG.
  Verify: `uv run catalog metadata --help` + live single-name smoke.
- [ ] 4. Gates: full pytest, ruff + format, `ty check src`; review; commit.
- [ ] 5. Live bounded discovery pass on the real catalog (`--discover`,
  small budget), then measure new pool_member pairs.
