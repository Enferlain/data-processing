# Tasks

## 1. Parsing and retention

- [x] 1.1 `imports/sidecar.py`: `parse_sidecar` (prefix→category map, pool metatags, unknown prefixes) + `SidecarStore` (idempotent `folder_sidecar` import run, raw observation per seed, 64 KiB read bound)
- [x] 1.2 `imports/folder.py`: wire twin lookup after materialization; `sidecar_parsed`/`sidecar_orphan`/`sidecar_pool_tags` counters; orphans never opened

## 2. Tests and gates

- [x] 2.1 `tests/test_folder_ingest.py`: retention + category mapping + no tag-table writes; rerun idempotency (one run reused, one observation); pool metatag counting; orphan skip
- [ ] 2.2 Gates: `uv run pytest` (full), `uv run ruff check .`, `uv run ruff format` on touched files, `uv run ty check src`

## Workflow follow-up

- Archive the change; sync the local-file-discovery delta
- CHANGELOG.md entry under Added
- Close bead `data-processing-h6d`
