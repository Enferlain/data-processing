# Tasks

- [x] 1. Migration `0036_operator_labels.sql`: `operator_labels` +
  `operator_label_assertions` + latest-state index; backup-test schema pins
  35→36.
  Verify: `uv run pytest tests/test_operator_labels.py tests/test_catalog_backup.py`.
- [x] 2. Service module `operator_labels.py`: create/retire, apply/revoke
  (append-only, latest-wins), current labels per subject, label search with
  identical-content expansion (hash-pair seeds, md5-linked posts), bounded
  reporting.
  Verify: `uv run pytest tests/test_operator_labels.py`.
- [x] 3. CLI family `catalog tag {create,list,remove,apply,revoke,show,search}`
  with JSON output; registered in FAMILIES; help text distinguishes operator
  labels from provider tags and from `catalog label` (pair server).
  Verify: `uv run catalog tag --help` + a smoke pass on a temp catalog.
- [x] 4. Gates and docs: full pytest, ruff check + format on changed files,
  `ty check src`, CHANGELOG entry, media-catalog docs section.
