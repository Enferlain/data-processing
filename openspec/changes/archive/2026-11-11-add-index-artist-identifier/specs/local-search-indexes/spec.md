# local-search-indexes Delta

## ADDED requirements

### Requirement: artist exports build identifier-resolution projections

`catalog index import --provider e621 --export artists` SHALL build a lookup-v1
projection of the e621 artists export (artist entries, other names, canonicalized
active/inactive URLs) registered as its own index target with its own snapshot revision,
retaining the raw export untouched under the provider's downloads directory. Refreshing
the artists projection SHALL NOT invalidate other targets' attempts.

#### Scenario: importing the artists export serves artist_identifier

- **WHEN** the artists export is imported and registered (default target
  `e621-artists`)
- **THEN** the target serves exactly `artist_identifier` and a subject whose
  source URL matches an artist entry's listed URL resolves to that artist entry
  offline

#### Scenario: posts projections do not serve artist_identifier

- **WHEN** discovery plans index methods against a posts-only projection
- **THEN** `artist_identifier` is excluded naming that the index does not serve
  the method

### Requirement: artist identifier lookups record leads, never facts

`artist_identifier` index steps SHALL probe the seed's source-URL material offline and
record matching artist entries as session-scoped leads (provider, artist native id,
name, other names, matched URL, active flag, snapshot revision) in the catalog. They
SHALL NOT create posts, occurrences, assets, or observations, and SHALL NOT plan fetch
follow-ups. Zero-result searches SHALL record their snapshot like every index method,
so a refreshed artists export replans them.

#### Scenario: a subject's source URL identifies an e621 artist offline

- **WHEN** a post seed carries a source URL that the artists export lists for
  artist `shiuk` and discovery runs without `--live`
- **THEN** the `e621-artists` index step completes offline and records an
  artist lead naming `shiuk` with the matched URL and snapshot revision

#### Scenario: artists re-import invalidates prior identifier searches

- **WHEN** an `artist_identifier` attempt recorded zero results under revision R
  and the artists export is re-imported under a new revision
- **THEN** the attempt is not fresh and the step executes again
