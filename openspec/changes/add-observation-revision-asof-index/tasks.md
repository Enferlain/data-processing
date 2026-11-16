# Tasks

- [ ] 1. Migration `0039_observation_revision_asof_index.sql`: the playback
  index; backup pins 38→39.
  Verify: `uv run pytest tests/test_observation_asof.py tests/test_catalog_backup.py`.
- [ ] 2. Tests: index present, EXPLAIN QUERY PLAN is an indexed seek with no
  scan, UPDATE/DELETE abort on both provenance tables; as-of query documented
  in the kernel docs.
  Verify: `uv run pytest tests/test_observation_asof.py`.
- [ ] 3. Gates: full pytest, ruff + format, ty; review; commit; archive;
  close i94.
