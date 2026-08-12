## ADDED Requirements

### Requirement: Provider lookup evidence remains non-authoritative
The match-review system SHALL accept versioned evidence produced by bounded provider lookup while retaining the evidence's query strategy, seed direction, provider observation, and strength classification. Lookup evidence MUST NOT bypass typed candidate rules, stable-ID requirements for account targets, append-only decisions, or explicit confirmation.

#### Scenario: Source and hash evidence support one post candidate
- **WHEN** separate bounded lookups connect the same X and booru posts by canonical source URL and exact verified MD5
- **THEN** both evidence records support one stable post candidate and remain independently explainable

#### Scenario: Lookup result repeats after confirmation
- **WHEN** a later lookup observes evidence already attached to a confirmed candidate
- **THEN** the confirmation remains unchanged and no duplicate candidate, evidence, or decision is created

#### Scenario: Weak artist result has no stable account target
- **WHEN** lookup returns only a booru artist tag, alias, uploader, or similar display name
- **THEN** match review does not materialize an account or identity candidate from that result
