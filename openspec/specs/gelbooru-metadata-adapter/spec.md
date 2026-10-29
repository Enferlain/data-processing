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
rating, score, declared MD5, dimensions, returned media representations, title, parent post
references as directional relations, tag spelling, and tag category evidence only when supplied
and validated by the selected transport's versioned fixture contract. DAPI detail requests
SHALL request typed tag info, and when the response supplies it, tags SHALL normalize under
the neutral categories (`tag`→general, `metadata`→meta, other documented type names
passthrough, anything else unknown). It MUST NOT derive absent media URLs, infer creator
identity from uploader or tags, or interpret undocumented native fields as reviewed
relationships.

#### Scenario: DAPI returns original and preview URLs
- **WHEN** a post response supplies validated original, sample, or preview locations
- **THEN** named metadata-only variants retain those returned locations while the original MD5 remains a provider declaration

#### Scenario: HTML exposes categorized tags
- **WHEN** a post page supplies fixture-proven artist, character, copyright, or general category markers
- **THEN** the normalized tag observations retain those native categories and their raw HTML provenance

#### Scenario: DAPI supplies uncategorized tag text
- **WHEN** a DAPI post supplies tag names without a proven category mapping
- **THEN** the tags remain recoverable with native category unknown rather than being guessed from undocumented numeric conventions

#### Scenario: DAPI detail supplies typed tag info
- **WHEN** a DAPI detail response carries `tag_info` entries with string types
- **THEN** each tag normalizes under its neutral category (`tag`→general, `metadata`→meta,
  undocumented type names stay unknown) while listings without tag info keep flat unknown tags

#### Scenario: Post references a parent
- **WHEN** a DAPI post record carries a parent post ID
- **THEN** the catalog retains one directional parent relation to that stable post reference
  without labeling their visual variation type

#### Scenario: Post carries a title
- **WHEN** a DAPI post record supplies a title string
- **THEN** the post projection retains it as metadata alongside its raw provenance

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

#### Scenario: Real variation examples are fixtures
- **WHEN** the five retained acceptance post IDs are used for compatibility coverage
- **THEN** their redacted metadata exercises exact-match and user-labelled variation cases without embedding credentials or media bytes

### Requirement: Gelbooru bounded reverse lookup is exact, credentialed, and evidence-only
The DAPI adapter SHALL declare and implement bounded reverse lookup by canonical source URL
and by exact MD5 (declared or locally verified) using the credentialed DAPI transport, with
exact query tokens only, digest-based request identities, pid-based page continuation under
the shared limits, and retained raw responses. Undeclared strategies, wildcard or whitespace
source tokens, non-hex hash material, and missing credentials MUST be rejected before any
request. Lookup results SHALL reuse the post normalizer and remain evidence: they MUST NOT
establish post equivalence, account identity, or authorship, and the HTML transport MUST NOT
gain lookup.

#### Scenario: Look up by declared MD5
- **WHEN** a bounded run searches DAPI for an exact MD5 and the provider returns a post
- **THEN** the result retains the provider post identity, source, declared MD5, uploader, and
  availability as evidence and lands as pending review material, never as a conclusion

#### Scenario: Unsupported strategy is excluded without a request
- **WHEN** planning requests a strategy gelbooru does not declare (external post ID, artist
  name, alias, or free text)
- **THEN** the plan reports it as unsupported and no provider request is made

#### Scenario: Missing credentials fail before transport
- **WHEN** a lookup execution is attempted without DAPI credentials
- **THEN** the attempt fails closed with a credential diagnostic and no provider contact

#### Scenario: Full page continues under bounds
- **WHEN** a lookup page returns a full result set
- **THEN** the run may continue at the next pid boundary under its admitted limits and stops
  cleanly when a budget is reached

### Requirement: Opt-in dapi note collection
The gelbooru dapi adapter SHALL support fetching the notes of one post by native identifier via
that instance's dapi note endpoint under the bounded run contract, as an explicit operator action
separate from default post sync, using the adapter's transport under the instance's credential
policy (credentialed where the instance requires it, anonymous where the instance allows it).
Each note observation SHALL retain the provider note identifier, body text, and position,
deduplicated by a digest over those facts. The operation SHALL require an already-retained post
and SHALL retain the raw source report with provenance. The response contract is verified by
live capture under the instance's credential policy (2026-10-28): the dapi note index returns
XML regardless of json=1, and the retained fixture carries the captured bytes.

#### Scenario: Notes land with position
- **WHEN** an operator enriches a retained post whose dapi note query returns note entries
- **THEN** one observation per note is retained carrying body, position, and provider note id,
  anchored to the raw report

#### Scenario: A note edit lands as a new observation
- **WHEN** a later fetch reports changed body or position for the same note id
- **THEN** a new observation is retained and the earlier one remains queryable

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
