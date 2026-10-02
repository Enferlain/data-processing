## Purpose

Provide explicit, bounded Gelbooru metadata ingestion through independently versioned DAPI and
HTML transports while preserving raw evidence, secrets, provider uncertainty, and offline safety.

## Requirements


### Requirement: Gelbooru transport selection is explicit and durable
Every Gelbooru metadata operation SHALL identify whether it uses credentialed JSON DAPI or
anonymous HTML, and the selected transport and parser version SHALL be retained with its run and
raw observation. The system MUST NOT silently retry an operation through the other transport after
authentication, authorization, challenge, parsing, or provider failure.

#### Scenario: User selects DAPI
- **WHEN** a user requests a Gelbooru post through the DAPI transport
- **THEN** only the credentialed JSON endpoint is contacted and an API failure remains a typed DAPI outcome

#### Scenario: User selects HTML
- **WHEN** a user requests one Gelbooru post through the HTML transport
- **THEN** only the canonical public post page is contacted and no API, listing, media, or unrelated page is requested

### Requirement: DAPI requests are credentialed, bounded, and secret-free
The DAPI transport SHALL resolve a Gelbooru user ID and API key from external configuration,
request JSON explicitly, cap provider pages at 100 records, and apply finite request, page, record,
body-size, and elapsed-time limits. Credential values and credential-bearing URLs MUST NOT enter
durable request identities, raw observations, logs, diagnostics, or normal output.

#### Scenario: Credentials resolve successfully
- **WHEN** both external Gelbooru credential references resolve for an admitted DAPI request
- **THEN** they are added only to the outgoing query and durable provenance retains a sanitized operation identity

#### Scenario: Credentials are absent or partial
- **WHEN** either required DAPI credential is unavailable
- **THEN** the operation fails before network access with bounded configuration guidance and no secret value

#### Scenario: DAPI listing reaches a budget
- **WHEN** an explicitly requested bounded listing has another `pid` page after a finite limit is reached
- **THEN** it pauses before the next request and retains a transport- and target-scoped continuation

### Requirement: HTML metadata is single-post and non-recursive
The HTML transport SHALL accept only one explicitly supplied stable numeric post ID, request one
canonical HTTPS post page, enforce finite response-size and elapsed-time limits, and parse only
metadata contained in that response. It MUST NOT enumerate listings, follow source links, load
scripts, use browser automation, establish a login session, or request thumbnails or media bytes.

#### Scenario: Public post page is available
- **WHEN** the selected Gelbooru post page returns a fixture-compatible document
- **THEN** one raw HTML observation and its normalized post facts are retained without any secondary request

#### Scenario: Page markup is incompatible
- **WHEN** required stable identity or metadata markers cannot be validated
- **THEN** the raw HTML is retained and the operation reports malformed response without inventing fields or switching to DAPI

### Requirement: Normalization preserves only evidenced Gelbooru facts
The adapter SHALL retain stable post ID, observation time, availability, source, uploader role,
rating, score, declared MD5, dimensions, returned media representations, tag spelling, and tag
category evidence only when supplied and validated by the selected transport's versioned fixture
contract. It MUST NOT derive absent media URLs, infer creator identity from uploader or tags, or
interpret undocumented native fields as reviewed relationships.

#### Scenario: DAPI returns original and preview URLs
- **WHEN** a post response supplies validated original, sample, or preview locations
- **THEN** named metadata-only variants retain those returned locations while the original MD5 remains a provider declaration

#### Scenario: HTML exposes categorized tags
- **WHEN** a post page supplies fixture-proven artist, character, copyright, or general category markers
- **THEN** the normalized tag observations retain those native categories and their raw HTML provenance

#### Scenario: DAPI supplies uncategorized tag text
- **WHEN** a DAPI post supplies tag names without a proven category mapping
- **THEN** the tags remain recoverable with native category unknown rather than being guessed from undocumented numeric conventions

### Requirement: DAPI and HTML observations reconcile without erasing history
Observations from either transport SHALL upsert the same platform-namespaced post identity while
retaining independent raw payloads, request provenance, transport versions, timestamps, and
transport-specific facts. A later partial observation MUST NOT erase a previously retained fact
solely because the other transport omitted it.

#### Scenario: Same post is fetched through both transports
- **WHEN** DAPI and HTML independently observe the same Gelbooru numeric post ID
- **THEN** the catalog retains one stable post with two auditable raw observations and no duplicate user activity

#### Scenario: Transport facts disagree
- **WHEN** two observations report different mutable metadata or availability
- **THEN** both raw claims remain auditable and the current projection follows a documented observation policy rather than silently merging them as truth

### Requirement: Gelbooru failures are typed and do not trigger media access
The adapter SHALL distinguish missing credentials, authentication-required, authorization or
challenge denial, unavailable post, rate-limited, transient provider, oversized response, and
malformed payload outcomes. No failure or successful metadata response SHALL cause a media-host
request, asset creation, implicit retry through another transport, or background crawl.

#### Scenario: API returns 401
- **WHEN** Gelbooru rejects DAPI credentials with HTTP 401
- **THEN** the run records authentication-required without exposing the credential-bearing request URL

#### Scenario: Provider returns a challenge page
- **WHEN** DAPI or HTML returns an authorization challenge or non-contract document
- **THEN** the response is retained under policy and the run fails with a bounded typed diagnostic rather than parsing it as a post

#### Scenario: Metadata contains media links
- **WHEN** a successful response contains original, sample, or thumbnail URLs
- **THEN** those URLs remain metadata and their hosts receive zero requests during synchronization

### Requirement: Gelbooru behavior is fixture-backed and live checks are opt-in
The default suite SHALL use committed minimal redacted DAPI and HTML fixtures with injected
transports and zero external requests. Any live Gelbooru test SHALL require explicit opt-in,
external credentials when using DAPI, provider-policy acknowledgement, one-post or tightly bounded
metadata scope, and hard request, response, record, and time limits.

#### Scenario: Default test execution
- **WHEN** tests run without Gelbooru live opt-in
- **THEN** no Gelbooru API, HTML page, media host, source site, or authentication endpoint is contacted

#### Scenario: Real variation examples are fixtures
- **WHEN** the five retained acceptance post IDs are used for compatibility coverage
- **THEN** their redacted metadata exercises exact-match and user-labelled variation cases without embedding credentials or media bytes
