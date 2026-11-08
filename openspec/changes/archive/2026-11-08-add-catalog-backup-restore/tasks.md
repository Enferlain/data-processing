# Tasks

## 1. Core

- [x] 1.1 `src/media_catalog/backup.py`: `backup_catalog` (VACUUM INTO +
  manifest with schema version, row counts, managed-root registry, sha256),
  default sibling destination, timestamped naming, `--keep` retention.
  Verify: unit roundtrip test.
- [x] 1.2 `restore_catalog`: manifest digest check, schema/integrity
  pre-check, `--force` overwrite guard, atomic copy, `--verify`
  integrity/foreign-key checks, `--media-root` verifier runs. Verify: unit
  tests incl. tamper refusal and overwrite refusal.
- [x] 1.3 `backup_doctor_section`: conventional-directory probe — none
  (neutral), latest timestamp/version, digest re-check (drift fails).
  Verify: unit tests for all three states.

## 2. CLI + docs

- [x] 2.1 `catalog backup` / `catalog restore` commands in
  `cli_commands/admin.py`; doctor gains the backup section. Verify: CLI
  tests incl. backup under an open WAL writer.
- [x] 2.2 Docs (`docs/tools/media-catalog.md`) + CHANGELOG. Verify: review.

## 3. Gates

- [x] 3.1 Full `uv run pytest`, `ruff check .`, `ruff format` (changed),
  `ty check src`, `openspec validate`. Verify: all green.
