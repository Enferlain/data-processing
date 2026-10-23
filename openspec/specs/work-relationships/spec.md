# work-relationships Specification

## Purpose
Work entities and the uniform typed-relationship model carrying epistemic status: the kernel
Phase D schema half that joins separately observed versions of a work (same bytes, re-encodes,
crops, censored variants, edits, reposts) through evidence-backed, review-gated relationships
instead of silent identity assumptions.

## Requirements

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
provider-declared occurrence variant roles (sample or preview toward original),
`reposted_from` relationships from provider-declared post source-URL references resolving to
another catalog post, and `parent_of` relationships from retained provider-declared post
parent relations. Seeding SHALL be offline, read the retained evidence only, report what it
materialized and skipped with counts, and never silently treat an inferred-quality signal as
a deterministic one.

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

#### Scenario: A declared parent relation links two posts
- **WHEN** a retained provider-declared post relation records one post as the parent of
  another
- **THEN** seeding materializes a directional `parent_of` relationship from the parent post
  toward the child post with `observed` status, citing the provider declaration as evidence

#### Scenario: Seeding never contacts a provider
- **WHEN** the seeding operation runs
- **THEN** no network access occurs and the retained evidence layer is read, not modified

### Requirement: Confirmed candidates materialize into relationships on operator command
The system SHALL provide an explicit materialization operation that converts confirmed post
match candidates into relationship rows. Materialization SHALL accept only candidates whose
current review state is confirmed, SHALL map the candidate's relation kind onto the
relationship vocabulary with a stated fixed mapping (`sourced_from` and `repost_of` to
`reposted_from` between the posts; `same_work`, `variant_of`, and `derived_from` between the
posts' work anchors), SHALL attach the candidate's entire evidence bundle through the
relationship-evidence join, and SHALL record a review decision naming the candidate as the
materialization source. Materialization SHALL be idempotent, SHALL NOT modify the candidate
or its ledger, and SHALL NOT require or perform any network access. Nothing except this
operator command SHALL create relationships from candidates — matchers, lookups, and
unconfirmed candidates never materialize.

#### Scenario: A confirmed candidate becomes one reviewed relationship
- **WHEN** an operator materializes a confirmed post candidate whose target is a catalog
  post
- **THEN** exactly one relationship exists with `reviewed` epistemic status and confirmed
  review state, the candidate's evidence rows are attached to it, a review decision names
  the candidate as the source, and the candidate's own state and ledger are unchanged

#### Scenario: Re-materialization attaches nothing new
- **WHEN** the same confirmed candidate is materialized again
- **THEN** no duplicate relationship, decision, or evidence link is created

#### Scenario: Unmaterializable candidates are refused with reasons
- **WHEN** materialization encounters a candidate that is pending or rejected, has relation
  kind `unresolved`, has a target reference that resolves to no catalog post, or (for a
  work-level kind) has a post without a materialized work anchor
- **THEN** that candidate is reported with a typed refusal reason, no relationship is
  created for it, and other candidates still materialize

### Requirement: Dependence classification and read-time lineage derivation
The relationship vocabulary SHALL classify kinds by their role in evidence dependence:
descent kinds (`reposted_from`, `derived_from`, `variant_of`, `reencoded_from`,
`resized_from`, `cropped_from`, `censored_variant_of`, `edited_from`, `transcoded_from`,
`extracted_from`, `thumbnail_of`) express that one side's claims or bytes likely descend from
the other; equivalence kinds (`same_bytes`, `same_work`) prove common origin without
direction; structural kinds (`page_of`, `parent_of`) anchor objects without expressing claim
descent and SHALL NOT merge lineages. The system SHALL provide a lineage-derivation surface
that computes connected components over a stated dependence edge set — descent and
equivalence kinds by default, restricted to conclusion-grade epistemic statuses (observed,
verified, derived, reviewed) and excluding rejected relationships — joined through the
structural anchoring of posts, their media occurrences, and their work anchors. Derivation
SHALL be read-only, deterministic, and offline, and SHALL NOT stamp lineage, group, or
correlation identifiers onto any retained row.

#### Scenario: The mirror chain resolves to one lineage
- **WHEN** lineage derivation runs over a repost chain where danbooru reposts pixiv, gelbooru reposts danbooru, and an archive reposts gelbooru
- **THEN** the four posts, their occurrences, and their work anchors resolve to one lineage group while four observations remain retained

#### Scenario: Same-bytes equivalence merges without a declared source
- **WHEN** occurrences of posts on different providers resolve to the same verified bytes and no provider declares a source
- **THEN** the posts resolve to one lineage group through the equivalence edges and structural anchoring

#### Scenario: A pending inferred proposal does not merge
- **WHEN** a dependence relationship exists with epistemic status `inferred` awaiting review
- **THEN** the default derivation keeps the two sides in separate lineages, and after review confirms it the two sides merge

#### Scenario: A rejected dependence separates the sides again
- **WHEN** review rejects a dependence relationship that the default policy had counted
- **THEN** subsequent derivation keeps the two sides in separate lineages while the rejected relationship and its evidence remain retained

#### Scenario: Structural kinds anchor but never merge claims
- **WHEN** two posts are linked only by a structural relationship such as `parent_of`
- **THEN** their claims resolve to separate lineages

#### Scenario: Derivation reads and never writes
- **WHEN** lineage derivation runs
- **THEN** no retained row is created, modified, or deleted, and re-running the derivation returns identical groups
