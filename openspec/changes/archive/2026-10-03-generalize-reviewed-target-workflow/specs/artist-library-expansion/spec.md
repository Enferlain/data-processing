## ADDED Requirements

### Requirement: Target resolution reports review state and eligibility
The system SHALL resolve eligible expansion targets from a reviewed anchor — a confirmed identity's
member accounts, or an explicitly selected stable account or attribution — and report each
candidate target with its provider, stable native reference, target kind, applicable enumeration
capability, and current review state. Pending and rejected candidates SHALL be reported as
ineligible with their review state rather than silently omitted; explicit selection of an
otherwise eligible stable target remains governed by the existing target-authority requirement
and does not become a review decision. Resolution SHALL perform no network access and write no
catalog state.

#### Scenario: Confirmed identity anchors multiple providers
- **WHEN** a confirmed identity includes member accounts on two providers that both declare
  enumeration capabilities
- **THEN** resolution presents both as distinct eligible targets with their stable native
  references, capabilities, and review states

#### Scenario: Unconfirmed candidate is reported ineligible
- **WHEN** an account related to the anchor is only a pending or rejected match candidate
- **THEN** resolution reports it as ineligible with its review state instead of silently omitting
  it, and does not present it as confirmed; explicit selection of that stable target remains
  available under the existing target-authority requirement

#### Scenario: Resolution performs no network access
- **WHEN** target resolution runs
- **THEN** the system issues no provider request and writes no catalog state

### Requirement: Target capabilities are discoverable offline
The system SHALL expose, for any stable account or attribution target, the enumeration operations
currently supported — provider, capability key and version, operation, and adapter and schema
versions — together with explicit unsupported markers and reasons where a target kind lacks a
capability. Discovery SHALL be offline and derived from the current capability registry.

#### Scenario: Supported account target
- **WHEN** the user asks for capabilities of a stable Pixiv account
- **THEN** the system lists the account-artworks enumeration capability with its versions and no
  provider request is made

#### Scenario: Supported attribution target
- **WHEN** the user asks for capabilities of a stable e621 attribution entity
- **THEN** the system lists the artist-tag enumeration capability with its versions and no
  provider request is made

#### Scenario: Attribution target without a capability
- **WHEN** the user asks for capabilities of an attribution entity whose provider declares no
  enumeration capability
- **THEN** the system reports that target kind as unsupported for that provider with a bounded
  reason
