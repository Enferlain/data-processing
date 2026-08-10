## Purpose

Ingest metadata from Danbooru-compatible instances without conflating uploader accounts, community
artist attribution, source references, or provider-declared file identity.

## Requirements

### Requirement: Danbooru-family instances have independent platform identity
Each configured Danbooru-family instance SHALL have an explicit platform key, canonical base URL,
adapter compatibility declaration, credential reference, and request policy. Equal native IDs on
Danbooru and AIBooru SHALL NOT collide.

#### Scenario: Equal post IDs on two instances
- **WHEN** Danbooru and AIBooru each return post `123`
- **THEN** the catalog retains two posts under their independent platform identities

#### Scenario: Unsupported response shape
- **WHEN** a configured instance claims compatibility but returns an incompatible required shape
- **THEN** the raw response is retained and the run reports a malformed-response outcome rather
  than applying another instance's assumptions

### Requirement: Booru post metadata preserves provider fields and categories
The adapter SHALL retain post ID, canonical URL, creation and update times, rating, status and
availability flags, dimensions, file size, MIME or extension hints, original/sample/preview URLs,
source value, Pixiv ID when supplied, and tags separated into artist, character, copyright,
general, and meta categories.

#### Scenario: Available post with categorized tags
- **WHEN** a post response contains all supported tag categories
- **THEN** each tag remains associated with the post under its provider category and spelling

#### Scenario: Deleted post retains identity
- **WHEN** a post is deleted or its media is unavailable but its metadata remains visible
- **THEN** the stable post and typed availability remain queryable without inventing file URLs

### Requirement: Provider hashes remain declared assertions
An MD5 or other file hash supplied by a Danbooru-family provider SHALL be stored as a declared
occurrence assertion with provider provenance and SHALL NOT be exposed as locally verified unless
catalog-managed bytes independently verify it.

#### Scenario: Metadata-only post has an MD5
- **WHEN** a post response supplies an MD5 but no bytes are downloaded
- **THEN** the occurrence exposes the declared MD5 and has no verified asset MD5 association

#### Scenario: Later bytes disagree
- **WHEN** locally acquired bytes later produce a different MD5
- **THEN** the declared and verified values both remain visible as a mismatch

### Requirement: Uploader participation is distinct from artist attribution
When a provider supplies an uploader user ID, the adapter SHALL represent that stable platform
account as the post's uploader. Artist-category tags and booru artist records SHALL remain
community attribution entities and SHALL NOT be materialized as uploader, author, creator, or
cross-platform identity confirmation without separate evidence and review.

#### Scenario: Uploader and artist tag differ
- **WHEN** a post has uploader user `17` and artist tag `example_artist`
- **THEN** user `17` receives only the uploader role and the artist tag remains separate attribution

#### Scenario: Uploader metadata is absent
- **WHEN** the provider omits uploader identity
- **THEN** the post is stored without inventing an account participant

### Requirement: Booru artist records retain aliases and URLs
The adapter SHALL retain booru artist record IDs, names, other names, active/deleted state, linked
artist tags, and observed external URLs as platform-scoped attribution metadata distinct from
accounts and creator identities.

#### Scenario: Artist has multiple external profiles
- **WHEN** an artist record lists Pixiv and X URLs under names that do not match the booru tag
- **THEN** all URLs and names remain associated with the artist observation for later discovery and
  evidence generation

#### Scenario: Artist record is deleted
- **WHEN** the provider marks an artist record deleted
- **THEN** its stable record, aliases, URLs, and deleted state remain queryable

### Requirement: Source and Pixiv references are evidence, not conclusions
The adapter SHALL retain a post's source URL and provider `pixiv_id` as typed external references
with raw provenance. These references MAY generate reviewable match evidence but SHALL NOT
automatically confirm account ownership, creator attribution, post equivalence, or work identity.

#### Scenario: Source points to a Pixiv artwork
- **WHEN** a Danbooru post source resolves to a stable Pixiv artwork ID
- **THEN** the reference is queryable as cross-platform evidence without automatically merging the
  two posts or their accounts

### Requirement: Parent and child relations are directional and idempotent
The adapter SHALL retain provider parent and child post references as directional, platform-scoped
relations and SHALL update repeated observations without duplicating the same relation.

#### Scenario: Parent and children are returned together
- **WHEN** a post response identifies one parent and two children
- **THEN** the catalog retains the three correctly directed relations without labeling their visual
  variation type

### Requirement: Danbooru-family pagination is resumable and rate-aware
Listing operations SHALL preserve the provider continuation semantics, use keyset pagination when
supported, and obey the shared synchronization budgets and provider rate-limit state.

#### Scenario: Resume descending ID pagination
- **WHEN** a committed page yields a `b<ID>` continuation
- **THEN** a resumed run requests records after that boundary without reverting to an unbounded
  numeric page scan

#### Scenario: Rate-limit metadata is returned
- **WHEN** the instance supplies rate-limit headers
- **THEN** their non-secret state is retained and subsequent requests remain within the configured
  conservative policy and run budgets
