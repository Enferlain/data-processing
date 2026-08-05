## Purpose

Provide a durable, platform-neutral local catalog whose normalized records, provenance, and raw
provider data can support later cross-platform discovery and matching without destructive rewrites.

## Requirements

### Requirement: Versioned catalog creation and migration
The system SHALL create a new SQLite catalog at a user-selected path, apply numbered migrations in
order, record the resulting schema version, and reject databases whose schema is newer than the
running software understands.

#### Scenario: Create a fresh catalog
- **WHEN** a user initializes a path that does not contain a catalog
- **THEN** the system creates all current schema objects and reports the current schema version

#### Scenario: Upgrade an older catalog
- **WHEN** a user opens a supported older catalog
- **THEN** the system applies each pending migration exactly once in a transaction

#### Scenario: Reject an unknown future schema
- **WHEN** the catalog schema version is newer than the software supports
- **THEN** the system exits without modifying the database and reports the version mismatch

### Requirement: Platform-namespaced records
The catalog SHALL identify remote accounts and posts using both a platform identifier and the
provider-native identifier, and SHALL permit different platforms to use the same native identifier
without collision.

#### Scenario: Equal native identifiers on different platforms
- **WHEN** accounts or posts with native identifier `123` are stored for two different platforms
- **THEN** the catalog retains them as separate records

#### Scenario: Repeat record upsert
- **WHEN** the same platform and native identifier is ingested again
- **THEN** the existing normalized record is updated without creating a duplicate

### Requirement: Temporal account metadata
The catalog SHALL retain a platform account separately from timestamped profile snapshots so that
handles, display names, biographies, profile links, counts, and account state can change over time.

#### Scenario: Account handle changes
- **WHEN** a later observation for the same stable account identifier contains a different handle
- **THEN** the catalog preserves both snapshots and exposes the latest known handle on account queries

#### Scenario: Partial profile observation
- **WHEN** a source omits optional profile fields
- **THEN** the catalog stores the available fields without inventing placeholder names or handles

### Requirement: Roleful post participation
The catalog SHALL represent post-to-account relationships with explicit roles and SHALL NOT assume
that an uploader or poster is the creator of every work appearing in the post.

#### Scenario: Store an X post author
- **WHEN** an imported X post identifies its publishing account
- **THEN** the catalog links that account to the post with an author role

#### Scenario: Creator is unknown
- **WHEN** a source identifies a post author but provides no reliable creator attribution
- **THEN** the catalog retains the author relationship and leaves creator attribution unconfirmed

### Requirement: Append-only provenance observations
The catalog SHALL record why and when a record entered the catalog as an append-only observation,
including the source import and observation type, rather than overwriting provenance with a flag.

#### Scenario: Post is both liked and bookmarked
- **WHEN** the same X post appears in a likes source and a bookmarks source
- **THEN** one post record has distinct liked and bookmarked observations

#### Scenario: Later discovery does not change user state
- **WHEN** a previously unseen post is added as discovered data
- **THEN** it does not acquire a liked or bookmarked observation

### Requirement: Raw provider record retention
The catalog SHALL preserve source records as raw bytes or losslessly serialized JSON together with
their source type, capture time, schema hint when known, and content digest.

#### Scenario: Source contains unknown fields
- **WHEN** an imported provider record contains fields with no normalized catalog column
- **THEN** those fields remain available in the retained raw record

#### Scenario: Identical raw record is seen twice
- **WHEN** the same source record content is imported repeatedly
- **THEN** the catalog can associate it with multiple import observations without duplicating the raw payload

### Requirement: Media occurrences remain distinct from assets
The catalog SHALL store remote media occurrences independently of downloaded byte assets and SHALL
allow several occurrences to refer to one verified asset without losing occurrence-specific URLs,
ordering, dimensions, alt text, or provenance.

#### Scenario: Metadata-only media
- **WHEN** a post import includes a media URL but no local file
- **THEN** the media occurrence is queryable without requiring an asset or network request

#### Scenario: Shared downloaded bytes
- **WHEN** two occurrences are later verified to have the same SHA-256
- **THEN** both occurrences can reference one asset while retaining their separate metadata

### Requirement: Catalog inspection and search
The CLI SHALL provide schema-version, integrity, summary, statistics, and text-search operations in
human-readable form and in a stable structured-output form suitable for scripts.

#### Scenario: Integrity check succeeds
- **WHEN** the user runs the integrity operation on a valid catalog
- **THEN** the command checks SQLite integrity and foreign keys and exits successfully

#### Scenario: Search without FTS5
- **WHEN** the SQLite runtime does not provide FTS5
- **THEN** text search remains available through a documented fallback and reports the active search mode

### Requirement: Foundation operations are offline
Catalog initialization, migration, inspection, search, and source import SHALL perform no network
requests and SHALL not download media.

#### Scenario: Import with network unavailable
- **WHEN** a supported local source is imported in an environment with network access disabled
- **THEN** the import completes using only the source and catalog paths supplied by the user
