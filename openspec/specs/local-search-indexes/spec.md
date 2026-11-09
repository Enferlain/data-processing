# local-search-indexes Specification

## Purpose

Registered provider lookup databases (local search indexes) act as offline
discovery targets — disposable, refreshable search infrastructure whose hits
are leads for the normal fetch pipeline, never catalog facts.

## Requirements
### Requirement: index registration binds a provider lookup database

A registered index SHALL bind a unique target name, the provider platform key
used for fetch routing, the index format, the private path to its SQLite
file, and the snapshot revision recorded inside it. Registration SHALL
validate that the file exists, is readable, and self-reports the expected
format and provider. The target name — not the filesystem path — SHALL be
the target's identity in the ledger, policies, and reports: changing the
path (moved file, new artifact location) updates the registration without
creating a new target or resetting search history. Index maintenance
(register/list/import) SHALL be separate commands from discovery; discovery
only reads.

#### Scenario: register validates the projection

- **WHEN** `catalog index register` points at a file that is missing, not a
  lookup-v1 projection, or self-reports a different provider
- **THEN** registration fails naming the problem and nothing is recorded

#### Scenario: moving the file preserves the target

- **WHEN** a registered index file moves and the registration's path is
  updated to the new location
- **THEN** the target name, prior search attempts, and freshness state are
  unchanged and later runs search the same target


### Requirement: imports build a verified rebuildable projection

`catalog index import` SHALL build the lookup-v1 projection from a raw
provider artifact (e621 daily DB export: gzipped CSV with published SHA-256;
the danbooru snapshot importer is a follow-up once a concrete artifact and
its layout are verified) into a temporary database, verify the artifact
checksum when one is supplied, record snapshot identity (source digest,
revision, import scope, built-at, builder version, record counts, high-water
marks) in `index_meta`, and swap it into place transactionally. The snapshot
revision SHALL identify the actual searchable scope — artifact digest plus
builder version plus `full` when the artifact was consumed to EOF, or the
bounded prefix size otherwise — so a bounded import and a full import of the
same artifact are different snapshots. The raw artifact is
**retained untouched, separate from the derived projection**: the importer
records the artifact's path and digest and never modifies or deletes it;
the projection is rebuildable from the artifact, never the reverse.
Importing writes nothing into the primary catalog beyond the registration
row.

#### Scenario: expanding a bounded import replans prior misses

- **WHEN** a bounded import answered zero results for a subject and a full
  import of the same artifact then runs
- **THEN** the subject's index searches are not fresh under the expanded
  scope and execute again

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

### Requirement: remote results teach the index at a shared post-commit boundary

Teaching SHALL live at the shared post-commit boundary where provider posts
are persisted — the normalized-page persistence layer — so that `catalog
fetch`, direct metadata sync, candidate lookup, and discovery all teach
registered indexes whenever they persist a provider post, with no per-entry
point wiring. The post's identity (provider post id, md5, provider source
URLs including the canonical URL, artist tags) SHALL be upserted into that
provider's registered index with API origin and confirmation time. Each
teach batch SHALL be one transaction against the projection: it either lands
whole or rolls back completely, never committing a partial batch. A landed
batch that changed content SHALL bump the projection's teach overlay
generation — the generation rides the target's version alongside the base
snapshot revision, so taught content invalidates prior attempts (including
zero-result ones); a pure reconfirmation SHALL leave the generation, and
therefore freshness, unchanged. Every landed batch SHALL be recorded in a
durable per-projection teach log for inspection. Teaching SHALL be
failure-contained: index writes run after the catalog commit, are wrapped so
any error becomes at most a bounded diagnostic, and can never fail, roll
back, or delay catalog success. With no registered index the hook SHALL be a
no-op.

#### Scenario: a fetched post becomes searchable locally

- **WHEN** a gelbooru post is fetched during a live session and gelbooru has
  a registered index
- **THEN** a later offline discovery for that post's md5 finds it in the
  gelbooru index without any network request

#### Scenario: taught content invalidates a prior miss

- **WHEN** an index search completed with zero results and a remote result
  later teaches the exact md5 or source URL that would now hit
- **THEN** the prior attempt is not fresh under the bumped overlay
  generation and the search executes again, finding the taught row

#### Scenario: failed teach batch leaves no partial rows

- **WHEN** a teach batch fails partway through
- **THEN** the projection is rolled back to its pre-batch state — no rows,
  no generation bump, no teach-log entry — and the catalog write that
  triggered it remains committed
