## Purpose

Turn links already present in local catalog records into durable, queryable observations and stable
platform references while preserving their source context and requiring no network access.

## Requirements

### Requirement: Extract links with source provenance
The system SHALL extract external URLs from supported normalized account and post fields and from
supported retained raw-record fields, and SHALL record the subject, field or context, source
observation, observation time, extraction version, and original URL for each occurrence.

#### Scenario: Account profile contains a website
- **WHEN** an account snapshot contains an external website URL
- **THEN** discovery records a link observation tied to that snapshot without replacing the stored profile value

#### Scenario: Post raw data contains expanded entity and card links
- **WHEN** a retained X or xarchive post record contains supported expanded entity or card URLs
- **THEN** discovery records each URL with its post and source-field context

### Requirement: Preserve original and canonical URL forms
The system SHALL retain the original observed URL separately from its deterministic canonical form
and SHALL identify the canonicalization algorithm and version used.

#### Scenario: URL contains removable tracking parameters
- **WHEN** a supported URL differs only by recognized tracking parameters or a known host alias
- **THEN** discovery preserves the original URL and produces the same canonical URL as equivalent observations

#### Scenario: Canonicalization is uncertain
- **WHEN** removing or rewriting a URL component could change its resource identity
- **THEN** discovery leaves that component intact rather than guessing

### Requirement: Parse typed platform references
The system SHALL use versioned recognizers to parse supported canonical URLs into a platform,
object kind, identifier kind, identifier, and canonical target URL without treating a
booru artist record, uploader account, post, or artwork as interchangeable object kinds.

#### Scenario: Recognize a Pixiv user URL
- **WHEN** a canonical URL contains a supported Pixiv user path with a stable numeric identifier
- **THEN** discovery records a Pixiv account reference using that stable identifier

#### Scenario: Recognize a Pixiv artwork URL
- **WHEN** a canonical URL contains a supported Pixiv artwork path with a stable numeric identifier
- **THEN** discovery records a Pixiv post reference separately from any account reference

#### Scenario: Recognize a mutable X handle
- **WHEN** a canonical URL identifies an X account only by its handle
- **THEN** discovery records a handle-kind account reference that remains ineligible for identity
  matching or account materialization until a stable provider account ID is known

#### Scenario: Recognize a Danbooru-family object
- **WHEN** a canonical URL identifies a supported Danbooru-family post or artist record
- **THEN** discovery retains the specific instance, object kind, and stable identifier or artist name available in the URL

#### Scenario: Recognize legacy and query-style booru post routes
- **WHEN** a URL identifies a post through a supported `/post/show/<id>` route or a Gelbooru-style `page=post`, `s=view`, and `id=<id>` query
- **THEN** discovery records an instance-qualified post reference while retaining the original route and query

#### Scenario: Recognize a Mastodon-compatible status
- **WHEN** a URL contains a supported instance-qualified `/@account/<status-id>` route
- **THEN** discovery records a status/post reference for that instance without assuming the display handle is its stable account ID

### Requirement: Semantic references are independent of observed URLs
The system SHALL identify a semantic platform reference by platform, instance, object kind,
identifier kind, identifier, and recognizer version independently of the canonical external links
that yielded it. A semantic reference MAY be associated with many external links and one external
link MAY yield multiple semantic references without replacing an earlier association.

#### Scenario: URL aliases identify one Pixiv account
- **WHEN** two distinct canonical URL aliases or query variants recognize the same Pixiv account
- **THEN** both link observations remain associated with the same platform reference and link
  queries return the platform, object kind, identifier kind, and identifier for each observation

### Requirement: Retain unresolved external links
The system SHALL keep valid links that cannot be mapped to a stable supported platform reference and
SHALL report why resolution is pending or unsupported without fabricating an identifier.

#### Scenario: Shortened URL requires a redirect
- **WHEN** a URL does not expose its destination without a network redirect
- **THEN** offline discovery stores it as unresolved and performs no request

#### Scenario: Personal or link-hub URL
- **WHEN** a URL points to an unsupported personal site or link hub
- **THEN** it remains queryable as an external reference for later bounded resolution

### Requirement: Discovery is offline and idempotent
The system SHALL perform link discovery without network access and SHALL derive stable observation
and reference keys so repeated runs with the same inputs and algorithm versions do not duplicate
records.

#### Scenario: Repeat discovery
- **WHEN** discovery is run twice over an unchanged catalog with the same extractor and recognizer versions
- **THEN** the second run reports existing link observations and references without creating duplicates

#### Scenario: Network is unavailable
- **WHEN** socket connection creation is denied during discovery and link queries
- **THEN** both operations complete using only catalog data

### Requirement: Query link observations and references
The CLI SHALL provide human-readable and stable structured output for discovering and listing links,
with filters for source subject, source context, target platform, target object kind, and resolution
state, while keeping raw private payload content out of default output.

#### Scenario: List links for one X account
- **WHEN** a user filters link results to a stable X account reference
- **THEN** the output includes that account's observed links, parsed targets, provenance summaries, and resolution states

#### Scenario: Script consumes discovery output
- **WHEN** discovery or listing is requested as structured output
- **THEN** the command emits one stable document containing run counts, algorithm versions, filters, and result records
