## ADDED REQUIREMENTS

### Requirement: Corroboration counts lineages, not observations
Where a surface counts sources agreeing on a claim, it SHALL distinguish observation count
from independent-corroboration count. Dependence between sources SHALL be expressed as typed
relationships from the descent and equivalence vocabularies carrying epistemic status — never
as lineage stamps on evidence rows, observation rows, or objects; evidence rows SHALL remain
single-finding facts whose grouping, if any, is detector payload. Independent corroboration
SHALL be derived at read time as lineage groups over a stated dependence policy naming the
relation kinds and epistemic statuses that count as dependence. A surface counting agreement
SHALL NOT treat N observations as N independent corroborations by default; treating
observations as independent SHALL be an explicit, stated choice of that surface. Global
provider-reliability scores SHALL NOT substitute for claim-specific dependence.

#### Scenario: Mirror chain collapses to one lineage
- **WHEN** four sources repeat a claim along a known repost/import chain (pixiv → danbooru → gelbooru → archive), each retained as its own observation and each repost recorded as a descent relationship
- **THEN** four observations remain retained while the four sources resolve to one lineage group, and a corroboration surface reports one independent lineage

#### Scenario: Byte-identical content across providers
- **WHEN** five providers serve byte-identical files linked by verified same-bytes relationships
- **THEN** five occurrences remain retained while resolving to one lineage group for origin and authorship claims

#### Scenario: Independent agreement stays independent
- **WHEN** two sources with no known dependence relationship assert the same claim
- **THEN** the claim carries two lineages and a corroboration surface reports two independent corroborations

#### Scenario: Dependence carries its own uncertainty
- **WHEN** a dependence relationship is only inferred (a pending proposal) or has been rejected by review
- **THEN** the default dependence policy does not merge the two sides, and the dependence's own epistemic status and review state remain retained with the relationship
