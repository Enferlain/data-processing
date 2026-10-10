## ADDED Requirements

### Requirement: Works projection groups variant families per work
The system SHALL provide a `works` export projection kind emitting one row per work: its
stable identifier and origin post identity, its representations with roles and verified-byte
links, a preferred-representation selection computed under a stated policy that excludes
thumbnail and preview roles and prefers the upstream original, and a summary of its
`same_work` relationships. The manifest SHALL state the grouping, exclusion, and preference
policies. Selection and exclusion counts with reasons SHALL follow the existing manifest
contract.

#### Scenario: Thumbnails never become the preferred representation
- **WHEN** a work's representations include sample or preview roles alongside an original
- **THEN** the works projection row lists them all but selects the preferred representation
  from the non-thumbnail roles, and the manifest states that policy

#### Scenario: Works rows stay auditable
- **WHEN** a works projection is exported
- **THEN** each row carries stable work and representation identifiers resolving back to the
  evidence layer, and re-running against unchanged evidence reproduces the digests
