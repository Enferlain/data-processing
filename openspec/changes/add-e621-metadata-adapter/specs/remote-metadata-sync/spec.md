## ADDED Requirements

### Requirement: Provider request gates enforce e621-specific constraints
Remote metadata synchronization SHALL allow an e621 adapter to require a descriptive application
User-Agent, a minimum one-second request interval, a maximum page size of 320, optional external
Basic authentication, and ID-keyset continuations while preserving the existing generic budgets,
raw retention, typed outcomes, transactions, and resume semantics.

#### Scenario: Standalone e621 synchronization
- **WHEN** a user explicitly fetches or lists e621 metadata
- **THEN** the shared synchronization loop applies both its generic finite budgets and the stricter e621 request policy without changing standalone behavior for other providers

#### Scenario: Secret-free authenticated run
- **WHEN** an e621 request uses Basic authentication
- **THEN** only the names of credential references and a sanitized request identity are durable while the Authorization value remains ephemeral

#### Scenario: Keyset page commits
- **WHEN** an e621 listing page normalizes and persists successfully
- **THEN** its raw response, normalized records, and next ID-keyset continuation commit atomically through the existing page transaction
