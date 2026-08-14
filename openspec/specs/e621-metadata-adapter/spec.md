## Purpose

Provide a first-class, metadata-only e621 adapter that preserves the provider's nested facts and
availability states while obeying its documented identification, pacing, pagination, privacy, and
authentication requirements.

## Requirements

### Requirement: e621 requests follow the provider policy
The system SHALL send a descriptive non-browser User-Agent on every e621 request, SHALL identify
the application according to provider policy, SHALL enforce a sustained interval of at least one
second between requests, and MUST NOT exceed two requests per second. Optional authentication
SHALL use externally resolved username and API-key material without retaining either secret.

#### Scenario: Anonymous metadata fetch
- **WHEN** public e621 metadata is requested without configured credentials
- **THEN** the request carries the descriptive application User-Agent and the same finite pacing and budget controls as an authenticated request

#### Scenario: Authenticated metadata fetch
- **WHEN** external e621 username and API-key references resolve successfully
- **THEN** the adapter uses provider-supported Basic authentication without placing either secret in durable request identity, raw metadata, diagnostics, or output

#### Scenario: Provider rate limit
- **WHEN** e621 reports rate limiting through HTTP 429 or 503
- **THEN** the run records a typed rate-limited or transient-provider outcome, retains allowlisted retry information, and does not exceed its request or time budget

### Requirement: e621 posts retain nested provider facts
The system SHALL normalize stable post identity; created and updated times; original file, sample,
and preview metadata; declared MD5, extension, byte size, and dimensions; categorized tags;
sources; rating; score; uploader; pools; relationships; counts; description presence; and provider
flags while retaining the complete raw response. Provider-declared hashes MUST remain distinct from
locally verified hashes.

#### Scenario: Normal post exposes three representations
- **WHEN** a post response contains original, sample, and preview objects
- **THEN** the catalog retains one ordered media occurrence with named variants, preserves which exact facts describe the original, and makes no request to any media URL

#### Scenario: Dynamic tag categories
- **WHEN** the provider returns tag arrays such as artist, character, copyright, species, lore, meta, contributor, invalid, or a future category
- **THEN** known categories retain their neutral mapping and unknown categories remain recoverable from raw data without being silently reassigned

#### Scenario: Post relationships
- **WHEN** a post declares a parent, children, pools, or sources
- **THEN** the catalog retains directed provider relationships and source references without treating them as same-work, authorship, or account-identity conclusions

### Requirement: Missing media URLs and deletion are modeled explicitly
The system SHALL accept null original, sample, or preview URLs without inventing or reconstructing
a URL. It SHALL distinguish a deleted post from a non-deleted post whose media is temporarily or
policy unavailable, while preserving any declared hashes, dimensions, tags, and flags returned by
the provider.

#### Scenario: Deleted post retains metadata
- **WHEN** e621 returns a post with its deleted flag set and null media URLs
- **THEN** the post is retained with deleted availability and its remaining provider facts stay queryable

#### Scenario: Non-deleted post has null URL
- **WHEN** a post is not deleted but one or more media URLs are null
- **THEN** the occurrence or variant is marked unavailable without misclassifying the post as deleted or deriving a URL from its MD5

#### Scenario: Unknown post ID
- **WHEN** an explicit post ID returns HTTP 404
- **THEN** the adapter records an unavailable typed outcome and does not create invented post or occurrence data

### Requirement: e621 post enumeration uses bounded keyset pagination
The system SHALL enumerate posts through the documented JSON listing endpoint with a maximum page
size of 320 and SHALL use ID-keyset continuations for resumable multi-page work. It MUST NOT depend
on shifting numeric pages or request a numeric page beyond the provider's supported window.

#### Scenario: Continue toward older IDs
- **WHEN** a listing page supplies posts and another page is admitted by all budgets
- **THEN** the continuation records the appropriate secret-free `b<ID>` boundary and the next request cannot repeat or skip a committed page

#### Scenario: Budget ends enumeration
- **WHEN** a request, page, record, or elapsed-time limit is reached
- **THEN** enumeration pauses before the next request and retains the last committed keyset continuation

#### Scenario: Invalid continuation
- **WHEN** a continuation has an incompatible provider, adapter, operation, target, direction, or version
- **THEN** resume fails before creating a request

### Requirement: e621 attribution metadata remains distinct from account identity
The system SHALL retain e621 tag, approved tag-alias, and artist records as provider attribution
evidence. Artist-category tags, artist records, other names, linked users, domains, and URLs MUST
NOT be materialized as external accounts or confirmed authorship without a separate stable account
reference and review decision.

#### Scenario: Artist tag and uploader differ
- **WHEN** a post has one or more artist-category tags and an uploader name or ID
- **THEN** artist tags are retained as attribution and the uploader is retained only in the uploader role

#### Scenario: Approved alias resolves a tag
- **WHEN** a retained active alias maps an antecedent artist tag to a consequent tag
- **THEN** the mapping remains typed alias evidence with its provider identifiers, status, timestamps, and raw observation

#### Scenario: Artist record exposes external URLs
- **WHEN** an e621 artist record contains other names, domains, or profile URLs
- **THEN** those values remain attribution metadata and eligible external-link evidence rather than an automatic account identity

### Requirement: e621 adapter behavior is fixture-backed and offline by default
The default test suite SHALL use committed redacted response fixtures and injected transports for
all supported e621 operations. Live tests SHALL be opt-in, metadata-only, strictly bounded, and
MUST NOT contact returned media hosts.

#### Scenario: Default test suite
- **WHEN** tests run without live-provider opt-in
- **THEN** no e621 API, static media, authentication, or external source endpoint is contacted

#### Scenario: Provider adds an unknown field
- **WHEN** a fixture or live response contains an unrecognized field
- **THEN** raw retention preserves it while normalized output remains versioned and bounded
