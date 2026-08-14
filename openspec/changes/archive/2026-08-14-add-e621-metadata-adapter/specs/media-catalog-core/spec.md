## ADDED Requirements

### Requirement: Catalog persistence preserves e621-specific facts neutrally
The catalog SHALL retain e621 post, attribution, tag, alias, uploader, relationship, and media facts
through provider-neutral entities plus versioned raw observations. It SHALL preserve dynamic tag
categories and optional nested fields without overwriting locally verified asset facts or
conflating uploader accounts, artist attribution, external accounts, and review conclusions.

#### Scenario: Existing schema can represent an e621 fact
- **WHEN** an e621 normalized fact maps losslessly to an existing neutral record or observation
- **THEN** the implementation reuses that contract and adds no provider-specific duplicate table

#### Scenario: Required fact is not representable
- **WHEN** a schema audit proves a required e621 alias, status, relationship, or media fact cannot be retained with its identity and provenance
- **THEN** an additive migration introduces the smallest neutral contract with validation, indexes, upgrade, rollback, and integrity coverage

#### Scenario: Reobserve an updated e621 post
- **WHEN** the same stable post is fetched after tags, sources, score, flags, relationships, or media availability change
- **THEN** stable identities remain idempotent, current projections update according to existing policy, and prior raw observations remain auditable
