## Purpose

Represent cross-platform account and post hypotheses as typed, explainable candidates whose evidence
and human decisions remain reviewable without turning similarity or links into automatic truth.

## ADDED Requirements

### Requirement: Account and post candidates remain typed and separate
The system SHALL represent account-to-account identity candidates separately from post-to-post
source or work candidates and SHALL reject candidate endpoints whose object kinds do not match the
candidate type.

#### Scenario: Profile links directly to a Pixiv account
- **WHEN** an X account profile yields a stable Pixiv account reference
- **THEN** the system can create an account candidate without creating a post candidate

#### Scenario: X post links to a Pixiv artwork
- **WHEN** an X post yields a stable Pixiv artwork reference
- **THEN** the system can create a post candidate without claiming that the publishing accounts have the same identity

#### Scenario: Record links to itself
- **WHEN** an account or post yields its own canonical platform URL
- **THEN** the link observation is retained but no self-match or self-relationship candidate is created

### Requirement: Evidence remains independent and explainable
Each candidate SHALL reference one or more immutable evidence items containing its source,
observation, evidence kind, direction, strength, extraction or comparison method and version,
timestamp, and a human-readable explanation suitable for review.

#### Scenario: One link supports two hypotheses differently
- **WHEN** one observed URL supplies account-profile evidence and post-source evidence
- **THEN** each candidate receives a separately classified evidence item with the appropriate subject and claim

#### Scenario: Weak name similarity accompanies a direct link
- **WHEN** a candidate has both a direct stable profile link and similar handles
- **THEN** the two evidence items remain independently visible rather than being collapsed into one opaque score

### Requirement: Candidate scoring is deterministic and non-authoritative
The system SHALL rank candidates using a deterministic versioned scoring policy derived from their
evidence, SHALL expose the score components, and SHALL NOT treat a score threshold as confirmation.

#### Scenario: Recompute with the same evidence and policy
- **WHEN** candidate ranking is repeated with unchanged evidence and the same policy version
- **THEN** the same score and component explanation are produced

#### Scenario: Candidate has a high score
- **WHEN** a candidate receives the highest available evidence score
- **THEN** its review state remains pending until an explicit decision is recorded

### Requirement: Account confirmation creates explicit identity membership
The system SHALL create or extend an identity grouping only after explicit confirmation of an
account candidate and SHALL retain the candidate evidence and decision that justified each
membership.

#### Scenario: Confirm two platform accounts
- **WHEN** a user confirms that an X account and a Pixiv account belong to the same identity
- **THEN** both accounts are linked to an identity with provenance back to the confirmed candidate and decision

#### Scenario: Confirm a stable account reference before enrichment
- **WHEN** a confirmed account candidate targets a recognized platform account ID that has not been fetched
- **THEN** the system creates a metadata-empty discovered account using only the platform and native ID, resolves the reference, and adds membership without fabricating a handle or name

#### Scenario: Potential transitive match
- **WHEN** two confirmed account links would imply an unreviewed third pair transitively
- **THEN** the system does not silently confirm the unreviewed pair

### Requirement: Post review records bounded relationship claims
The system SHALL support confirmed post relationships including sourced-from, same-work, repost-of,
variant-of, and derived-from families, SHALL define every directed relation from the candidate
subject toward its target, and SHALL allow an unknown or unresolved relation instead of forcing a
more specific classification.

#### Scenario: Confirm an upstream source
- **WHEN** a user confirms that a Pixiv artwork is the source of an X post
- **THEN** the system records that the X subject post is sourced from the Pixiv target post without declaring exact byte equality or account identity

#### Scenario: Similar images have uncertain transformation
- **WHEN** evidence suggests that two posts depict the same work but cannot distinguish resizing, editing, progression, or another transformation
- **THEN** the candidate can remain same-work or unresolved without inventing a transformation label

#### Scenario: Provider-observed post relation already exists
- **WHEN** discovery processes a post with an existing quote, reply, or provider-observed repost relation
- **THEN** candidate generation leaves that provider relation unchanged and stores any reviewed cross-platform hypothesis separately

### Requirement: Image evidence does not overstate equivalence
The relationship model SHALL distinguish exact-byte evidence, visual-similarity evidence, technical
variation, meaningful edit or progression, and broader derivative claims, SHALL allow multiple
transformation characteristics, and SHALL NOT interpret hashes or perceptual similarity alone as
proof of authorship or identity. In this change such characteristics SHALL be representational or
manually supplied only; discovery SHALL NOT fetch bytes, calculate hashes, or classify variations.

#### Scenario: Different resolution and encoding
- **WHEN** later verified evidence shows one image was resized and re-encoded from another
- **THEN** the relationship can carry both characteristics without treating the files as the same exact asset

#### Scenario: Progression images
- **WHEN** later evidence supports an ordered sketch-to-final relationship
- **THEN** the relationship can preserve direction and source labels without requiring every possible stage to be predefined

#### Scenario: Offline discovery encounters two media URLs
- **WHEN** discovery observes media URLs that might depict related images
- **THEN** it does not download, hash, perceptually compare, or automatically label their relationship

### Requirement: Review decisions are append-only and reversible
The system SHALL keep pending, confirmed, and rejected candidate state together with append-only
decision history, reviewer-supplied notes, timestamps, and the evidence generation reviewed.

#### Scenario: Reject a false candidate
- **WHEN** a user rejects a candidate with a note
- **THEN** the rejection remains queryable and later discovery does not recreate a new pending duplicate from the same evidence

#### Scenario: Reconsider an earlier decision
- **WHEN** a user changes a confirmed or rejected decision after new evidence appears
- **THEN** a new decision is appended and the earlier decision remains in history

### Requirement: Candidate generation and review are idempotent and queryable
The system SHALL derive stable candidate and evidence identities, preserve manual decisions across
repeat discovery, and provide human-readable and structured commands to list candidates, inspect
evidence, filter by type or state, and record decisions.

#### Scenario: Repeat candidate generation
- **WHEN** unchanged link evidence is processed again
- **THEN** existing candidates and decisions remain intact and no duplicate evidence is created

#### Scenario: List pending post candidates
- **WHEN** a user filters candidates to pending post relationships
- **THEN** account candidates and already decided post candidates are excluded from the result
