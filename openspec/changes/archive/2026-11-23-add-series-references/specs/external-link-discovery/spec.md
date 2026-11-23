## ADDED requirements

### Requirement: Series references are typed evidence-only platform references

The system SHALL admit a `series` object kind on platform references with
the same source-namespaced identity as every other kind (platform, instance
host, object kind, identifier kind, native identifier, recognizer version).
A series reference SHALL use the provider's stable series identifier and
SHALL remain evidence: it SHALL NOT resolve to an account or post, SHALL NOT
serve as a match-candidate target, and SHALL NOT act as lookup seed material
unless a later change explicitly promotes it. Recognizers SHALL parse pixiv
series URLs (`www.pixiv.net/artworks/series/<id>`) into `series`/`stable_id`
references.

#### Scenario: pixiv series URL recognizes as typed evidence

- **WHEN** material contains `https://www.pixiv.net/artworks/series/12345`
- **THEN** recognition yields a pixiv `series` reference with
  `stable_id` `12345`, distinct from any artwork post reference

#### Scenario: series reference cannot become a candidate target

- **WHEN** a candidate row targets a series reference
- **THEN** the existing reference-kind guards reject the write

#### Scenario: widening preserves existing references

- **WHEN** the series-kind migration replays over an existing catalog
- **THEN** every prior platform reference row survives with its id and
  identity intact and only the admissible kind set widens
