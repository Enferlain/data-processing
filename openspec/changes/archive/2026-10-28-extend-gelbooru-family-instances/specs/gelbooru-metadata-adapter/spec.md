# Spec Delta

## ADDED Requirements

### Requirement: Gelbooru-engine instances are registered and identified
The adapter SHALL serve a registered family of gelbooru-engine instances. Each instance SHALL
declare a distinct platform key, its canonical HTTPS base URL, per-instance external credential
references, and per-instance schema, transport, and parser versions; runs, requests, raw
observations, and platform rows SHALL carry the instance's platform key. A metadata operation
SHALL be admitted only for a platform key whose operations are registered in the kernel's
per-platform operation registry, and instance selection SHALL be explicit on every surface that
offers more than one instance. The anonymous HTML transport SHALL remain available only for the
canonical gelbooru.com instance.

#### Scenario: Operator selects a family instance
- **WHEN** an operator runs a DAPI metadata operation against a registered family instance
- **THEN** all requests target that instance's canonical base URL and every retained row is attributed to its platform key

#### Scenario: Unregistered platform key
- **WHEN** a remote run names a platform key that no registered instance uses
- **THEN** the run contract refuses the operation before any request is made

## MODIFIED Requirements

### Requirement: DAPI requests are credentialed, bounded, and secret-free
Each instance SHALL declare whether its DAPI requires credentials. For instances that require
them, the transport SHALL resolve the user ID and API key from that instance's external
configuration and fail before network access when either is absent. For instances that declare
anonymous DAPI, requests SHALL proceed without credentials and credential-bearing configuration
SHALL not be required. All instances SHALL request JSON explicitly, cap provider pages at 100
records, apply finite request, page, record, body-size, and elapsed-time limits, and keep
credential values and credential-bearing URLs out of durable request identities, raw
observations, logs, diagnostics, and normal output.

#### Scenario: Credentials resolve successfully
- **WHEN** both external credential references resolve for an admitted DAPI request on an instance that requires them
- **THEN** they are added only to the outgoing query and durable provenance retains a sanitized operation identity

#### Scenario: Credentials are absent or partial on a credentials-required instance
- **WHEN** either required DAPI credential is unavailable
- **THEN** the operation fails before network access with bounded configuration guidance and no secret value

#### Scenario: Anonymous DAPI on an instance that allows it
- **WHEN** an instance declares anonymous DAPI and no credentials are configured
- **THEN** the request proceeds without credential parameters and provenance retains the same sanitized identity shape

#### Scenario: DAPI listing reaches a budget
- **WHEN** an explicitly requested bounded listing has another `pid` page after a finite limit is reached
- **THEN** it pauses before the next request and retains a transport- and target-scoped continuation

### Requirement: Gelbooru behavior is fixture-backed and live checks are opt-in
The default suite SHALL use committed minimal redacted fixtures per registered instance —
captured from the live instance's responses, never synthetic shapes — with injected transports
and zero external requests. A new family instance SHALL land only together with a live-captured,
credential-free fixture for each response shape its surfaces parse; an instance whose responses
cannot be captured is deferred, not shipped synthetic. Any live test SHALL remain opt-in, require
external credentials when the instance's DAPI uses them, acknowledge provider policy, and stay
bounded to one post or a tightly scoped listing with hard request, response, record, and time
limits.

#### Scenario: Default test execution
- **WHEN** tests run without live opt-in
- **THEN** no family instance's API, HTML page, media host, source site, or authentication endpoint is contacted

#### Scenario: A family instance joins with verified shapes
- **WHEN** a new instance is registered
- **THEN** its parsing contract is exercised exclusively against redacted bytes captured from that instance's live responses

### Requirement: Opt-in dapi note collection
The gelbooru dapi adapter SHALL support fetching the notes of one post by native identifier via
that instance's dapi note endpoint under the bounded run contract, as an explicit operator action
separate from default post sync, using the adapter's transport under the instance's credential
policy (credentialed where the instance requires it, anonymous where the instance allows it).
Each note observation SHALL retain the provider note identifier, body text, and position,
deduplicated by a digest over those facts. The operation SHALL require an already-retained post
and SHALL retain the raw source report with provenance. The response contract is verified by
live capture under the instance's credential policy, and the retained fixture carries the
captured bytes.

#### Scenario: Notes land with position
- **WHEN** an operator enriches a retained post whose dapi note query returns note entries
- **THEN** one observation per note is retained carrying body, position, and provider note id,
  anchored to the raw report

#### Scenario: A note edit lands as a new observation
- **WHEN** a later fetch reports changed body or position for the same note id
- **THEN** a new observation is retained and the earlier one remains queryable
