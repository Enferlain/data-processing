# catalog-cross-check Delta

## MODIFIED requirements

### Requirement: batch cross-check coordinates existing provider lookups

`catalog crosscheck` SHALL select an explicit corpus (`hash-material` default,
`downloaded`, `file-seeds`, `all`), cross-check each subject across the
configured supported providers using the existing candidate-lookup machinery,
and execute provider lookups sequentially against one writable connection, so
concurrent catalog writers cannot deadlock. Metadata-only bookmark subjects
SHALL be labeled as such wherever they appear.

#### Scenario: hash-material corpus over providers with resume

- **WHEN** `catalog crosscheck <catalog>` runs with request/minute budgets and
  stops at an item boundary
- **THEN** in-flight runs are finalized or checkpoint-paused, completed items are
  never re-executed by the next invocation, and pending items resume

#### Scenario: fresh complete runs are reused, not re-queried

- **WHEN** a subject × provider × strategy already has a complete lookup run with
  the same seed revision, material digest, and strategy version
- **THEN** the batch records it as skipped-reused and issues no provider request

#### Scenario: file-seeds corpus cross-checks bare-file discovery seeds

- **WHEN** `catalog crosscheck <catalog> --corpus file-seeds` runs
- **THEN** every bare-file discovery seed is a subject keyed by its canonical
  identity (the lowest seed id per verified md5/sha256 pair), its verified md5 is
  the only query material, unsupported strategies are recorded skipped with a
  no-query-material reason, and item outcomes are recorded with seed kind `file`
