# Tasks

- [ ] 1. `run_crosscheck` lane restructure: per-provider workers with own
  connections/adapters, shared budget lock + stop flag, merged counts,
  lane-failure containment.
  Verify: `uv run pytest tests/test_crosscheck.py`.
- [ ] 2. Concurrency tests: all providers' items recorded exactly once,
  counts aggregate exactly, lanes observed overlapping (thread diversity),
  shared budget stop honored across lanes.
  Verify: `uv run pytest tests/test_crosscheck.py tests/test_crosscheck_lanes.py`.
- [ ] 3. Gates: full pytest, ruff + format, ty; review; commit; archive;
  close jq1.
