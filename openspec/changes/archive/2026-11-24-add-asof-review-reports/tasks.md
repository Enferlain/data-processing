# Tasks

## 1. Reconstruction module

- [x] 1.1 `src/media_catalog/temporal.py`: cutoff validation (calendar-checked, Z-normalized), `review_state_snapshot`, `change_report` — latest-wins over the five ledgers, birth-state rule for relationships, arrival counts per the timestamp vocabulary

## 2. CLI surface

- [x] 2.1 `catalog as-of` in `cli_commands/maintenance.py`: `--at` / `--from`+`--to` modes, `--json`

## 3. Tests and gates

- [x] 3.1 `tests/test_temporal_asof.py`: snapshot before/after a reversal; undecided-yet exclusion; relationship birth state; window partitioning (half-open chaining); reversal counting; mixed-precision ordering; cutoff validation; read-only guarantee
- [x] 3.2 Gates: `uv run pytest` (full), `uv run ruff check .`, `uv run ruff format` on touched files, `uv run ty check src`

## Workflow follow-up

- Archive the change; sync the provenance-kernel delta
- CHANGELOG.md entry under Added
- Update bead `data-processing-2ai` (surface follow-ons delivered; remaining: current-column replay, timelines, worklist view)
