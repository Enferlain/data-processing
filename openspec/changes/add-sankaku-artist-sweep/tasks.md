# Tasks

- [x] 1. `remote_sync/artist_sweep.py`: ranked names, per-name sync with
  skip/budget/pacing, failure containment, md5 overlap report.
  Verify: `uv run pytest tests/test_artist_sweep.py`.
- [x] 2. CLI `catalog metadata sankaku-sweep` (discover-only) + tests.
  Verify: `uv run catalog metadata sankaku-sweep --help` + CLI registration.
- [ ] 3. Gates: full pytest, ruff + format, ty; review; commit; archive;
  update hvs.
