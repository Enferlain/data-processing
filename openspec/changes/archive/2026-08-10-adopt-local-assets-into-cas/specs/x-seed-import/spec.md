## MODIFIED Requirements

### Requirement: Import legacy x-likes databases
The system SHALL import posts, accounts, account metadata, media occurrences, fetch state,
unavailable state, locally verified hashes, occurrence-level local file references, and raw JSON
available in a supported `x_likes` SQLite database without modifying that source database.

#### Scenario: Import an enriched likes database
- **WHEN** the user imports a supported `x_likes` database containing enriched posts and accounts
- **THEN** the catalog stores equivalent X-namespaced records and a liked observation for each source post

#### Scenario: Import unavailable content
- **WHEN** a legacy post is marked unavailable or tombstoned and has partial raw data
- **THEN** the catalog preserves its stable identifier, status, reason, observation, and raw data

#### Scenario: Import verified legacy hashes
- **WHEN** a legacy media row has MD5, SHA-256, or perceptual hashes calculated from a downloaded file
- **THEN** the catalog identifies them as locally verified values rather than provider-declared hashes

#### Scenario: Equal bytes came from different local paths
- **WHEN** two legacy media rows have the same SHA-256 but retain different local file paths
- **THEN** each media occurrence preserves its own source-file reference while both may reference the shared asset

#### Scenario: Local file has no legacy SHA-256
- **WHEN** a legacy media row contains a local file path but no SHA-256
- **THEN** the occurrence-level source reference remains eligible for later byte verification without fabricating an asset
