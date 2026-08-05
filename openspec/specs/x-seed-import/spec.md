## Purpose

Seed the neutral catalog from the user's existing X likes database and xarchive bookmark exports
while retaining source fidelity, distinct user actions, and repeatable reconciliation evidence.

## Requirements

### Requirement: Import legacy x-likes databases
The system SHALL import posts, accounts, account metadata, media occurrences, fetch state, unavailable
state, locally verified hashes, local asset references, and raw JSON available in a supported
`x_likes` SQLite database without modifying that source database.

#### Scenario: Import an enriched likes database
- **WHEN** the user imports a supported `x_likes` database containing enriched posts and accounts
- **THEN** the catalog stores equivalent X-namespaced records and a liked observation for each source post

#### Scenario: Import unavailable content
- **WHEN** a legacy post is marked unavailable or tombstoned and has partial raw data
- **THEN** the catalog preserves its stable identifier, status, reason, observation, and raw data

#### Scenario: Import verified legacy hashes
- **WHEN** a legacy media row has MD5, SHA-256, or perceptual hashes calculated from a downloaded file
- **THEN** the catalog identifies them as locally verified values rather than provider-declared hashes

### Requirement: Import xarchive bookmark exports
The system SHALL parse supported xarchive bookmark JSON, store the export's posts, authors, profile
metadata, media occurrences, engagement metadata, unavailable state, and raw records, and add a
bookmarked observation for each bookmark entry.

#### Scenario: Bookmark with complete author metadata
- **WHEN** an xarchive entry includes a stable author identifier, handle, display name, biography, and profile links
- **THEN** the catalog stores the stable account and a timestamped profile snapshot with those values

#### Scenario: Bookmark with incomplete author metadata
- **WHEN** an xarchive entry contains an author identifier but omits a real handle or display name
- **THEN** the catalog retains the account identifier without fabricating `User <id>` or `user_<id>` values

#### Scenario: Bookmark contains multiple media items
- **WHEN** an xarchive post contains multiple images or other media entries
- **THEN** the catalog preserves every occurrence in its source order with its available URLs and metadata

### Requirement: Idempotent source imports
Each importer SHALL derive a stable import identity from the source kind, source-content digest, and
record identity so that retrying or repeating an import does not duplicate normalized records or
observations.

#### Scenario: Repeat the same file
- **WHEN** a user imports an unchanged source file more than once
- **THEN** the later run reports existing records and creates no duplicate posts, media occurrences, or observations

#### Scenario: Updated export overlaps an earlier export
- **WHEN** a later source file contains previously imported records plus new or updated records
- **THEN** existing records are reconciled and only new observations or snapshots are appended

### Requirement: Likes and bookmarks remain distinguishable
The system SHALL keep liked and bookmarked observations separately queryable even when both refer to
the same X post.

#### Scenario: Query only bookmarks
- **WHEN** the user requests statistics or search results filtered to bookmarked observations
- **THEN** liked-only posts are excluded and posts with a bookmarked observation are included

#### Scenario: Overlapping sources
- **WHEN** a post exists in both imported sources
- **THEN** source reconciliation counts one X post and two independently attributable observation types

### Requirement: Import runs are atomic and auditable
The system SHALL record an import run with source metadata, digest, start and finish state, per-entity
counts, warnings, and errors, and SHALL prevent a failed record batch from leaving unreported partial
normalized changes.

#### Scenario: Successful reconciliation
- **WHEN** an import completes successfully
- **THEN** the report includes source, accepted, inserted, updated, existing, skipped, and failed counts by entity type

#### Scenario: Malformed source record
- **WHEN** a record cannot be normalized safely
- **THEN** the importer records a bounded diagnostic tied to the import run and either rolls back its batch or reports the committed partial boundary

#### Scenario: Unsupported source schema
- **WHEN** the source does not match a supported schema or required identifier fields are missing
- **THEN** the importer exits without silently treating the source as empty and reports how it was rejected

### Requirement: Existing x-likes behavior remains compatible
Adding the catalog and importers SHALL preserve the existing `x-likes` console command, legacy
database layout, and current tests unless a future separately specified migration changes them.

#### Scenario: Run the existing CLI after installation
- **WHEN** the project is installed with the new catalog entry point
- **THEN** the `x-likes` command remains available with its existing import, enrichment, and optional download behavior
