## Purpose

Ingest Pixiv profiles and artwork metadata as durable catalog records while preserving stable
native identifiers, multi-page ordering, provider state, and raw response provenance.

## ADDED Requirements

### Requirement: Pixiv stable identifiers define normalized identity
The Pixiv adapter SHALL identify accounts by Pixiv's stable numeric user identifier and posts by
the stable numeric artwork identifier. Mutable user names and display names SHALL be stored as
snapshot metadata and SHALL NOT replace the stable identifier.

#### Scenario: Pixiv user changes display name
- **WHEN** a later profile response has the same user ID and a different display name
- **THEN** the catalog retains another snapshot for the existing Pixiv account

#### Scenario: Artwork and user share a numeric value
- **WHEN** a user ID and artwork ID happen to contain the same digits
- **THEN** they remain distinct account and post records

### Requirement: Pixiv profiles retain available metadata and links
The adapter SHALL retain the available handle or account name, display name, biography, profile
image, background image, website and social links, follower/following counts, account state, and
observation time without inventing absent values.

#### Scenario: Profile contains external creator links
- **WHEN** a Pixiv profile response exposes website or social profile URLs
- **THEN** the URLs remain associated with the observed profile snapshot and are available to
  cross-platform discovery

#### Scenario: Partial profile response
- **WHEN** optional profile fields are absent
- **THEN** the stable account and available fields are stored without placeholders

### Requirement: Pixiv artwork metadata is retained without media acquisition
The adapter SHALL retain artwork title, caption, creation and update times when supplied, type,
page count, dimensions, tags, restriction and visibility state, canonical URL, user relationship,
and raw provider response without downloading artwork files.

#### Scenario: Fetch one illustration
- **WHEN** an available artwork detail is fetched by stable artwork ID
- **THEN** the post, publishing Pixiv account, author-role participation, raw response, tags, and
  metadata-only media occurrences are persisted together

#### Scenario: Artwork is unavailable
- **WHEN** Pixiv reports an artwork as deleted, private, restricted, or unavailable
- **THEN** the typed availability observation is retained without fabricating media URLs

### Requirement: Pixiv multi-page order and variants are preserved
The adapter SHALL create one media occurrence per Pixiv artwork page, preserve zero-based page
order and stable page identity, and retain original and preview/sample URLs and supplied dimensions
as variants of that page.

#### Scenario: Multi-page artwork
- **WHEN** an artwork response contains three ordered pages
- **THEN** exactly three metadata-only occurrences are queryable in provider page order with their
  original page URLs preserved

#### Scenario: Re-fetch changes a preview URL
- **WHEN** a later response changes a page's preview URL but retains its stable artwork and page
  identity
- **THEN** the occurrence is updated without creating a duplicate page or losing the original URL

### Requirement: Pixiv tags preserve provider meaning
The adapter SHALL retain each artwork tag's provider spelling, translated label when supplied,
provider ordering when supplied, and raw provenance. Tags SHALL NOT be interpreted as confirmed
creator identities.

#### Scenario: Tag includes a translation
- **WHEN** a Pixiv tag contains both its original label and a translated label
- **THEN** both labels remain associated with the same observed artwork tag

### Requirement: Ugoira remains an explicit metadata-only media form
For Ugoira artwork, the adapter SHALL retain the archive URL, frame sequence and delays, supplied
dimensions, MIME hints, and adapter schema version without downloading, extracting, or converting
the animation.

#### Scenario: Ugoira metadata is available
- **WHEN** Pixiv returns an Ugoira archive and ordered frame-delay records
- **THEN** the catalog retains the archive occurrence and lossless frame metadata in provider order

### Requirement: User artwork enumeration is bounded and resumable
The adapter SHALL enumerate a user's artworks only through the remote synchronization budgets and
continuation contract, and SHALL NOT implicitly enumerate a user merely because their profile or
one artwork was fetched.

#### Scenario: Fetch a profile only
- **WHEN** the user requests Pixiv profile metadata without an artwork-list operation
- **THEN** no user-artwork listing endpoint is requested

#### Scenario: Resume artwork listing
- **WHEN** a bounded user-artwork run resumes from a committed continuation
- **THEN** it continues from that provider cursor while stable artwork and page records remain
  idempotent

### Requirement: Pixiv access controls are respected
The adapter SHALL use only the configured authentication flow, SHALL surface authentication and
authorization failures as typed outcomes, and SHALL NOT fall back to browser scraping, credential
harvesting, or access-control bypasses.

#### Scenario: Refresh token is rejected
- **WHEN** Pixiv rejects the configured refresh token
- **THEN** the operation stops with an authentication-required outcome and stores no token value
