## MODIFIED Requirements

### Requirement: Storage-enforced audit immutability
Audit-history rows SHALL be immutable or append-only as enforced by the storage layer. Source
reports and their payload content, tag, tag-alias, post-tag, flag, pool, and post metadata
observations, provenance-event revisions, review decisions, and acquisition verification records
SHALL be immutable and undeletable. Plans, probes, execution lineage, and
expansion post associations, terminal candidate-lookup requests, and terminal acquisition
attempts SHALL reject updates and SHALL never be deleted. Provenance events, adoption attempts, candidates, evidence rows, and
candidate-evidence links SHALL never be deleted, but MAY update their current fields — a
provenance event's current projection, an attempt's re-recorded outcome, a candidate's review
state and score, an evidence row's rematerialized digest. Remote requests SHALL be undeletable,
and immutable after insert except for attaching — never swapping or detaching — their retained
source report. The declared inputs of a begun run SHALL be immutable while its state, counters,
outcome, retry guidance, diagnostic, and finish time advance freely. Audit-history tables
introduced after this specification SHALL enforce immutability at the storage layer from their
first migration.

#### Scenario: Attempt to mutate an immutable audit row
- **WHEN** a statement attempts to update or delete an immutable audit row — a source report or
  its payload content, an observation row, a provenance-event revision, a review decision, or an
  acquisition verification record
- **THEN** the storage layer rejects the statement

#### Scenario: Attempt to delete update-rejected audit history
- **WHEN** a statement attempts to delete an expansion plan, a probe, an execution lineage row,
  an expansion post association, a candidate-lookup request, or a media-acquisition attempt
- **THEN** the storage layer rejects the statement

#### Scenario: Attempt to delete review or evidence history
- **WHEN** a statement attempts to delete a provenance event, an adoption attempt, a reviewed
  candidate, an evidence row, or a candidate-evidence link
- **THEN** the storage layer rejects the statement

#### Scenario: Legitimate current-field updates remain possible
- **WHEN** a statement refreshes a provenance event's current projection on re-import, re-records
  an adoption attempt, updates a candidate's review state or score, or updates an evidence row's
  rematerialized digest
- **THEN** the storage layer accepts the statement

#### Scenario: Legitimate run and request advances remain possible
- **WHEN** a statement advances a begun run's status, counters, outcome, retry guidance,
  diagnostic, or finish time, or attaches a retained source report to its remote request
- **THEN** the storage layer accepts the statement

#### Scenario: A new audit table lands
- **WHEN** a future migration introduces a new audit-history table
- **THEN** it ships with storage-level immutability or append-only enforcement
