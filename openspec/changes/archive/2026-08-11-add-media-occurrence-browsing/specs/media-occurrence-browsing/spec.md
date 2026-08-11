## Purpose

Lets users inspect synchronized posts, media occurrences, variants, provenance, and verified assets
without querying SQLite directly or causing network or filesystem side effects.

## ADDED Requirements

### Requirement: Media browsing is offline and read-only
The system SHALL browse only an existing current-version catalog through the read-only database
boundary. Browsing MUST NOT migrate or create a catalog, issue network requests, create managed
storage layout, or modify catalog or filesystem state.

#### Scenario: Browse with network and storage unavailable
- **WHEN** a user lists media occurrences while network access and managed storage are unavailable
- **THEN** the query returns catalog metadata without attempting either resource or changing the catalog

#### Scenario: Reject a non-current catalog
- **WHEN** a user browses a missing, older, or future-version catalog
- **THEN** the operation fails with bounded backup, migration, or creation guidance and does not alter the catalog

### Requirement: Occurrence listings are bounded and stable
The system SHALL return one logical row per media occurrence in ascending occurrence-identifier
order with a positive bounded limit and an opaque or occurrence-identifier continuation. It SHALL
support filters for platform, author account, post, occurrence availability, and whether a verified
asset is linked. Repeating a page against unchanged catalog state SHALL return the same rows and
ordering.

#### Scenario: List an artist's synchronized media
- **WHEN** a user filters by an instance-qualified platform account reference
- **THEN** the result contains only occurrences on posts where that account has the author role

#### Scenario: Continue a bounded listing
- **WHEN** more matching occurrences exist beyond the requested limit
- **THEN** the result includes a continuation that starts the next page strictly after the last returned occurrence

#### Scenario: Filter linked and unlinked occurrences
- **WHEN** a user requests occurrences without a verified asset association
- **THEN** the result excludes occurrences already linked to an asset and remains stably ordered

### Requirement: Browsing exposes acquisition-ready identifiers without sensitive URLs
Every occurrence result SHALL expose its stable catalog occurrence identifier, platform and native
post identity, source key, page/media index, media kind, availability, named variant keys, and a
redacted acquisition status. Variant keys and eligibility outcomes MUST agree with explicit media
acquisition planning for the same catalog state. Normal list and detail output MUST NOT expose
remote media URLs, signed query values, request headers, credentials, private paths, or retained raw
payloads.

#### Scenario: Feed a named variant into acquisition planning
- **WHEN** detail output reports occurrence `42` with an eligible `original` variant
- **THEN** selecting `42:original` in the acquisition planner resolves the same variant and eligibility without the browser revealing its URL

#### Scenario: Unsupported or malformed variant metadata
- **WHEN** an occurrence has an unsupported provider or malformed or ambiguous variant metadata
- **THEN** browsing retains the occurrence, reports a bounded exclusion reason, and does not reveal or guess a target URL

### Requirement: Detail output preserves declared and verified provenance
Occurrence detail SHALL keep provider-declared hashes, size, MIME type, and dimensions distinct from
locally verified asset facts. It SHALL include linked asset identifiers and relationships, bounded
source classifications and raw-observation identifiers, and author participation without exposing
managed or legacy paths.

#### Scenario: Declared and verified MD5 differ
- **WHEN** an occurrence's provider-declared MD5 differs from a linked asset's verified MD5
- **THEN** detail output shows both labeled values and their provenance without treating either as a replacement for the other

#### Scenario: Occurrence has private local provenance
- **WHEN** an occurrence source or linked asset location contains a private absolute or relative path
- **THEN** detail output reports only safe source/location classifications and identifiers and omits the path text

### Requirement: CLI browsing has stable machine and human interfaces
The CLI SHALL provide distinct media list and show operations. JSON output SHALL have stable keys,
bounded results, and continuations; human output SHALL identify occurrence and variant selections
that can be passed to acquisition planning. A missing occurrence or invalid filter SHALL return a
bounded error, while inspecting an unavailable or unlinked occurrence SHALL still succeed.

#### Scenario: Show an unlinked occurrence
- **WHEN** a user requests an existing unavailable or unlinked occurrence
- **THEN** the command exits successfully and reports its state and safe next action

#### Scenario: Show a missing occurrence
- **WHEN** a user requests an occurrence identifier that does not exist
- **THEN** the command exits non-successfully with a bounded error that contains no private catalog path
