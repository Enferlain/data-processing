# Sankaku Metadata Adapter Specification

## Purpose

Metadata-only integration with Sankaku's capi-v2 API: bounded, credentialed, capture-verified
synchronization of post facts and tag-enumerated listings into the catalog kernel without ever
requesting media bytes.

## Requirements

### Requirement: Sankaku instance identity is explicit and registered
The adapter SHALL serve the registered Sankaku instance (platform key `sankaku`, canonical
HTTPS base at the live-verified `sankakuapi.com` host) with per-instance schema and adapter versions. A metadata operation SHALL be
admitted only because the platform key is registered in the kernel's per-platform operation
registry and its platform row is migration-seeded; runs, requests, raw observations, and
platform rows SHALL carry the `sankaku` platform key.

#### Scenario: Operator runs a Sankaku metadata command
- **WHEN** an operator runs a Sankaku post or listing sync
- **THEN** every request targets the instance's canonical capi-v2 base URL and every retained row is attributed to `sankaku`

#### Scenario: Unregistered platform key
- **WHEN** a remote run names a platform key no registered instance uses
- **THEN** the run contract refuses the operation before any request is made

### Requirement: Sankaku credentials are exchanged for an ephemeral bearer token
The transport SHALL resolve a login and password from external configuration and exchange them
for an access token at the API's token endpoint before the first request; the operation SHALL
fail before network access when either credential is absent. The token SHALL exist only in HTTP
headers for the process lifetime — never in durable request identities, raw observations, logs,
diagnostics, retained fixtures, or normal output — and SHALL be re-exchanged when the provider
reports it invalid. The login/password pair itself SHALL never be transmitted anywhere except
the token endpoint.

#### Scenario: Credentials resolve and the token exchange succeeds
- **WHEN** both external credential references resolve
- **THEN** requests carry only the resulting bearer token and durable provenance retains a sanitized operation identity

#### Scenario: Credentials are absent or the exchange is refused
- **WHEN** either credential is unavailable or the provider rejects the exchange
- **THEN** the operation fails before any metadata request with bounded configuration guidance and no secret value

#### Scenario: The provider invalidates the token
- **WHEN** a metadata response reports the token invalid
- **THEN** the adapter re-exchanges once from the external credentials and retries the request; repeated failure ends the run typed as an authentication outcome

### Requirement: Sankaku post and listing operations are bounded
Post fetch SHALL resolve exactly one post by its opaque provider id via the id-range
query, and listings SHALL enumerate a tag query through the provider's keyset cursor under the
shared bounded-run contract (finite request, page, record, body-size, and elapsed-time limits;
cursor continuation is retained per run). Provider rate-limit responses SHALL end or pause the
run typed as a rate-limit outcome with the provider's reset signal retained when supplied —
never retried past the admitted budget.

#### Scenario: Single post fetch
- **WHEN** an operator fetches one post by id
- **THEN** one bounded request retains one raw observation and the post's evidenced facts

#### Scenario: Keyset listing continues under bounds
- **WHEN** a listing page returns a next cursor and budget remains
- **THEN** the run may continue at that cursor and retains the continuation when it pauses

#### Scenario: Rate limit response
- **WHEN** the provider returns a rate-limit response
- **THEN** the run pauses or ends typed as rate-limited without exceeding its budget or speculating past a supplied reset time

### Requirement: Sankaku normalization preserves only evidenced facts
The adapter SHALL retain stable post id, observation time, availability and status, rating,
score, declared MD5, dimensions, returned media representations (original/sample/preview URLs
as metadata only), source URL, parent-post references as directional relations, and tag
spelling with typed categories from the embedded tag objects (kernel categories only; other
provider types and the fuller tag-name array land as unknown category) — each only when the
captured contract supplies and validates it. Nothing SHALL be invented, and media hosts receive
zero requests.

#### Scenario: Post facts land from a captured contract
- **WHEN** a post response matches the captured fixture contract
- **THEN** the evidenced facts land as observations and no media URL is requested

#### Scenario: Response shape violates the captured contract
- **WHEN** a required stable identity or shape marker is absent or malformed
- **THEN** the raw response is retained and the operation reports malformed response

### Requirement: Sankaku behavior is fixture-backed and live checks are opt-in
The default suite SHALL use committed minimal redacted fixtures captured from the live
credentialed API — never synthetic shapes — with injected transports and zero external
requests. The adapter's surfaces SHALL land only together with captured fixtures for each
response shape they parse; an instance or surface whose responses cannot be captured is
deferred. Any live test SHALL remain opt-in, require the external credentials, acknowledge
provider policy, and stay bounded with hard limits.

#### Scenario: Default test execution
- **WHEN** tests run without live opt-in
- **THEN** no Sankaku API, media host, source site, or token endpoint is contacted

#### Scenario: Fixture provenance is verifiable
- **WHEN** a fixture suite is committed
- **THEN** its manifest names the capture date, schema version, and redactions, and its bytes contain no credential or token material
