## ADDED REQUIREMENTS

### Requirement: Dependence classification and read-time lineage derivation
The relationship vocabulary SHALL classify kinds by their role in evidence dependence:
descent kinds (`reposted_from`, `derived_from`, `variant_of`, `reencoded_from`,
`resized_from`, `cropped_from`, `censored_variant_of`, `edited_from`, `transcoded_from`,
`extracted_from`, `thumbnail_of`) express that one side's claims or bytes likely descend from
the other; equivalence kinds (`same_bytes`, `same_work`) prove common origin without
direction; structural kinds (`page_of`, `parent_of`) anchor objects without expressing claim
descent and SHALL NOT merge lineages. The system SHALL provide a lineage-derivation surface
that computes connected components over a stated dependence edge set — descent and
equivalence kinds by default, restricted to conclusion-grade epistemic statuses (observed,
verified, derived, reviewed) and excluding rejected relationships — joined through the
structural anchoring of posts, their media occurrences, and their work anchors. Derivation
SHALL be read-only, deterministic, and offline, and SHALL NOT stamp lineage, group, or
correlation identifiers onto any retained row.

#### Scenario: The mirror chain resolves to one lineage
- **WHEN** lineage derivation runs over a repost chain where danbooru reposts pixiv, gelbooru reposts danbooru, and an archive reposts gelbooru
- **THEN** the four posts, their occurrences, and their work anchors resolve to one lineage group while four observations remain retained

#### Scenario: Same-bytes equivalence merges without a declared source
- **WHEN** occurrences of posts on different providers resolve to the same verified bytes and no provider declares a source
- **THEN** the posts resolve to one lineage group through the equivalence edges and structural anchoring

#### Scenario: A pending inferred proposal does not merge
- **WHEN** a dependence relationship exists with epistemic status `inferred` awaiting review
- **THEN** the default derivation keeps the two sides in separate lineages, and after review confirms it the two sides merge

#### Scenario: A rejected dependence separates the sides again
- **WHEN** review rejects a dependence relationship that the default policy had counted
- **THEN** subsequent derivation keeps the two sides in separate lineages while the rejected relationship and its evidence remain retained

#### Scenario: Structural kinds anchor but never merge claims
- **WHEN** two posts are linked only by a structural relationship such as `parent_of`
- **THEN** their claims resolve to separate lineages

#### Scenario: Derivation reads and never writes
- **WHEN** lineage derivation runs
- **THEN** no retained row is created, modified, or deleted, and re-running the derivation returns identical groups
