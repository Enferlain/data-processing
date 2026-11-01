# Spec Delta

## MODIFIED Requirements

### Requirement: Normalization preserves only evidenced pawchive facts
Normalization SHALL accept the flat post detail body and string identifiers the
live wire serves. A creator SHALL normalize to an account with its service, public
id, and site index timestamps as evidence; a post SHALL normalize with its
participant (creator role), brace-string or null tags as unknown-category tags,
and one media occurrence per non-empty file or attachment entry carrying the file
name, the content-addressed path, the preview-only flag, and a stable thumbnail
URL variant. Expiring signed media URLs SHALL NOT be retained in any durable
fact; empty media entries SHALL stay absent rather than becoming empty
occurrences. Zoneless provider timestamps SHALL be qualified as UTC (the
documented interpretation for zoneless provider stamps, identical to the gelbooru
HTML adapter's), and unparseable time values SHALL stay absent rather than
invented.

#### Scenario: Captured post detail normalizes under the pawchive identity
- **WHEN** the captured post detail fixture normalizes
- **THEN** it yields the post, its creator account and participant, six occurrences
  with name+path identity and thumbnail variants, and no remote original URL

#### Scenario: Expiring URL is dropped
- **WHEN** a media entry carries an expiring signed `temp_url`
- **THEN** no durable fact retains that URL

#### Scenario: Zoneless timestamp qualifies
- **WHEN** a post or account field carries a zoneless ISO timestamp
- **THEN** it normalizes as UTC and persists; unparseable time values stay absent
