# local-search-indexes Delta

## ADDED requirements

### Requirement: danbooru community snapshots bootstrap posts projections

`catalog index import --provider danbooru --artifact <parquet>` SHALL build a
lookup-v1 posts projection from a danbooru community snapshot parquet,
streaming with bounded memory, reusing the proven URL extraction and
canonicalization, recording the artifact path and digest, a scope-aware
revision, and absent-column reporting. Because the snapshot carries
`tag_string_artist`, the danbooru projection SHALL also serve the
artist-name methods.

#### Scenario: snapshot import serves md5, source-URL, and artist lookups

- **WHEN** the snapshot is imported and registered (target `danbooru`)
- **THEN** md5, canonical source-URL, provider-id, and artist-name lookups
  resolve offline against it

#### Scenario: bootstrap snapshot never claims currency

- **WHEN** a subject misses the danbooru projection
- **THEN** the miss records its snapshot revision and scope and live provider
  lookups remain the fall-through path
