## ADDED Requirements

### Requirement: Non-recorded items enter through an explicit materialize-a-seed operation
The system SHALL provide an explicit operator materialize-a-seed operation that turns the
evidence bundle present at the time — one or more URLs where the item was found, an optional
note, and optional declared values — into a provenance-recorded stub post. The bundle SHALL be
retained as raw import evidence under an `operator_seed` import run; the stub SHALL carry
availability `unknown`, every supplied URL as a `source_url` reference and as a typed
`provider_id` reference, and no snapshot or media claims. URL inputs MUST resolve to stable
post identities and be pairwise consistent per platform, and violations MUST fail closed
before any write. Materialization MUST be idempotent, MUST NOT create candidates,
relationships, review decisions, or identity conclusions, and the resulting stub SHALL be a
valid lookup seed exactly like a recorded post.

#### Scenario: Seed a non-recorded pixiv item
- **WHEN** the operator materializes a seed from a pixiv artwork URL
- **THEN** the stub post exists with availability `unknown`, the retained bundle as its raw
  observation, and a typed pixiv reference that `external_post_id` planning accepts

#### Scenario: Conflicting URLs fail closed
- **WHEN** two supplied URLs resolve to different stable post ids on the same platform
- **THEN** the operation fails with a bounded diagnostic and writes nothing

#### Scenario: Re-running the same bundle
- **WHEN** the operator materializes the same bundle again
- **THEN** the existing import run is reused and no duplicate posts, references, or raw
  observations are written

#### Scenario: Seed materialization decides nothing
- **WHEN** a stub is created
- **THEN** no match candidates, relations, decisions, or identity claims exist for it, and
  later real observations enrich the same stub in place
