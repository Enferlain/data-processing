## MODIFIED Requirements

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
