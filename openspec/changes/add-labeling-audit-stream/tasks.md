# Tasks

- [ ] 1. `build_audit_queue` in `labeling/queue.py`: three seeded, label-
  deduped, media-filtered populations with `audit_*` signals.
  Verify: `uv run pytest tests/test_labeling_audit.py`.
- [ ] 2. `labeling/calibration.py` + `catalog label-stats` report
  (per-signal counts, same/variant rate, Wilson 95% CI).
  Verify: `uv run pytest tests/test_labeling_audit.py -k calibration`.
- [ ] 3. Server/CLI wiring: `catalog label --audit N [--seed S]`; docs.
  Verify: `uv run catalog label --help`.
- [ ] 4. Gates: full pytest, ruff + format, ty; review; commit; archive.
