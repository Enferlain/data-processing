## ADDED Requirements

### Requirement: Remote raw observations are platform-associated
The catalog SHALL associate every retained remote provider response with its platform instance and,
when known, its normalized object kind and stable native identifier. Raw payload deduplication SHALL
NOT discard distinct run, request, status, schema-version, or observation-time provenance.

#### Scenario: Identical payload from independent instances
- **WHEN** two platform instances return byte-identical JSON
- **THEN** the payload bytes may be deduplicated while each platform observation remains separately
  queryable

#### Scenario: Raw response precedes successful normalization
- **WHEN** a remote response is valid JSON but incompatible with the installed normalizer
- **THEN** its platform and request provenance remain queryable without a normalized object link

### Requirement: Provider tags retain namespace, category, and observation provenance
The catalog SHALL store tags as platform-scoped entities and SHALL retain each post association's
provider spelling, category, translated label when supplied, ordering when supplied, observation
time, and raw provenance. Equal tag text from different platforms or categories SHALL NOT collide.

#### Scenario: Same text in different categories
- **WHEN** a provider uses the same tag text once as an artist tag and once as a general tag
- **THEN** the two categorized associations remain distinguishable

#### Scenario: Tag spelling changes
- **WHEN** a later observation uses a changed provider spelling or translation
- **THEN** the new observation is retained without rewriting the earlier raw provenance

### Requirement: Provider attribution entities remain separate from accounts
The catalog SHALL represent provider-defined artist or attribution records independently from
platform accounts, real-person identities, and post participants, while retaining their stable
provider IDs, names, aliases, state, tags, external URLs, and raw provenance.

#### Scenario: Artist record links to an account URL
- **WHEN** a booru artist record contains a Pixiv profile URL
- **THEN** the catalog retains the link as evidence and does not automatically merge the artist
  record with the Pixiv account

### Requirement: Media occurrences retain rich remote metadata
Metadata-only media occurrences SHALL retain provider page identity and order, media role, remote
and preview URLs, MIME or extension hints, declared file size, dimensions, duration, alt text,
variant metadata, availability, declared hashes, observation time, and raw provenance when
supplied. None of these fields SHALL require or imply downloaded bytes.

#### Scenario: Provider supplies original and preview variants
- **WHEN** a metadata response describes one original file and one preview for a page
- **THEN** both URLs and their roles remain associated with one ordered occurrence without creating
  an asset

#### Scenario: Later partial metadata omits file size
- **WHEN** a later observation omits an occurrence's previously known declared file size
- **THEN** the omission does not erase the earlier provider value or its provenance
