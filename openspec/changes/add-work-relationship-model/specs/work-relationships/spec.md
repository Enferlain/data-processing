## Purpose

Work entities and the uniform typed-relationship model carrying epistemic status: the kernel
Phase D schema half that joins separately observed versions of a work (same bytes, re-encodes,
crops, censored variants, edits, reposts) through evidence-backed, review-gated relationships
instead of silent identity assumptions.

## ADDED Requirements

### Requirement: Work entities are minimal deterministic anchors
The system SHALL materialize one work entity per post that has media occurrences, linked to
that post's representations. A work SHALL carry no media vocabulary (no dimensions, codec, or
format facts — those stay in the media family layer), and work materialization SHALL NOT
require grouping decisions. Human-level same-work identity across platforms SHALL emerge from
reviewed `same_work` relationships and projections, never from merging or rewriting work rows.

#### Scenario: A post's occurrences anchor one work
- **WHEN** a post with media occurrences is materialized into works
- **THEN** exactly one work exists for it, all of its occurrences are linked as
  representations, and the work itself stores no image-specific facts

### Requirement: Relationships are typed, epistemic, and canonically oriented
Relationships SHALL be stored in one uniform table with polymorphic endpoints (work, media
occurrence, post, asset), a closed kind vocabulary, and an epistemic status from the kernel
vocabulary (`observed`, `verified`, `derived`, `inferred`, `reviewed`). Each kind SHALL declare
whether it is symmetric or directional; symmetric kinds SHALL be stored in a canonical
endpoint order and directional kinds SHALL store the derivative, child, page, or thumbnail on
one fixed side. Every relationship SHALL have a deterministic key over its canonical identity
so re-materialization is idempotent. No similarity metric, matching name, or provider
declaration alone SHALL establish identity, authorship, or same-work as a conclusion.

#### Scenario: Hash equality proves bytes only
- **WHEN** two representations resolve to the same verified bytes
- **THEN** a `same_bytes` relationship may exist as `verified` while identity, authorship, and
  `same_work` conclusions remain unestablished

#### Scenario: Re-seeding does not duplicate
- **WHEN** the deterministic seeder runs twice over unchanged evidence
- **THEN** each relationship exists once with its evidence attached once

### Requirement: Relationship evidence uses the shared evidence ledger
Evidence for relationships SHALL be recorded in the existing evidence ledger (stance,
direction, strength, detector identity and version, explanation) and attached through a
relationship-evidence join. Deterministic relationships SHALL bypass human review while still
carrying evidence. Evidence SHALL survive the review decision it fed, and contradicting
evidence SHALL NOT delete or overwrite supporting evidence.

#### Scenario: A deterministic relationship still cites evidence
- **WHEN** the seeder materializes a `same_bytes` relationship
- **THEN** the relationship carries at least one supporting evidence row naming its detector
  and version

#### Scenario: Contradicting evidence arrives
- **WHEN** later evidence contradicts an existing relationship
- **THEN** both evidence rows remain queryable and any state change happens through recorded
  transitions or review, not deletion

### Requirement: Relationship review is append-only and reversible
Human review over relationships SHALL be an append-only ledger recording prior state, decision,
and note; reversing a decision SHALL create a new decision row rather than editing history, and
the reviewed relationship and its evidence SHALL never be deleted. A rejected relationship
SHALL be retained with its history rather than removed.

#### Scenario: Confirm then reverse
- **WHEN** a reviewer confirms a relationship and a later review reverses it
- **THEN** both decisions remain in the ledger, the relationship reflects the latest decision,
  and the relationship row plus its evidence are still queryable

### Requirement: Epistemic-status transitions are append-only history
When a relationship's epistemic status changes (for example `observed` becoming `reviewed`),
the prior status and the cause SHALL be retained in an append-only transition history. A
relationship row's identity, endpoints, and kind SHALL be immutable after insert.

#### Scenario: An observed relationship is later reviewed
- **WHEN** a human accepts a relationship previously materialized as `observed`
- **THEN** the status becomes `reviewed`, the transition history records the prior `observed`
  status, and no new relationship row is created

### Requirement: Relationship storage is immutable at the storage layer
From its first migration, the relationship model SHALL enforce kernel immutability tiers at
the storage layer: works and work-representation links reject update and deletion;
relationship rows may only ever update their epistemic-status and review-state fields and are
never deletable; evidence links, review decisions, and status transitions reject update and
deletion entirely.

#### Scenario: Storage rejects out-of-contract writes
- **WHEN** a statement attempts to delete a relationship, rewrite its endpoints, or update a
  review decision row
- **THEN** the database rejects the statement at the storage layer

### Requirement: Deterministic seeding is offline and bounded
The system SHALL provide an explicit seeding operation that materializes `same_bytes`
relationships from verified content deduplication, `thumbnail_of` relationships from
provider-declared occurrence variant roles (sample or preview toward original), and
`reposted_from` relationships from provider-declared post source-URL references resolving to
another catalog post. Seeding SHALL be offline, read the retained evidence only, report what
it materialized and skipped with counts, and never silently treat an inferred-quality signal
as a deterministic one.

#### Scenario: Identical bytes link two representations
- **WHEN** two occurrences of different posts resolve to the same verified asset bytes
- **THEN** seeding materializes one symmetric `same_bytes` relationship between those
  occurrences with `verified` status

#### Scenario: A declared sample points at its original
- **WHEN** a post's occurrence carries a provider-declared sample or preview variant role
  alongside an original
- **THEN** seeding materializes a directional `thumbnail_of` relationship from the sample or
  preview occurrence toward the original occurrence with `observed` status

#### Scenario: A declared source URL resolves to a catalog post
- **WHEN** a post's provider-declared source-URL reference resolves to another catalog post's
  identity
- **THEN** seeding materializes a directional `reposted_from` relationship from the citing
  post toward the cited post with `observed` status

#### Scenario: Seeding never contacts a provider
- **WHEN** the seeding operation runs
- **THEN** no network access occurs and the retained evidence layer is read, not modified
