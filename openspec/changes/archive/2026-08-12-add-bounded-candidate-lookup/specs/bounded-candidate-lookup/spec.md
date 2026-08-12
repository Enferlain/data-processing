## Purpose

Lets users search supported providers for cross-platform account and post leads under explicit budgets, while preserving provenance and requiring review before any identity or relationship conclusion.

## ADDED Requirements

### Requirement: Candidate lookup is explicit, planned, and finite
The system SHALL require an existing catalog account or post seed, one or more named lookup strategies, an allowlisted provider target, and positive request, result, page, and elapsed-time limits before executing network lookup. Planning and dry-run output MUST be read-only and network-free, MUST identify unsupported strategies before execution, and MUST NOT expose rendered request URLs.

#### Scenario: Plan lookup from an X post
- **WHEN** a user plans source-URL and exact-hash lookup for an existing X post
- **THEN** the plan reports the eligible strategies, target providers, immutable limits, and exclusions without contacting a provider or modifying the catalog

#### Scenario: Provider lacks a requested capability
- **WHEN** a requested provider does not support a selected lookup strategy
- **THEN** planning excludes that strategy with a stable reason instead of substituting an unapproved query

### Requirement: Lookup strategies preserve evidence semantics
The system SHALL distinguish canonical source-post URL, embedded stable post ID, provider-declared hash, locally verified exact hash, artist-record URL, alias, handle, and display-name evidence. Exact hashes and post references MAY support post relationship candidates but MUST NOT establish account identity or authorship. Name, handle, alias, artist-tag, and uploader results MUST remain weak leads unless separate stable account evidence exists.

#### Scenario: Booru post cites the X seed
- **WHEN** a bounded source lookup returns a booru post whose retained source is the canonical X seed post
- **THEN** the system may create a directed post-source candidate with the source lookup and provider observation attached as evidence

#### Scenario: Exact hash finds a booru post
- **WHEN** a provider-declared MD5 equals the verified MD5 of an X occurrence
- **THEN** the system may create an exact-byte post candidate but does not infer that the booru uploader, artist tag, and X author are the same identity

#### Scenario: Artist name resembles an X name
- **WHEN** an artist-name or alias query returns a similarly named booru artist record without a stable account reference
- **THEN** the result remains a weak lookup lead and does not create or confirm an account identity candidate

### Requirement: Lookup runs are durable and resumable
The system SHALL persist immutable run limits, sanitized request attempts, retained raw observations, typed outcomes, committed result associations, and a continuation only after each page commits. A paused, interrupted, rate-limited, or retryable run SHALL resume without duplicating committed results or skipping an uncommitted page.

#### Scenario: Result budget stops a page sequence
- **WHEN** the next committed result would exceed the run's result limit
- **THEN** the run pauses at a durable boundary and preserves a continuation that can resume under a new explicitly authorized run

#### Scenario: Provider rate limit interrupts lookup
- **WHEN** a provider returns a rate-limit response with an allowlisted retry time
- **THEN** the run records a typed paused outcome and does not busy-wait or advance its committed continuation

#### Scenario: Repeat an unchanged lookup
- **WHEN** the same provider results are observed again
- **THEN** raw observations and run provenance remain auditable while candidate and evidence identities are not duplicated

### Requirement: Existing review decisions remain authoritative
Lookup SHALL feed compatible results into the existing typed account/post candidate and evidence ledger. It MUST preserve prior pending, confirmed, and rejected decisions, MUST NOT auto-confirm a candidate regardless of score or evidence count, and MUST NOT recreate a rejected candidate under a new identity from unchanged evidence.

#### Scenario: Lookup strengthens a rejected candidate
- **WHEN** a later run adds new evidence to a previously rejected post candidate
- **THEN** the evidence generation advances while the rejection and its decision history remain intact for explicit reconsideration

#### Scenario: Lookup finds an artist profile URL
- **WHEN** a booru artist record contains a stable Pixiv account URL
- **THEN** that URL may produce a typed account reference and review candidate, while the artist record itself remains attribution evidence rather than an account

### Requirement: Lookup does not become expansion or acquisition
The system SHALL NOT recursively follow result links, enumerate a discovered account's posts, download media, calculate similarity, select a preferred occurrence, or label newly found posts liked or bookmarked. A confirmed stable account or post target MAY be handed explicitly to existing metadata synchronization in a separate operation.

#### Scenario: Result exposes another external link
- **WHEN** a returned record contains an additional supported platform URL
- **THEN** the system retains it as evidence but does not traverse it during the lookup run

#### Scenario: User confirms a Pixiv account candidate
- **WHEN** review confirms a stable Pixiv account target found by lookup
- **THEN** the user can explicitly start the existing bounded Pixiv metadata sync without the lookup run automatically enumerating or downloading anything

### Requirement: Lookup inspection is bounded and redacted
The CLI SHALL provide plan, execute, resume, run-list, and run-show operations with stable human and JSON output. Normal output and errors MUST omit credentials, headers, cookies, raw payloads, private paths, signed query values, and rendered request URLs while retaining provider, strategy, seed, counts, limits, typed outcomes, evidence identifiers, and review references.

#### Scenario: Inspect a failed authenticated lookup
- **WHEN** a lookup fails because credentials are absent or rejected
- **THEN** inspection reports the provider, strategy, typed authentication outcome, and bounded diagnostic without exposing credential values or private configuration paths
