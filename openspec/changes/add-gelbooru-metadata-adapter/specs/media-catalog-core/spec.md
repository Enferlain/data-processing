## ADDED Requirements

### Requirement: Catalog persistence preserves Gelbooru facts and transport provenance neutrally
The catalog SHALL retain fixture-proven Gelbooru post, uploader, source, tag, rating, score, hash,
dimension, availability, and media-variant facts through provider-neutral entities plus versioned
DAPI or HTML raw observations. It MUST NOT require provider-specific duplicate tables or conflate
uploader, artist tag, external account, authorship, same-work, or variation conclusions.

#### Scenario: Existing neutral record represents a Gelbooru fact
- **WHEN** a normalized Gelbooru fact maps losslessly to an existing post, participant, tag, media occurrence, provider fact, or raw observation
- **THEN** the existing contract is reused with Gelbooru platform identity and transport provenance

#### Scenario: Required fact is not representable
- **WHEN** fixture-backed schema analysis proves a Gelbooru fact cannot retain its identity, native category, value, time, and raw provenance
- **THEN** the smallest additive provider-neutral migration is introduced with fresh, upgrade, rollback, foreign-key, and integrity coverage

#### Scenario: Metadata is not user activity
- **WHEN** a Gelbooru post enters the catalog through DAPI or HTML synchronization
- **THEN** it receives remote observation provenance but no liked or bookmarked event
