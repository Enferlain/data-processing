# pawchive-metadata-adapter Specification

## Purpose
TBD - created by archiving change add-pawchive-metadata-adapter. Update Purpose after archive.

## Requirements

### Requirement: Pawchive metadata access is anonymous, bounded, and policy-floored
The system SHALL serve pawchive metadata through a registered single-instance adapter
family. Every request SHALL carry a descriptive non-browser User-Agent, the captured
API accept header, and a sustained interval of at least one second; response bodies
SHALL be capped at a finite byte ceiling sized for the server-fixed 50-entry listing
pages; and no credential material SHALL exist anywhere on the surface. A metadata
operation SHALL be admitted only because the `pawchive` platform key is registered in
the kernel's per-platform operation registry, and its platform row SHALL be
migration-seeded.

#### Scenario: Anonymous metadata fetch
- **WHEN** any pawchive operation runs
- **THEN** the request proceeds without credentials under the same pacing, size, and
  budget controls as every family adapter

#### Scenario: Oversized listing page
- **WHEN** a listing response body exceeds the adapter's byte ceiling
- **THEN** the run records a typed too-large outcome instead of parsing it

### Requirement: Pawchive targets compose service, creator, and post identity
Account targets SHALL be `service:user-id` and post targets
`service:user-id:post-id`. The service dimension SHALL be retained as evidence on
normalized accounts, posts, and participants rather than becoming separate platform
keys. Malformed targets SHALL fail before any network access.

#### Scenario: Post target routes to the captured endpoint
- **WHEN** a fetch post operation runs with target `patreon:75232195:70439020`
- **THEN** the request targets `/api/v1/patreon/user/75232195/post/70439020` and every
  retained row is attributed to the `pawchive` platform key

### Requirement: Listing pagination is offset-based and stateless
Listing requests SHALL page by the provider's offset parameter with the server-fixed
page size. The requested offset SHALL be embedded in the durable request target so the
next offset derives from the response alone; a page shorter than the fixed page size
SHALL terminate the listing without a continuation.

#### Scenario: Full page rolls forward
- **WHEN** a listing page returns exactly the fixed page size at offset N
- **THEN** the normalized page carries a continuation with offset N plus the page size

#### Scenario: Short page terminates
- **WHEN** a listing page returns fewer entries than the fixed page size
- **THEN** the normalized page carries no continuation

### Requirement: Normalization preserves only evidenced pawchive facts
Normalization SHALL accept the flat post detail body and string identifiers the live
wire serves. A creator SHALL normalize to an account with its service, public id, and
site index timestamps as evidence; a post SHALL normalize with its participant
(creator role), brace-string or null tags as unknown-category tags, and one media
occurrence per non-empty file or attachment entry carrying the file name, the
content-addressed path, the preview-only flag, and a stable thumbnail URL variant.
Expiring signed media URLs SHALL NOT be retained in any durable fact; empty media
entries SHALL stay absent rather than becoming empty occurrences.

#### Scenario: Captured post detail normalizes under the pawchive identity
- **WHEN** the captured post detail fixture normalizes
- **THEN** it yields the post, its creator account and participant, six occurrences
  with name+path identity and thumbnail variants, and no remote original URL

#### Scenario: Expiring URL is dropped
- **WHEN** a media entry carries an expiring signed `temp_url`
- **THEN** no durable fact retains that URL

### Requirement: Pawchive behavior is fixture-backed and offline by default
The adapter's response contracts SHALL be verified by committed, live-captured,
redacted fixture suites before any normalizer behavior is trusted; no synthetic
shapes. Contract facts observed on captures too large for the fixture size cap SHALL
be recorded in the fixture manifest. Tests SHALL run offline against those fixtures;
live checks, if ever added, SHALL be opt-in.

#### Scenario: Captured contract regression
- **WHEN** the fixture suite normalizes under the current adapter
- **THEN** the expected facts match, pinning the captured wire shapes
