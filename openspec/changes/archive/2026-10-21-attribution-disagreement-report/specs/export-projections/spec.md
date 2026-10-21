## ADDED Requirements

### Requirement: Attribution disagreements project over linked posts
The system SHALL provide an `attribution-disagreements` export projection kind emitting one
row per retained post-level relationship (`reposted_from`, `same_work`) whose ends disagree
on artist attribution: both ends carry attribution, and no cross-pair of attribution
identities is joined by a confirmed identity membership. The projection SHALL be offline and
read-only, SHALL follow the existing manifest recipe and digest contracts, and SHALL NOT
create, modify, or override any review decision, candidate, or relationship.

#### Scenario: Unjoined attributions surface as one disagreement row
- **WHEN** two posts are linked by a retained relationship and each end's artist attribution
  — account participants with artist or author roles, plus provider attribution entities
  implied by the post's tags — resolves to identities no confirmed identity membership joins
- **THEN** the export emits one row listing both ends' attribution identities (platform,
  native identifier, primary name, review state), the linking relationship's kind and
  epistemic status, stable evidence-layer identifiers, and a name-equality hint marked as
  weak evidence

#### Scenario: Confirmed identities exclude a pair
- **WHEN** any account identity on one end is joined to one on the other end by a confirmed
  identity membership
- **THEN** the pair is excluded from the rows and reported under the confirmed-join
  exclusion count

#### Scenario: Other exclusions are counted with reasons
- **WHEN** a linked pair lacks attribution on either end, the relationship's review state is
  rejected, or rows fall beyond the export limit
- **THEN** the pair or row is excluded and counted under the matching bounded reason

#### Scenario: The report never settles anything
- **WHEN** the attribution-disagreements projection runs
- **THEN** no review decision, candidate, relationship, or other evidence-layer row is
  written, and the manifest states the report-only policy
