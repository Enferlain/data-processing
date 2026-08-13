## ADDED Requirements

### Requirement: Stable e621 attribution can seed library expansion
Artist-library expansion SHALL allow a confirmed or explicitly selected stable e621 attribution
entity to enumerate posts through the versioned e621 artist-tag capability. It MUST preserve the
attribution target, exact provider tag identity, authority provenance, adapter/schema versions,
finite limits, and ID-keyset resume state without relabeling the attribution as an account.

#### Scenario: Explicit e621 attribution target
- **WHEN** a user selects a stable retained e621 artist attribution with a bounded note
- **THEN** offline planning produces an e621 attribution expansion choice and asserts no account identity or global authorship relationship

#### Scenario: Enumerated e621 posts enter the library workflow
- **WHEN** a current e621 expansion plan executes successfully
- **THEN** committed posts and occurrences are associated with that expansion and can be browsed and explicitly acquired without receiving liked or bookmarked activity

#### Scenario: Expansion resumes by post ID
- **WHEN** an e621 expansion pauses after committing a page
- **THEN** an explicit compatible resume uses the retained ID-keyset continuation without recursively expanding any discovered artist, alias, uploader, source, or account

### Requirement: e621 expansion estimates are evidence-bounded
The system SHALL report an exact retained e621 artist-tag `post_count` only when a current retained
tag observation unambiguously identifies the selected canonical artist tag. Arbitrary multi-tag or
filtered expansion counts SHALL remain unknown unless a later versioned provider capability proves
them; planning MUST NOT run a listing request merely to estimate size.

#### Scenario: Canonical artist tag has retained count
- **WHEN** the selected attribution maps unambiguously to a retained current artist-category tag with `post_count`
- **THEN** the offline plan reports that provider count, its observation time, source, and capability version

#### Scenario: Alias or filtered target lacks exact count
- **WHEN** the target depends on unresolved alias state, additional filters, or lacks a current exact tag observation
- **THEN** the plan reports an unknown estimate without network access
