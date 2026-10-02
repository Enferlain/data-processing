## ADDED Requirements

### Requirement: Remote synchronization preserves explicit provider transport identity
Remote metadata synchronization SHALL allow a provider operation to bind an explicit transport and
transport version into its plan, request identity, raw provenance, and resume compatibility. It
MUST NOT substitute a different transport after a committed plan or failed request.

#### Scenario: Gelbooru DAPI run is resumed
- **WHEN** a paused Gelbooru DAPI listing is resumed under compatible limits
- **THEN** the transport, target, adapter/schema versions, and continuation are revalidated before the next request

#### Scenario: Caller changes transport
- **WHEN** a resume or retry selects HTML for a run created with DAPI, or DAPI for a run created with HTML
- **THEN** synchronization rejects the incompatible operation before network access

### Requirement: Credential-bearing query authentication remains ephemeral
Remote synchronization SHALL support provider credentials carried in query parameters while
ensuring that secret values and rendered credential-bearing URLs exist only at the transport
boundary. Retained requests and public results SHALL expose only allowlisted non-secret operation
fields and credential-reference names.

#### Scenario: Gelbooru DAPI request is retained
- **WHEN** a credentialed DAPI response is stored before normalization
- **THEN** the raw response and sanitized request attempt remain auditable without the API key, user ID value, or rendered URL
