# Tasks

## 1. Timeline and accounts-as-of

- [x] 1.1 `temporal.py`: `timeline(connection, *, post_id=None, account_id=None, limit)` with the uniform event shape, run provenance joins, parsed-time ordering; `review_state_snapshot` gains the `accounts` section (known at T, snapshots retained ≤ T)
- [x] 1.2 `catalog timeline` CLI: `--post`/`--account` mutually exclusive required, `--limit` (default 200), `--json`

## 2. Tests and gates

- [x] 2.1 `tests/test_temporal_asof.py`: post timeline ordering across observation/label/candidate events; account timeline snapshots; unknown subject rejection; accounts-at-cutoff counts; CLI round-trip
- [x] 3.1 Gates: `uv run pytest` (full), `uv run ruff check .`, `uv run ruff format` on touched files, `uv run ty check src`

## Workflow follow-up

- Archive the change; sync the provenance-kernel delta
- CHANGELOG.md entry under Added
- Close bead `data-processing-2ai` (all consumer-ready follow-ons delivered; attribution-worklist as-of parked with reason)
