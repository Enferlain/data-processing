# catalog-cross-check Specification

## Purpose

Batch cross-checking of a selected catalog corpus across the configured live
providers, coordinated over the existing candidate-lookup machinery with
durable, resumable, item-level outcomes. Matches stay candidates; the catalog
remains the sole source of facts.

## Requirements

### Requirement: batch cross-check coordinates existing provider lookups

`catalog crosscheck` SHALL select an explicit corpus (`hash-material` default,
`downloaded`, `all`), cross-check each subject across the configured supported
providers using the existing candidate-lookup machinery, and execute provider
lookups sequentially against one writable connection, so concurrent catalog
writers cannot deadlock. Metadata-only bookmark subjects SHALL be labeled as such
wherever they appear.

#### Scenario: hash-material corpus over providers with resume

- **WHEN** `catalog crosscheck <catalog>` runs with request/minute budgets and
  stops at an item boundary
- **THEN** in-flight runs are finalized or checkpoint-paused, completed items are
  never re-executed by the next invocation, and pending items resume

#### Scenario: fresh complete runs are reused, not re-queried

- **WHEN** a subject × provider × strategy already has a complete lookup run with
  the same seed revision, material digest, and strategy version
- **THEN** the batch records it as skipped-reused and issues no provider request

### Requirement: budgets are checkpoint controls with graceful stop

Budgets SHALL stop the batch at item boundaries — never mid-item — preserving run
state, pages, and checkpoints. Stopping SHALL leave the batch resumable and SHALL
report which items are pending.

#### Scenario: budget exhaustion finalizes cleanly

- **WHEN** `--max-requests` or `--max-minutes` is reached
- **THEN** the current item finishes or pauses with a checkpoint, the summary
  reports completed/pending counts, and a later invocation continues from pending

### Requirement: item-level reporting with reasons; matches stay candidates

The batch SHALL record per subject × provider × strategy state
(checked / matched / skipped / failed / pending) with a reason for non-checked
states — including missing credentials and rate limits with their `retry_after` —
and SHALL report aggregate counts. Matched candidates SHALL preserve existing
lookup provenance and SHALL NOT become confirmed relationships.

#### Scenario: rate-limited provider is visible and resumable

- **WHEN** a provider answers 429 with `retry_after` and the budget stops the
  batch first
- **THEN** the item is reported as failed-rate-limited with the delay, and a later
  invocation retries it

#### Scenario: matches are recorded as candidates only

- **WHEN** a provider lookup returns matching candidates
- **THEN** run provenance and candidate records are exactly the existing
  candidate-lookup artifacts; no relationship or pair decision is created
