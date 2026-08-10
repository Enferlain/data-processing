## Purpose

Provide safe, resumable, and auditable metadata-only interaction with remote providers without
turning catalog enrichment into an unbounded crawl, an implicit media download, or a secret leak.

## ADDED Requirements

### Requirement: Remote operations are explicitly bounded
Every remote metadata operation SHALL require positive request, page, record, and elapsed-time
budgets, SHALL stop when the first budget is exhausted, and SHALL report which budget ended the
operation. Provider defaults MAY be stricter than user-supplied limits but SHALL NOT silently widen
them.

#### Scenario: Page budget is exhausted
- **WHEN** another continuation page exists after the configured page budget has been consumed
- **THEN** the run stops without requesting that page and reports the page-budget boundary

#### Scenario: Single-object request
- **WHEN** a user fetches one explicitly identified account or post
- **THEN** the operation still enforces request and elapsed-time budgets

### Requirement: Runs and checkpoints are durable and resumable
The system SHALL record a remote run independently of finite-file import runs and SHALL durably
retain its platform, instance, operation, canonical target, adapter version, budgets, counters,
status, continuation checkpoint, and timestamps. A continuation checkpoint SHALL advance only in
the same successful transaction that associates an already retained raw response with all
successfully persisted normalized records for that page.

#### Scenario: Process stops after committing a page
- **WHEN** a paginated run is resumed after its last page transaction committed
- **THEN** it starts from the committed continuation checkpoint without duplicating normalized
  records or provenance associations

#### Scenario: Page normalization fails
- **WHEN** a provider response is retained but validation or normalized persistence fails
- **THEN** the continuation checkpoint does not advance and the failure remains visible on the run

#### Scenario: Completed target is fetched again
- **WHEN** the same target and operation are run again with a new observation time
- **THEN** a new auditable run may be recorded while stable normalized identities remain idempotent

### Requirement: Remote responses retain complete provenance
For every provider response used by normalization, the system SHALL retain the unmodified response
bytes and associate them with the platform instance, canonical secret-free request identity,
adapter and response-schema versions, observation time, HTTP status, normalized object kind and
native identifier when known, and the run that requested it.

#### Scenario: Provider adds an unknown field
- **WHEN** a response contains a field the installed adapter does not normalize
- **THEN** the field remains recoverable from the retained raw response

#### Scenario: Equivalent requests contain credentials
- **WHEN** authentication is transported in a header, query parameter, cookie, or token exchange
- **THEN** the durable request identity excludes the secret while still distinguishing the
  provider operation and non-secret request parameters

### Requirement: Failures are typed and preserve retry information
The system SHALL distinguish unavailable, deleted, authentication-required, authorization-denied,
rate-limited, transient-provider, malformed-response, budget-exhausted, and local-persistence
outcomes. When a provider supplies a retry time or rate-limit state, the system SHALL retain its
non-secret value and SHALL NOT retry beyond the run's request or elapsed-time budget.

#### Scenario: Provider returns a rate limit
- **WHEN** a response indicates rate limiting and supplies a retry time
- **THEN** the run records the typed outcome and retry time without busy-looping or exceeding its
  budgets

#### Scenario: Response shape is incompatible
- **WHEN** required fields cannot be validated under the recorded adapter schema version
- **THEN** the raw response is retained, no invented normalized values are stored, and the run
  reports a malformed-response failure

### Requirement: Credentials remain external and secret
Remote credentials SHALL be obtained from an external configuration reference or environment,
SHALL NOT be accepted as literal command-line arguments, and SHALL NOT be stored in the catalog,
raw payloads, request identities, logs, diagnostics, or structured command output.

#### Scenario: Authentication fails
- **WHEN** a supplied credential is rejected by a provider
- **THEN** the diagnostic identifies the provider and authentication-required outcome without
  revealing the credential or authentication header

#### Scenario: No credential is configured
- **WHEN** an operation requires authentication but no credential reference resolves
- **THEN** the system fails before making the protected request and explains how to configure a
  credential reference

### Requirement: Metadata synchronization never downloads media
Remote metadata commands SHALL request only provider metadata responses and SHALL NOT fetch media
bytes, populate managed asset storage, or modify existing assets. Original, preview, sample, and
animation archive URLs SHALL be retained only as media-occurrence metadata.

#### Scenario: Artwork exposes original files
- **WHEN** an adapter receives original image URLs for an artwork
- **THEN** it stores metadata-only occurrences and performs no request to those URLs

### Requirement: Live provider tests are opt-in and bounded
The default automated test suite SHALL use redacted local fixtures and make zero network requests.
Live smoke tests SHALL require an explicit opt-in, external credentials when necessary, and hard
request, record, and elapsed-time limits.

#### Scenario: Default test execution
- **WHEN** the test suite runs without the live-test opt-in
- **THEN** no Pixiv, Danbooru, AIBooru, media-host, or OAuth endpoint is contacted
