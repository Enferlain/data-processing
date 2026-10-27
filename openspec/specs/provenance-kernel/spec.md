## Purpose

Formalize the domain-neutral provenance core — source identity, observation retention, provenance
events, verified blobs, typed relationships with epistemic status, evidence and review ledgers,
the bounded run contract, audit immutability, and projections — that every data family and
capability in the catalog builds on, so these cross-cutting invariants are named, testable, and
cannot silently erode as new sources and data families are added.

Where a capability spec restates a kernel invariant at domain altitude, the kernel requirement is
authoritative for the cross-cutting invariant. Where a surface's enforcement strength is
deliberately weaker than full immutability — rows that may update current fields but are never
deletable, or whose only permitted post-insert change is stated — the requirement names the
exception rather than relying on writer convention.

## Requirements

### Requirement: Source-namespaced object identity
The catalog SHALL register each remote provider or instance as a source with a stable key, and
SHALL identify every source-derived object by its source and provider-native identifier so that
identical native identifiers from different sources never collide. Identifier kinds SHALL
distinguish stable identifiers from temporal ones such as handles, slugs, hashes, and opaque
tokens; only stable identifiers MAY anchor reconciled identity.

#### Scenario: Same native identifier on two sources
- **WHEN** two different sources each report an object with native identifier `123`
- **THEN** the catalog retains them as separate objects

#### Scenario: Temporal identifier changes
- **WHEN** a source changes an object's handle or display name
- **THEN** the catalog records the change as temporal metadata without altering the stable
  identity of the object

### Requirement: Append-only source-report retention
The catalog SHALL retain, for every observation it normalizes, the raw source report as payload
content addressed by digest and anchored to the run and request that captured it. Source reports
SHALL be append-only and deduplicated by content; a later report about the same object SHALL be
stored as a new observation rather than revising an earlier one in place.

#### Scenario: Provider changes a mutable field
- **WHEN** a later source report for the same object contradicts an earlier report
- **THEN** both reports remain retained and independently addressable

#### Scenario: Identical payload captured twice
- **WHEN** two independent requests return byte-identical payloads
- **THEN** the payload content is stored once while each request keeps its own observation

### Requirement: Provenance events explain presence
The catalog SHALL record why each record is present — for example imported, discovered, or
crawled, or engagement such as liked or bookmarked — as append-only provenance events with the
source and time of the event, rather than mutable flags, and SHALL retain re-observations of a
provenance event as revisions. A record that arrived through discovery or crawling SHALL NOT
acquire engagement provenance it did not have.

#### Scenario: One record, two presence reasons
- **WHEN** the same record reaches the catalog through two sources that each justify its presence
  (for example a like and a bookmark on the same post)
- **THEN** the record carries two distinct provenance events, one per source

#### Scenario: Discovery does not confer engagement
- **WHEN** a previously unseen record is added as discovered data
- **THEN** it does not acquire a liked or bookmarked provenance event

#### Scenario: Re-observation is retained as a revision
- **WHEN** the same presence reason is observed again with updated detail
- **THEN** the original provenance event is preserved and the re-observation is retained as a
  revision instead of overwriting it

### Requirement: Content-addressed verified blobs
The catalog SHALL store acquired bytes as blobs content-addressed by a locally verified strong
hash, SHALL deduplicate identical bytes into one blob while retaining every acquisition against
it, and SHALL keep provider-declared facts distinct from locally verified facts.

#### Scenario: Identical bytes acquired twice
- **WHEN** two acquisitions produce byte-identical content
- **THEN** one blob is retained and both acquisitions link to it

#### Scenario: Declared and verified hashes coexist
- **WHEN** a blob has both a provider-declared hash and a locally computed hash
- **THEN** the catalog stores them as distinct facts that can disagree without conflict

### Requirement: Declared-versus-verified comparisons are retained
Where the catalog records a comparison of a provider-declared value against a locally verified
value, it SHALL retain the claim kind, the declared value, the verified value, and the comparison
result — matched, mismatched, or not comparable — as durable records.

#### Scenario: Declared hash mismatches verified bytes
- **WHEN** acquired bytes fail a provider-declared hash claim
- **THEN** the comparison is recorded as mismatched and the bytes are quarantined or flagged
  rather than silently accepted

#### Scenario: Values are not comparable
- **WHEN** a declared value cannot be meaningfully compared with the verified value
- **THEN** the comparison is recorded as not comparable rather than omitted

### Requirement: Typed relationships carry epistemic status
Relationships between catalog objects — identity, authorship, derivation, variant-of, same-work,
and similar — SHALL be typed and provenance-bearing, and SHALL carry an epistemic status. The
kernel vocabulary for epistemic status is: observed (a source reports it), verified (a local
deterministic check proves it), derived (a deterministic algorithm establishes it), inferred (a
matcher proposes it), and reviewed (a human accepted or rejected it). Today's candidate proposal
and review states are the initial partial expression of this vocabulary; relationship-bearing
records introduced after this specification adopt the vocabulary explicitly. No similarity
metric, matching name, or provider-declared attribution alone SHALL establish identity,
authorship, or same-work as a conclusion.

#### Scenario: Matcher proposes a relationship
- **WHEN** a matcher proposes that two objects may relate
- **THEN** the proposal is recorded as inferred and pending review, not as a conclusion

#### Scenario: Hash equality proves bytes only
- **WHEN** two blobs have identical verified hashes
- **THEN** a same-bytes relationship may be recorded as verified while identity, authorship, and
  same-work conclusions remain unestablished

### Requirement: Evidence ledger with stance and provenance
Evidence supporting or contradicting a proposed relationship or assertion SHALL be retained with
its stance — supports, contradicts, or neutral — plus direction, strength, detector identity and
version, and a human-readable explanation. Evidence SHALL survive the review decision it fed.

#### Scenario: Contradicting evidence arrives
- **WHEN** a later observation contradicts the evidence supporting a candidate
- **THEN** both evidence rows remain queryable and the candidate's state changes through review,
  not deletion

#### Scenario: Evidence cites its detector
- **WHEN** evidence is recorded
- **THEN** the detector identity and version that produced it are retained with the evidence

### Requirement: Append-only reversible review
Human review decisions SHALL be append-only, SHALL record the prior state, and SHALL never delete
the reviewed candidate or its evidence. Reversing a decision creates a new decision rather than
editing history.

#### Scenario: Confirm then reverse
- **WHEN** a reviewer confirms a candidate and a later reviewer reverses it
- **THEN** both decisions remain in the ledger with their prior states and the candidate reflects
  the latest decision

### Requirement: Bounded run contract
Every run that performs network interaction SHALL declare explicit budgets before starting —
request, page, record, and time budgets for metadata enumeration, or item, byte, and time
budgets for acquisition; SHALL terminate with a typed outcome from the shared closed vocabulary
covering at least success, unavailability, deletion, authentication and authorization failures,
rate limiting, transient provider errors, malformed responses, budget exhaustion, and local
persistence failure, with family-specific extensions and omissions recorded per family; SHALL
record which budget boundary stopped it when applicable; SHALL persist retry guidance when
rate-limited; and SHALL support resumable execution — checkpoints that carry the continuation
adapter and version, or an equivalent durable resume state such as staged partials — so an
interrupted run resumes without duplicating or skipping committed work. Run inputs SHALL be
immutable once the run begins; the storage layer rejects input mutation.

#### Scenario: Budget exhaustion
- **WHEN** a run reaches a declared budget before completing
- **THEN** it terminates with the budget-exhausted outcome and records the boundary that stopped
  it

#### Scenario: Resume after interruption
- **WHEN** a run is interrupted after committing units of work and is later resumed
- **THEN** execution continues from the committed checkpoint or durable resume state without
  duplicating or skipping committed work

#### Scenario: Rate-limited termination
- **WHEN** a provider terminates a run with a rate-limit outcome
- **THEN** the run records the outcome with retry guidance rather than busy-waiting

#### Scenario: Run inputs are immutable
- **WHEN** a statement attempts to change the declared inputs of a begun run
- **THEN** the storage layer rejects the statement

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

### Requirement: Projections preserve retained history
Any current view that resolves competing or mutable facts SHALL follow a stated policy — for
example, the newer observation wins a mutable field — and SHALL NOT erase retained observations.
Omission by a later source report SHALL NOT delete facts supplied by an earlier report, and
derived views and exports SHALL be rebuildable from retained observations.

#### Scenario: Newer observation wins but history remains
- **WHEN** two source reports disagree on a mutable field and the current view selects the newer
- **THEN** both reports remain retained and the selection policy is stated

#### Scenario: Field omitted by a later report
- **WHEN** a later source report omits a field an earlier report supplied
- **THEN** the earlier value remains in retained history

### Requirement: New capabilities preserve kernel invariants
Capabilities and data families added after this specification SHALL reuse the kernel contracts —
source identity, observation retention, provenance events, the bounded run contract, evidence and
review ledgers, audit immutability, and projections — rather than introducing parallel mechanisms,
and SHALL NOT bypass provenance retention, bounded interaction, or review.

#### Scenario: A new data family is added
- **WHEN** a future change introduces a non-media data family
- **THEN** its records carry source identity, retained observations, bounded runs, and evidence
  in accordance with this specification

### Requirement: Temporal as-of reconstruction from retained history
The system SHALL be able to reconstruct what was known as of a cutoff time from retained
history alone, without rewriting or special-casing historical rows. Timestamps SHALL keep
their distinct meanings: source observation time (when a source report was observed),
provider-claimed time (what the provider asserts about the content), acquisition time (when
bytes entered local custody), interpretation time (when a normalizer produced facts,
including reprocessing), and review time (when a human decided). Reconstructed current
values SHALL resolve under the stated projection policy restricted to facts observed at or
before the cutoff; review state SHALL be the latest decision at or before the cutoff.
Deleted, unavailable, moved, or later-corrected objects SHALL appear in reconstructions
through their retained observations, never by absence.

#### Scenario: A field's value as of a cutoff
- **WHEN** a field was observed with value A in January and value B in March, and the
  system reconstructs as of a February cutoff
- **THEN** the reconstructed current value is A, both observations remain retained, and no
  historical row is modified

#### Scenario: Review state as of a cutoff
- **WHEN** a candidate or relationship was confirmed in January and reversed in March
- **THEN** reconstructing as of February yields the confirmed state from the January
  decision, and both decisions remain retained

#### Scenario: Projections state their evidence cutoff
- **WHEN** a projection or export is generated
- **THEN** it records the cutoff its selection resolved under, so the build can later be
  explained or replayed against retained history

### Requirement: Corroboration counts lineages, not observations
Where a surface counts sources agreeing on a claim, it SHALL distinguish observation count
from independent-corroboration count. Dependence between sources SHALL be expressed as typed
relationships from the descent and equivalence vocabularies carrying epistemic status — never
as lineage stamps on evidence rows, observation rows, or objects; evidence rows SHALL remain
single-finding facts whose grouping, if any, is detector payload. Independent corroboration
SHALL be derived at read time as lineage groups over a stated dependence policy naming the
relation kinds and epistemic statuses that count as dependence. A surface counting agreement
SHALL NOT treat N observations as N independent corroborations by default; treating
observations as independent SHALL be an explicit, stated choice of that surface. Global
provider-reliability scores SHALL NOT substitute for claim-specific dependence.

#### Scenario: Mirror chain collapses to one lineage
- **WHEN** four sources repeat a claim along a known repost/import chain (pixiv → danbooru → gelbooru → archive), each retained as its own observation and each repost recorded as a descent relationship
- **THEN** four observations remain retained while the four sources resolve to one lineage group, and a corroboration surface reports one independent lineage

#### Scenario: Byte-identical content across providers
- **WHEN** five providers serve byte-identical files linked by verified same-bytes relationships
- **THEN** five occurrences remain retained while resolving to one lineage group for origin and authorship claims

#### Scenario: Independent agreement stays independent
- **WHEN** two sources with no known dependence relationship assert the same claim
- **THEN** the claim carries two lineages and a corroboration surface reports two independent corroborations

#### Scenario: Dependence carries its own uncertainty
- **WHEN** a dependence relationship is only inferred (a pending proposal) or has been rejected by review
- **THEN** the default dependence policy does not merge the two sides, and the dependence's own epistemic status and review state remain retained with the relationship

### Requirement: Source-report observation identity is anchor-scoped or source-scoped content addressing
Each raw observation SHALL have exactly one identity: rows anchored to an import run are keyed by
their anchor, object kind, native identifier, and payload; rows anchored to a remote request are
keyed by that request; anchorless rows SHALL be content-addressed **per source** — platform,
object kind, native identifier when present, and payload bytes — enforced by the storage layer.
Anchorless retention SHALL require a declared source platform. Byte-identical anchorless payloads
from the same source SHALL resolve to one observation shareable by any number of requesting rows
(each keeping its own outcome and timestamps); byte-identical payloads from different sources
SHALL remain distinct observations with their own source attribution.

#### Scenario: A retry shares the observation
- **WHEN** the same source is asked again and returns byte-identical bytes for the same object
- **THEN** the requesting row references the existing content-addressed observation and no new
  observation row is created

#### Scenario: Different sources never fold
- **WHEN** two different sources return byte-identical bodies for the same object identity
- **THEN** two observations are retained, each carrying its own source attribution

#### Scenario: Anchored rows keep their anchor identity
- **WHEN** an observation is anchored to an import run or a remote request
- **THEN** the anchor key governs its identity and the anchorless indexes do not apply

#### Scenario: Anchorless retention names its source
- **WHEN** a source report is retained without a run or request anchor
- **THEN** the retention declares the reporting platform, and the observation's identity includes
  it
