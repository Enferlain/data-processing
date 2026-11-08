# Spec Delta

## Purpose

Registered provider lookup databases (local search indexes) act as offline
discovery targets — disposable, refreshable search infrastructure whose hits
are leads for the normal fetch pipeline, never catalog facts.

## ADDED Requirements

### Requirement: index registration binds a provider lookup database

A registered index SHALL bind a unique target name, the provider platform key
used for fetch routing, the index format, the private path to its SQLite
file, and the snapshot revision recorded inside it. Registration SHALL
validate that the file exists, is readable, and self-reports the expected
format and provider. Index maintenance (register/list/import) SHALL be
separate commands from discovery; discovery only reads.

#### Scenario: register validates the projection

- **WHEN** `catalog index register` points at a file that is missing, not a
  lookup-v1 projection, or self-reports a different provider
- **THEN** registration fails naming the problem and nothing is recorded

### Requirement: imports build a verified rebuildable projection

`catalog index import` SHALL build the lookup-v1 projection from a raw
provider artifact (e621 daily DB export: gzipped CSV with published SHA-256;
danbooru metadata snapshot) into a temporary database, verify the artifact
checksum when one is supplied, record snapshot identity (source digest,
revision, built-at, builder version, record counts, high-water marks) in
`index_meta`, and swap it into place transactionally. The raw artifact
SHALL remain on disk beside the projection; rebuilding from it SHALL produce
an equivalent projection. Importing writes nothing into the primary catalog
beyond the registration row.

#### Scenario: checksum mismatch refuses import

- **WHEN** the supplied artifact hash does not match its published checksum
- **THEN** import fails before any projection is built or swapped

#### Scenario: rebuilt projection replaces atomically

- **WHEN** an import completes while a discovery session holds the previous
  projection open
- **THEN** the running session sees the old snapshot to its end and later
  sessions see the new revision

### Requirement: index targets are ordinary policy-governed search targets

Registered indexes SHALL appear in discovery planning as `index`-kind targets
with one decision row per (index, method), governed by the same
include/exclude, method, and recheck policy as every other target, with the
same explanations in `--dry-run` and `--search-state`. Index steps SHALL
execute offline — without `--live` and without consuming request budget —
ordered after the local catalog steps and before provider steps. Attempt
versions SHALL embed the snapshot revision, so a refreshed snapshot makes
prior index attempts non-fresh and replans them.

#### Scenario: index steps run offline before providers

- **WHEN** a subject with an md5 and a source URL is discovered without
  `--live` against a registered e621 index
- **THEN** the index md5 and source-url steps execute and complete offline,
  and provider steps remain planned

#### Scenario: refreshed snapshot replans index searches

- **WHEN** an index whose revision changed is searched again under the
  default recheck mode
- **THEN** the prior successful attempts are not fresh and the steps execute
  again under the new revision

### Requirement: index hits are leads, never facts

Index lookups SHALL record hits as session-scoped leads (provider, provider
post id, md5, source URLs) with the snapshot revision — including zero-result
searches, which record their snapshot and scope without asserting
nonexistence. Index rows SHALL NOT create posts, occurrences, assets, or
observations. In live sessions, index hits SHALL feed the same bounded
follow-up generation as provider-lookup hits, so only the normal fetch
pipeline writes catalog facts with provenance.

#### Scenario: index hit bridges to a normal fetch

- **WHEN** an index step finds provider post 12345 in a live session
- **THEN** the session plans a `fetch_post` follow-up for that provider post
  id and no catalog record is created by the index step itself

### Requirement: remote results teach the index

After a successful provider fetch or candidate lookup, the fetched post's
identity (provider post id, md5, source URLs, artist tags) SHALL be upserted
into that provider's registered index with API origin and confirmation time.
An index write failure SHALL be recorded on the step without failing or
rolling back any catalog write, and SHALL never block the discovery result.

#### Scenario: a fetched post becomes searchable locally

- **WHEN** a gelbooru post is fetched during a live session and gelbooru has
  a registered index
- **THEN** a later offline discovery for that post's md5 finds it in the
  gelbooru index without any network request
